from __future__ import annotations

import unittest
from datetime import date

from app.dash0_export import (
    CURRENT_DAY_SUFFIX,
    GaugeSpec,
    _normalize_grpc_endpoint,
    dash0_exporter_from_env,
    latest_complete_day_spec,
    publish_gauges,
)


class NormalizeEndpointTests(unittest.TestCase):
    def test_bare_host_port_is_tls(self) -> None:
        endpoint, insecure = _normalize_grpc_endpoint(
            "ingress.us-west-2.vpce.aws.dash0.com:4317"
        )
        self.assertEqual(endpoint, "ingress.us-west-2.vpce.aws.dash0.com:4317")
        self.assertFalse(insecure)

    def test_http_scheme_is_insecure(self) -> None:
        endpoint, insecure = _normalize_grpc_endpoint("http://localhost:4317")
        self.assertEqual(endpoint, "localhost:4317")
        self.assertTrue(insecure)

    def test_https_scheme_is_secure(self) -> None:
        endpoint, insecure = _normalize_grpc_endpoint("https://ingress.dash0.com")
        self.assertEqual(endpoint, "ingress.dash0.com:4317")
        self.assertFalse(insecure)


class ExporterFromEnvTests(unittest.TestCase):
    def test_disabled_by_off(self) -> None:
        self.assertIsNone(dash0_exporter_from_env({"DASH0_INGESTION_URL": "off"}))

    def test_disabled_by_dash(self) -> None:
        self.assertIsNone(dash0_exporter_from_env({"DASH0_INGESTION_URL": "-"}))

    def test_defaults_to_vpc_endpoint(self) -> None:
        exporter = dash0_exporter_from_env({})
        self.assertIsNotNone(exporter)


class PublishGaugesTests(unittest.TestCase):
    def test_disabled_endpoint_reports_reason(self) -> None:
        result = publish_gauges(
            [GaugeSpec(name="x", unit="1", description="d", points=[(1.0, {})])],
            service_name="test-exporter",
            env={"DASH0_INGESTION_URL": "off"},
        )
        self.assertFalse(result.ok)
        self.assertIn("disabled", result.reason)

    def test_no_points_is_a_noop_success(self) -> None:
        result = publish_gauges(
            [GaugeSpec(name="x", unit="1", description="d", points=[])],
            service_name="test-exporter",
            env={"DASH0_INGESTION_URL": "off"},
        )
        # Empty points short-circuits before the endpoint check.
        self.assertTrue(result.ok)
        self.assertEqual(result.points, 0)


class LatestCompleteDaySpecTests(unittest.TestCase):
    TODAY = date(2026, 8, 20)

    def spec(self, points: list[tuple[float, dict[str, str]]]) -> GaugeSpec:
        return GaugeSpec(
            name="saas.cost.daily",
            unit="USD",
            description="Daily SaaS spend",
            points=points,
        )

    def test_keeps_only_the_latest_finished_day_and_drops_the_date(self) -> None:
        current = latest_complete_day_spec(
            self.spec(
                [
                    (1.0, {"saas.cost.date": "2026-08-18", "saas.provider": "vercel"}),
                    (2.0, {"saas.cost.date": "2026-08-19", "saas.provider": "vercel"}),
                    (4.0, {"saas.cost.date": "2026-08-19", "saas.provider": "aws"}),
                ]
            ),
            date_key="saas.cost.date",
            today=self.TODAY,
        )
        assert current is not None
        self.assertEqual(current.name, "saas.cost.daily" + CURRENT_DAY_SUFFIX)
        self.assertEqual(current.unit, "USD")
        self.assertEqual(
            sorted(current.points),
            [
                (2.0, {"saas.provider": "vercel"}),
                (4.0, {"saas.provider": "aws"}),
            ],
        )
        for _, attributes in current.points:
            self.assertNotIn("saas.cost.date", attributes)

    def test_today_is_excluded_as_still_accruing(self) -> None:
        current = latest_complete_day_spec(
            self.spec(
                [
                    (9.0, {"saas.cost.date": "2026-08-20", "saas.provider": "aws"}),
                    (3.0, {"saas.cost.date": "2026-08-19", "saas.provider": "aws"}),
                ]
            ),
            date_key="saas.cost.date",
            today=self.TODAY,
        )
        assert current is not None
        self.assertEqual(current.points, [(3.0, {"saas.provider": "aws"})])

    def test_returns_none_when_only_today_is_present(self) -> None:
        self.assertIsNone(
            latest_complete_day_spec(
                self.spec(
                    [(9.0, {"saas.cost.date": "2026-08-20", "saas.provider": "aws"})]
                ),
                date_key="saas.cost.date",
                today=self.TODAY,
            )
        )

    def test_returns_none_for_no_points(self) -> None:
        self.assertIsNone(
            latest_complete_day_spec(
                self.spec([]), date_key="saas.cost.date", today=self.TODAY
            )
        )

    def test_sums_rows_that_collide_once_the_date_is_dropped(self) -> None:
        # Two services under one provider collapse to a single point when the
        # panel groups by provider; OTLP would otherwise keep only the last.
        current = latest_complete_day_spec(
            GaugeSpec(
                name="saas.cost.daily",
                unit="USD",
                description="d",
                points=[
                    (
                        1.5,
                        {
                            "saas.cost.date": "2026-08-19",
                            "saas.provider": "aws",
                            "saas.service": "s3",
                        },
                    ),
                    (
                        2.5,
                        {
                            "saas.cost.date": "2026-08-19",
                            "saas.provider": "aws",
                            "saas.service": "ec2",
                        },
                    ),
                ],
            ),
            date_key="saas.cost.date",
            today=self.TODAY,
        )
        assert current is not None
        self.assertEqual(len(current.points), 2)
        self.assertAlmostEqual(sum(value for value, _ in current.points), 4.0)

    def test_malformed_dates_are_ignored(self) -> None:
        current = latest_complete_day_spec(
            self.spec(
                [
                    (7.0, {"saas.cost.date": "not-a-date", "saas.provider": "aws"}),
                    (5.0, {"saas.cost.date": "2026-08-19", "saas.provider": "aws"}),
                ]
            ),
            date_key="saas.cost.date",
            today=self.TODAY,
        )
        assert current is not None
        self.assertEqual(current.points, [(5.0, {"saas.provider": "aws"})])

    def test_works_for_the_aws_and_llm_date_keys(self) -> None:
        for date_key, name in (
            ("aws.cost.date", "aws.cost.unblended"),
            ("llm.cost.date", "llm.cost.estimated"),
        ):
            with self.subTest(date_key=date_key):
                current = latest_complete_day_spec(
                    GaugeSpec(
                        name=name,
                        unit="USD",
                        description="d",
                        points=[(6.0, {date_key: "2026-08-19", "k": "v"})],
                    ),
                    date_key=date_key,
                    today=self.TODAY,
                )
                assert current is not None
                self.assertEqual(current.name, name + CURRENT_DAY_SUFFIX)
                self.assertEqual(current.points, [(6.0, {"k": "v"})])


if __name__ == "__main__":
    unittest.main()
