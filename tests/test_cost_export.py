from __future__ import annotations

import logging
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from app.cost_export import (
    CostReport,
    CostWindowError,
    lookback_days_from_env,
    resolve_range,
    run_export,
)
from app.dash0_export import PublishResult

WINDOW_DAYS = 14


class ResolveRangeTests(unittest.TestCase):
    def test_default_window_is_derived_from_utc_not_container_local_time(self) -> None:
        with patch("app.cost_export.datetime") as clock:
            clock.now.return_value = datetime(2026, 8, 14, 23, 30, tzinfo=timezone.utc)
            window = resolve_range(None, None, WINDOW_DAYS)

        clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(window.end, date(2026, 8, 15))
        self.assertEqual(window.start, date(2026, 8, 1))
        self.assertEqual(window.until, "2026-08-14")

    def test_default_window_spans_the_lookback_including_today(self) -> None:
        window = resolve_range(None, None, 3)
        self.assertEqual((window.end - window.start).days, 3)

    def test_inclusive_until_becomes_exclusive_end(self) -> None:
        window = resolve_range("2026-07-01", "2026-07-31", WINDOW_DAYS)
        self.assertEqual(window.start, date(2026, 7, 1))
        self.assertEqual(window.end, date(2026, 8, 1))

    def test_non_positive_lookback_still_yields_a_day(self) -> None:
        window = resolve_range(None, None, 0)
        self.assertEqual((window.end - window.start).days, 1)

    def test_until_before_since_is_rejected(self) -> None:
        with self.assertRaises(CostWindowError):
            resolve_range("2026-07-31", "2026-07-01", WINDOW_DAYS)

    def test_malformed_date_is_rejected(self) -> None:
        with self.assertRaises(CostWindowError):
            resolve_range("07/01/2026", None, WINDOW_DAYS)

    def test_since_and_until_share_one_clock_read(self) -> None:
        with patch("app.cost_export.datetime") as clock:
            clock.now.return_value = datetime(2026, 8, 14, 23, 59, tzinfo=timezone.utc)
            window = resolve_range(None, None, 14)
        clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual((window.end - window.start).days, 14)


class LookbackEnvTests(unittest.TestCase):
    def test_valid_value_is_used(self) -> None:
        with patch.dict(os.environ, {"AWS_COST_LOOKBACK_DAYS": "7"}, clear=False):
            self.assertEqual(lookback_days_from_env("AWS_COST_LOOKBACK_DAYS", 14), 7)

    def test_unset_and_unparseable_values_fall_back(self) -> None:
        for value in ("", "  ", "fourteen"):
            with patch.dict(os.environ, {"AWS_COST_LOOKBACK_DAYS": value}, clear=False):
                self.assertEqual(lookback_days_from_env("AWS_COST_LOOKBACK_DAYS", 14), 14)


class RunExportTests(unittest.TestCase):
    def test_dry_run_skips_publish_and_succeeds_when_rows_exist(self) -> None:
        published: list[object] = []
        window = resolve_range("2026-08-01", "2026-08-01", 14)

        def fetch(since, until, days):  # noqa: ANN001
            return CostReport(rows=["row"], window=window)

        code = run_export(
            ["--dry-run", "--since", "2026-08-01", "--until", "2026-08-01"],
            description="t",
            lookback_env="AWS_COST_LOOKBACK_DAYS",
            default_lookback=14,
            dry_run_help="dry",
            fetch_failed="failed",
            fetch=fetch,
            format_row=str,
            publish=lambda rows: published.append(rows) or PublishResult(True, points=1),
            published_label="metric",
            log=logging.getLogger("test_export"),
        )
        self.assertEqual(code, 0)
        self.assertEqual(published, [])

    def test_fetch_errors_become_exit_one(self) -> None:
        def fetch(since, until, days):  # noqa: ANN001
            raise CostWindowError("until must be on or after since")

        code = run_export(
            ["--since", "2026-08-31", "--until", "2026-08-01"],
            description="t",
            lookback_env="AWS_COST_LOOKBACK_DAYS",
            default_lookback=14,
            dry_run_help="dry",
            fetch_failed="failed",
            fetch=fetch,
            format_row=str,
            publish=lambda rows: PublishResult(True, points=0),
            published_label="metric",
            log=logging.getLogger("test_export"),
        )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
