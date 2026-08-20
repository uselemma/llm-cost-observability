from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app import export_saas_costs as exporter
from app.vendors.base import CostRow, VendorCostError


def _row(provider="aws", service="EKS", day="2026-08-13", cost=1.0, **kwargs):
    return CostRow(
        date=day, provider=provider, service=service, cost_usd=cost, **kwargs
    )


class SelectVendorsTests(unittest.TestCase):
    def test_defaults_to_configured_vendors_only(self) -> None:
        fake = {
            "on": mock.Mock(is_configured=lambda env=None: True),
            "off": mock.Mock(is_configured=lambda env=None: False),
        }
        with mock.patch.dict(exporter.VENDORS, fake, clear=True):
            selected, skipped = exporter.select_vendors(None)
        self.assertEqual(selected, ["on"])
        self.assertEqual(skipped, ["off"])

    def test_explicit_request_bypasses_configuration_check(self) -> None:
        fake = {"off": mock.Mock(is_configured=lambda env=None: False)}
        with mock.patch.dict(exporter.VENDORS, fake, clear=True):
            selected, skipped = exporter.select_vendors("off")
        self.assertEqual(selected, ["off"])
        self.assertEqual(skipped, [])

    def test_unknown_vendor_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            exporter.select_vendors("nope")


class AggregateTests(unittest.TestCase):
    def test_sums_duplicate_attribute_sets(self) -> None:
        points = exporter.aggregate([_row(cost=1.0), _row(cost=2.5)])
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0][0], 3.5)

    def test_keeps_distinct_services_apart(self) -> None:
        points = exporter.aggregate([_row(service="EKS"), _row(service="S3")])
        self.assertEqual(len(points), 2)

    def test_drops_rows_that_net_to_zero(self) -> None:
        self.assertEqual(exporter.aggregate([_row(cost=1.0), _row(cost=-1.0)]), [])

    def test_point_attributes_are_promql_ready(self) -> None:
        points = exporter.aggregate([_row()])
        self.assertEqual(
            set(points[0][1]),
            {
                "saas.cost.date",
                "saas.provider",
                "saas.service",
                "saas.cost.source",
                "saas.env",
            },
        )


class CollectTests(unittest.TestCase):
    def test_one_failing_vendor_does_not_sink_the_others(self) -> None:
        # spec pins the vendor interface: a bare Mock answers hasattr() for
        # everything, so it would masquerade as a coverage-reporting vendor.
        good = mock.Mock(
            spec=["fetch"], fetch=lambda s, e, env=None: [_row(provider="good")]
        )
        bad = mock.Mock(
            spec=["fetch"],
            fetch=mock.Mock(side_effect=VendorCostError("token expired")),
        )
        with mock.patch.dict(
            exporter.VENDORS, {"good": good, "bad": bad}, clear=True
        ):
            rows, errors, _ = exporter.collect(
                ["good", "bad"], date(2026, 8, 13), date(2026, 8, 14)
            )
        self.assertEqual([row.provider for row in rows], ["good"])
        self.assertEqual(len(errors), 1)
        self.assertIn("token expired", errors[0])

    def test_unexpected_exception_is_contained(self) -> None:
        boom = mock.Mock(
            spec=["fetch"], fetch=mock.Mock(side_effect=RuntimeError("kaboom"))
        )
        with mock.patch.dict(exporter.VENDORS, {"boom": boom}, clear=True):
            rows, errors, _ = exporter.collect(
                ["boom"], date(2026, 8, 13), date(2026, 8, 14)
            )
        self.assertEqual(rows, [])
        self.assertIn("RuntimeError", errors[0])

    def test_cloudflare_coverage_warning_is_surfaced(self) -> None:
        from app.vendors import cloudflare as cf

        with mock.patch.dict(exporter.VENDORS, {"cloudflare": cf}, clear=True):
            with mock.patch.object(
                cf, "fetch_with_coverage", return_value=([], "partial period")
            ):
                _, _, warnings = exporter.collect(
                    ["cloudflare"], date(2026, 8, 13), date(2026, 8, 14)
                )
        self.assertTrue(any("partial period" in w for w in warnings))


class PublishTests(unittest.TestCase):
    def _publish(self, rows):
        captured: dict[str, object] = {}

        def fake_publish(specs, *, service_name, env=None):
            captured["specs"] = specs
            return exporter.PublishResult(ok=True, points=len(specs[0].points))

        with mock.patch.object(exporter, "publish_gauges", side_effect=fake_publish):
            result = exporter.publish_saas_cost_gauges(rows)
        return captured["specs"], result

    def test_publishes_dated_gauge_with_usd_unit(self) -> None:
        specs, result = self._publish([_row()])
        self.assertEqual(specs[0].name, "saas.cost.daily")
        self.assertEqual(specs[0].unit, "USD")
        self.assertTrue(result.ok)

    def test_also_publishes_the_date_free_trend_gauge(self) -> None:
        specs, _ = self._publish([_row()])
        self.assertEqual(
            [spec.name for spec in specs],
            ["saas.cost.daily", "saas.cost.daily.current"],
        )
        # The trend gauge must not carry the date, or each day becomes its own
        # series and the chart is back to one line per vendor per day.
        for _, attributes in specs[1].points:
            self.assertNotIn("saas.cost.date", attributes)

    def test_trend_gauge_is_omitted_when_no_day_has_finished(self) -> None:
        today = date.today().isoformat()
        specs, result = self._publish([_row(day=today)])
        self.assertEqual([spec.name for spec in specs], ["saas.cost.daily"])
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
