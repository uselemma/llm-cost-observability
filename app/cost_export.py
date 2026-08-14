"""Shared window, report, and CLI loop for one-shot cost → Dash0 exporters."""
from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Generic, TypeVar

from app.dash0_export import PublishResult

T = TypeVar("T")


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
    publish: Callable[[Sequence[T]], PublishResult],
    published_label: str,
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

    log.info(
        "fetched %d rows (%s .. %s)%s",
        len(report.rows),
        report.window.since,
        report.window.until,
        f"; account errors={'; '.join(report.errors)}" if report.errors else "",
    )

    if args.dry_run:
        preview = list(report.rows[:20])
        for row in preview:
            log.info("%s", format_row(row))
        if len(report.rows) > 20:
            log.info("... %d more rows", len(report.rows) - 20)
        return 0 if report.rows or not report.errors else 1

    result = publish(report.rows)
    if not result.ok:
        log.error("dash0 export failed: %s", result.reason)
        return 1

    log.info("published %d %s to Dash0", result.points, published_label)
    if report.errors:
        log.warning("partial fetch failures: %s", "; ".join(report.errors))
        return 0 if result.points else 1
    return 0
