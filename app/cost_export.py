"""Shared window, report, and CLI loop for one-shot cost → Dash0 exporters.

Both CronJobs are the same machine: resolve a UTC day window, fetch rows, then
either preview them or turn each row into one or more OTLP gauges. Domain
modules fetch; exporter modules declare metric schema as GaugeBinding data.
"""
from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Generic, TypeVar

from app.dash0_export import GaugeSpec, publish_gauges

T = TypeVar("T")

DEFAULT_LOOKBACK_DAYS = 14
_DRY_RUN_PREVIEW = 20


class CostExportError(Exception):
    """Fetch or window failure the CLI maps to a non-zero exit."""


class CostWindowError(CostExportError):
    """Invalid since/until/lookback window."""


@dataclass(frozen=True)
class CostWindow:
    start: date  # inclusive
    end: date  # exclusive

    @property
    def since(self) -> str:
        return self.start.isoformat()

    @property
    def until(self) -> str:
        return (self.end - timedelta(days=1)).isoformat()


@dataclass(frozen=True)
class CostReport(Generic[T]):
    rows: Sequence[T]
    window: CostWindow
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class GaugeBinding(Generic[T]):
    """How one OTLP gauge is projected from a cost row."""

    name: str
    unit: str
    description: str
    value: Callable[[T], float]


def parse_day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise CostWindowError(f"invalid {field} date, expected YYYY-MM-DD") from exc


def resolve_range(
    since: str | None,
    until: str | None,
    lookback_days: int,
) -> CostWindow:
    """Return a UTC day window. ``until`` is an inclusive calendar day."""
    default_end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = (
        parse_day(since, "since")
        if since
        else default_end - timedelta(days=max(1, lookback_days))
    )
    end = parse_day(until, "until") + timedelta(days=1) if until else default_end
    if end <= start:
        raise CostWindowError("until must be on or after since")
    return CostWindow(start=start, end=end)


def lookback_days_from_env(name: str, default: int) -> int:
    """Read a lookback env var; a bad value must not crash the CronJob."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger("cost_export").warning(
            "ignoring invalid %s=%r; using %d", name, raw, default
        )
        return default


def build_gauge_specs(
    rows: Sequence[T],
    gauges: Sequence[GaugeBinding[T]],
    attributes: Callable[[T], dict[str, str]],
) -> list[GaugeSpec]:
    """Project rows onto the declared gauges. One spec per binding, one point per row."""
    return [
        GaugeSpec(
            name=gauge.name,
            unit=gauge.unit,
            description=gauge.description,
            points=[(gauge.value(row), attributes(row)) for row in rows],
        )
        for gauge in gauges
    ]


def run_export(
    argv: list[str] | None,
    *,
    description: str,
    lookback_env: str,
    default_lookback: int,
    dry_run_help: str,
    fetch_failed: str,
    fetch: Callable[[str | None, str | None, int], CostReport[T]],
    format_row: Callable[[T], str],
    attributes: Callable[[T], dict[str, str]],
    gauges: Sequence[GaugeBinding[T]],
    service_name: str,
    log: logging.Logger,
) -> int:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--since", help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--until", help="Inclusive end date YYYY-MM-DD")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=lookback_days_from_env(lookback_env, default_lookback),
        help=f"Days to fetch when --since/--until omitted (default {default_lookback})",
    )
    parser.add_argument("--dry-run", action="store_true", help=dry_run_help)
    args = parser.parse_args(argv)

    try:
        report = fetch(args.since, args.until, args.lookback_days)
    except CostExportError as exc:
        log.error("%s: %s", fetch_failed, exc)
        return 1

    error_note = f"; errors={'; '.join(report.errors)}" if report.errors else ""
    log.info(
        "fetched %d rows (%s .. %s)%s",
        len(report.rows),
        report.window.since,
        report.window.until,
        error_note,
    )

    if args.dry_run:
        preview = list(report.rows[:_DRY_RUN_PREVIEW])
        for row in preview:
            log.info("%s", format_row(row))
        extra = len(report.rows) - len(preview)
        if extra:
            log.info("... %d more rows", extra)
        return 1 if report.errors and not report.rows else 0

    result = publish_gauges(
        build_gauge_specs(report.rows, gauges, attributes),
        default_service_name=service_name,
    )
    if not result.ok:
        log.error("dash0 export failed: %s", result.reason)
        return 1

    log.info(
        "published %d %s to Dash0",
        result.points,
        " / ".join(gauge.name for gauge in gauges),
    )
    if report.errors:
        log.warning("partial fetch failures: %s", "; ".join(report.errors))
        return 1 if not result.points else 0
    return 0
