from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.dash0_export import (
    GaugeSpec,
    _normalize_grpc_endpoint,
    dash0_exporter_from_env,
    publish_gauges,
)


class EndpointTests(unittest.TestCase):
    def test_bare_host_port_uses_tls(self) -> None:
        self.assertEqual(
            _normalize_grpc_endpoint("ingress.us-west-2.vpce.aws.dash0.com:4317"),
            ("ingress.us-west-2.vpce.aws.dash0.com:4317", False),
        )

    def test_http_scheme_is_insecure_and_defaults_the_port(self) -> None:
        self.assertEqual(
            _normalize_grpc_endpoint("http://collector.lemma.svc/"),
            ("collector.lemma.svc:4317", True),
        )

    def test_https_scheme_keeps_tls(self) -> None:
        endpoint, insecure = _normalize_grpc_endpoint("https://ingest.example.com:443")
        self.assertEqual(endpoint, "ingest.example.com:443")
        self.assertFalse(insecure)

    def test_url_without_a_host_is_rejected(self) -> None:
        for raw in ("http:///v1/metrics", "http://:4317"):
            with self.assertRaises(ValueError):
                _normalize_grpc_endpoint(raw)


class ExporterFromEnvTests(unittest.TestCase):
    def test_export_can_be_disabled(self) -> None:
        for value in ("off", "none", "-", "OFF"):
            with patch.dict(os.environ, {"DASH0_INGESTION_URL": value}, clear=False):
                self.assertIsNone(dash0_exporter_from_env())

    def test_disabled_endpoint_short_circuits_publish(self) -> None:
        spec = GaugeSpec(name="x", unit="1", description="d", points=[(1.0, {"a": "b"})])
        with patch.dict(os.environ, {"DASH0_INGESTION_URL": "off"}, clear=False):
            result = publish_gauges([spec], default_service_name="test-exporter")

        self.assertFalse(result.ok)
        self.assertEqual(result.points, 0)
        self.assertIn("disabled", result.reason)


class PublishGaugesTests(unittest.TestCase):
    def test_empty_input_succeeds_without_contacting_dash0(self) -> None:
        spec = GaugeSpec(name="x", unit="1", description="d", points=[])
        with patch("app.dash0_export.dash0_exporter_from_env") as exporter_factory:
            exporter_factory.return_value = object()
            result = publish_gauges([spec], default_service_name="test-exporter")

        self.assertTrue(result.ok)
        self.assertEqual(result.points, 0)

    def test_successful_export_reports_the_point_count(self) -> None:
        from opentelemetry.sdk.metrics.export import MetricExportResult

        exported: list[object] = []

        class FakeExporter:
            def export(self, metrics_data, timeout_millis=None):  # noqa: ANN001
                exported.append(metrics_data)
                return MetricExportResult.SUCCESS

            def shutdown(self, timeout_millis=None):  # noqa: ANN001
                return None

        spec = GaugeSpec(
            name="aws.cost.unblended",
            unit="USD",
            description="d",
            points=[(1.0, {"a": "b"}), (2.0, {"a": "c"})],
        )
        with patch("app.dash0_export.dash0_exporter_from_env", return_value=FakeExporter()):
            result = publish_gauges([spec], default_service_name="test-exporter")

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.points, 2)
        self.assertEqual(len(exported), 1)

    def test_failed_export_is_reported_not_raised(self) -> None:
        from opentelemetry.sdk.metrics.export import MetricExportResult

        class FailingExporter:
            def export(self, metrics_data, timeout_millis=None):  # noqa: ANN001
                return MetricExportResult.FAILURE

            def shutdown(self, timeout_millis=None):  # noqa: ANN001
                return None

        spec = GaugeSpec(name="x", unit="1", description="d", points=[(1.0, {})])
        with patch("app.dash0_export.dash0_exporter_from_env", return_value=FailingExporter()):
            result = publish_gauges([spec], default_service_name="test-exporter")

        self.assertFalse(result.ok)
        self.assertIn("OTLP export failed", result.reason)


if __name__ == "__main__":
    unittest.main()
