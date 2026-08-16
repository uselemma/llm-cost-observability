from __future__ import annotations

import unittest

from app.dash0_export import (
    GaugeSpec,
    _normalize_grpc_endpoint,
    dash0_exporter_from_env,
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


if __name__ == "__main__":
    unittest.main()
