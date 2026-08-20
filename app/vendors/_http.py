"""Minimal JSON/JSONL HTTP helper for the vendor billing adapters.

Deliberately stdlib-only: the exporter image already carries boto3,
clickhouse-connect and the OTEL SDK, and none of these billing calls need
more than a GET with a header and a timeout. Adding `requests` here would
grow the CronJob image for three function calls.
"""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
from typing import Any, Iterator

DEFAULT_TIMEOUT = 60


class HttpError(Exception):
    """Non-2xx response or transport failure, with the body when we have one."""


def _open(url: str, headers: dict[str, str], timeout: int):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # Billing APIs put the useful part (bad key, wrong role, unsupported
        # plan) in the body, not the status line -- keep a slice of it.
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise HttpError(f"HTTP {exc.code} from {url.split('?')[0]}: {body}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"cannot reach {url.split('?')[0]}: {exc.reason}") from exc


def get_json(
    url: str, headers: dict[str, str], timeout: int = DEFAULT_TIMEOUT
) -> Any:
    with _open(url, headers, timeout) as response:
        raw = response.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise HttpError(f"non-JSON response from {url.split('?')[0]}") from exc


def get_jsonl(
    url: str, headers: dict[str, str], timeout: int = DEFAULT_TIMEOUT
) -> Iterator[dict]:
    """Stream newline-delimited JSON, transparently gunzipping if needed.

    Blank lines are skipped; a malformed line raises rather than being
    dropped, because silently losing charge records would understate spend.
    """
    merged = {"Accept-Encoding": "gzip", **headers}
    with _open(url, merged, timeout) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError as exc:
            raise HttpError(f"malformed JSONL at line {number}") from exc
