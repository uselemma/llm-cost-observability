"""Shared plumbing for the finops cost-export CronJobs.

One-shot OTLP/gRPC gauge publishing to Dash0. Metrics are collected with an
InMemoryMetricReader and handed to the exporter directly so the export result is
checked synchronously — no background reader, no flush-timing races.

Env: DASH0_INGESTION_URL ("off"/"none"/"-" disables), DASH0_INGESTION_KEY or
DASH0_TOKEN, DASH0_DATASET (default production), OTEL_SERVICE_NAME.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExportResult,
)
from opentelemetry.sdk.resources import Resource

DEFAULT_DASH0_ENDPOINT = "ingress.us-west-2.vpce.aws.dash0.com:4317"


@dataclass(frozen=True)
class GaugeSpec:
    """One gauge instrument plus its (value, attributes) data points."""

    name: str
    unit: str
    description: str
    points: list[tuple[float, dict[str, str]]]


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    points: int = 0
    reason: str = ""


def _normalize_grpc_endpoint(raw: str) -> tuple[str, bool]:
    """Return (host:port, insecure). Bare host:port implies TLS (VPC endpoint)."""
    trimmed = raw.strip().rstrip("/")
    if "://" not in trimmed:
        return trimmed, False
    parsed = urlparse(trimmed)
    if not parsed.hostname:
        raise ValueError(f"invalid Dash0 endpoint: {raw!r}")
    port = parsed.port or 4317
    return f"{parsed.hostname}:{port}", parsed.scheme == "http"


def dash0_exporter_from_env() -> OTLPMetricExporter | None:
    """Build the OTLP/gRPC exporter from DASH0_* env; None when disabled."""
    raw = (os.environ.get("DASH0_INGESTION_URL") or DEFAULT_DASH0_ENDPOINT).strip()
    if not raw or raw.lower() in ("-", "none", "off"):
        return None

    key = (
        os.environ.get("DASH0_INGESTION_KEY") or os.environ.get("DASH0_TOKEN") or ""
    ).strip()
    dataset = (os.environ.get("DASH0_DATASET") or "production").strip()
    headers: list[tuple[str, str]] = []
    if key:
        headers.append(("authorization", f"Bearer {key}"))
    if dataset:
        headers.append(("dash0-dataset", dataset))

    endpoint, insecure = _normalize_grpc_endpoint(raw)
    return OTLPMetricExporter(
        endpoint=endpoint,
        insecure=insecure,
        headers=tuple(headers) if headers else None,
        timeout=15,
    )


def publish_gauges(
    specs: list[GaugeSpec],
    *,
    default_service_name: str,
) -> PublishResult:
    """Record the given gauges and export them to Dash0 in a single shot."""
    exporter = dash0_exporter_from_env()
    if exporter is None:
        return PublishResult(ok=False, reason="DASH0_INGESTION_URL disabled/unset")

    points = sum(len(spec.points) for spec in specs)
    if points == 0:
        return PublishResult(ok=True, reason="no data points")

    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create(
            {
                "service.name": (os.environ.get("OTEL_SERVICE_NAME") or "").strip()
                or default_service_name,
                "service.namespace": "finops",
            }
        ),
        metric_readers=[reader],
    )

    try:
        meter = provider.get_meter(default_service_name, "0.1.0")
        for spec in specs:
            gauge = meter.create_gauge(
                spec.name,
                unit=spec.unit,
                description=spec.description,
            )
            for value, attributes in spec.points:
                # Python OTEL Gauge uses set(); JS SDK uses record().
                gauge.set(value, attributes)

        metrics_data = reader.get_metrics_data()
        if metrics_data is None:
            return PublishResult(ok=False, reason="no metrics collected")
        result = exporter.export(metrics_data, timeout_millis=30_000)
        if result != MetricExportResult.SUCCESS:
            return PublishResult(
                ok=False, reason="OTLP export failed (check Dash0 endpoint/token)"
            )
        return PublishResult(ok=True, points=points)
    except Exception as exc:  # noqa: BLE001 — CLI must not crash on export quirks
        return PublishResult(ok=False, reason=str(exc))
    finally:
        for closer in (exporter.shutdown, provider.shutdown):
            try:
                closer(timeout_millis=10_000)
            except Exception:  # noqa: BLE001
                pass
