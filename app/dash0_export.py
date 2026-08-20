"""Generic OTLP/gRPC gauge publish to Dash0, shared by the finops exporters.

Each exporter (app.export_aws_costs, app.export_llm_costs) builds a list of
GaugeSpec and hands it to publish_gauges, which owns the OTLP wiring: build a
MeterProvider, record every point, export once synchronously, and report
whether the export actually succeeded (not just whether it was attempted).
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
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
class PublishResult:
    ok: bool
    points: int = 0
    reason: str = ""


@dataclass(frozen=True)
class GaugeSpec:
    """One gauge instrument plus the (value, attributes) points to record."""

    name: str
    unit: str
    description: str
    points: list[tuple[float, dict[str, str]]]


# Suffix for the date-free companion of a dated cost gauge.
CURRENT_DAY_SUFFIX = ".current"


def latest_complete_day_spec(
    spec: GaugeSpec,
    *,
    date_key: str,
    today: date | None = None,
) -> GaugeSpec | None:
    """Derive a date-free gauge holding only the most recent finished day.

    The dated gauges carry the calendar day as an attribute and re-publish the
    entire lookback window on every run. That makes a per-day trend chart
    impossible: grouping by the date attribute yields one series per entity
    *per date* (55 series on the SaaS panel), and the date can never move to
    the x-axis because every sample is stamped at publish time -- Dash0
    discards backdated points outright, returning success while dropping
    anything older than roughly half an hour.

    Dropping the date attribute and keeping a single finished day fixes that:
    each run contributes exactly one point per entity, so consecutive runs
    accumulate a real daily trend with one series per entity. Values are
    copied verbatim from `spec`, so the trend can never disagree with the
    totals computed from the dated gauge.

    Note the deliberate one-day offset -- the point published today carries
    yesterday's cost, because today is still accruing and backfilling later
    is impossible.

    Returns None when no finished day is present.
    """
    reference = today or datetime.now(timezone.utc).date()

    finished: list[date] = []
    for _, attributes in spec.points:
        raw = attributes.get(date_key, "")
        try:
            day = date.fromisoformat(raw.strip()[:10])
        except ValueError:
            continue
        if day < reference:
            finished.append(day)
    if not finished:
        return None

    target = max(finished).isoformat()
    totals: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
    for value, attributes in spec.points:
        if attributes.get(date_key, "").strip()[:10] != target:
            continue
        rest = {k: v for k, v in attributes.items() if k != date_key}
        totals[tuple(sorted(rest.items()))] += value

    if not totals:
        return None

    return GaugeSpec(
        name=f"{spec.name}{CURRENT_DAY_SUFFIX}",
        unit=spec.unit,
        description=(
            f"{spec.description} -- most recent complete day only, published "
            "without a date attribute so each run appends one point per "
            "entity and the series forms a daily trend"
        ),
        points=[(value, dict(key)) for key, value in sorted(totals.items())],
    )


def _normalize_grpc_endpoint(raw: str) -> tuple[str, bool]:
    """Return (host:port, insecure). Bare host:port implies TLS (VPC endpoint)."""
    trimmed = raw.strip().rstrip("/")
    if not trimmed:
        raise ValueError("empty Dash0 endpoint")
    if "://" not in trimmed:
        return trimmed, False
    parsed = urlparse(trimmed)
    if not parsed.hostname:
        raise ValueError(f"invalid Dash0 endpoint: {raw!r}")
    port = parsed.port or (4317 if parsed.scheme in ("http", "https") else None)
    hostport = parsed.hostname if port is None else f"{parsed.hostname}:{port}"
    return hostport, parsed.scheme == "http"


def dash0_exporter_from_env(
    env: dict[str, str] | None = None,
) -> OTLPMetricExporter | None:
    """Build the OTLP/gRPC exporter from DASH0_* env; None when disabled."""
    e = env if env is not None else os.environ
    raw = (e.get("DASH0_INGESTION_URL") or DEFAULT_DASH0_ENDPOINT).strip()
    if not raw or raw.lower() in ("-", "none", "off"):
        return None

    key = (e.get("DASH0_INGESTION_KEY") or e.get("DASH0_TOKEN") or "").strip()
    dataset = (e.get("DASH0_DATASET") or "production").strip()
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
    service_name: str,
    env: dict[str, str] | None = None,
) -> PublishResult:
    """Record every gauge in specs and export once, synchronously, to Dash0.

    Uses InMemoryMetricReader + a direct exporter.export() call (no
    background PeriodicExportingMetricReader) so the OTLP result is checked
    before the process exits — required for a one-shot CronJob.
    """
    total_points = sum(len(s.points) for s in specs)
    if total_points == 0:
        return PublishResult(ok=True, points=0, reason="no data points")

    e = env if env is not None else os.environ
    exporter = dash0_exporter_from_env(e)
    if exporter is None:
        return PublishResult(ok=False, reason="DASH0_INGESTION_URL disabled/unset")

    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create(
            {
                "service.name": e.get("OTEL_SERVICE_NAME", service_name).strip()
                or service_name,
                "service.namespace": "finops",
            }
        ),
        metric_readers=[reader],
    )

    try:
        meter = provider.get_meter(service_name, "0.1.0")
        for spec in specs:
            gauge = meter.create_gauge(
                spec.name, unit=spec.unit, description=spec.description
            )
            for value, attributes in spec.points:
                # Python OTEL Gauge uses set(); JS SDK uses record().
                gauge.set(float(value), attributes)

        metrics_data = reader.get_metrics_data()
        if metrics_data is None:
            return PublishResult(ok=False, reason="no metrics collected")
        result = exporter.export(metrics_data, timeout_millis=30_000)
        if result != MetricExportResult.SUCCESS:
            return PublishResult(
                ok=False,
                reason="OTLP export failed (check Dash0 endpoint/token)",
            )
        return PublishResult(ok=True, points=total_points)
    except Exception as exc:  # noqa: BLE001 — CLI must not crash on export quirks
        return PublishResult(ok=False, reason=str(exc))
    finally:
        for closer in (exporter.shutdown, provider.shutdown):
            try:
                closer(timeout_millis=10_000)
            except Exception:  # noqa: BLE001
                pass
