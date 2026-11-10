"""Token prices from models.dev, used to cost calls the gateway recorded no cost for.

Cloudflare AI Gateway only prices providers it knows. Calls through a custom provider (here
`custom-vercel`) and some models (embeddings) arrive with cost 0 even though token counts are
present. For those rows we compute `tokens x price` from https://models.dev/api.json, so there
is no model list to maintain here: prices are fetched, cached, and matched to whatever model
ids actually appear in the spans.

Prices are per 1M tokens in models.dev; we convert to per-token. Cached input is priced at the
cache-read rate and cache writes at the cache-write rate (falling back to the plain input rate
when models.dev lists none). Cached-token counts come from the response body's `usage` block.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any


from app.ch import get_client

log = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
CATALOG_TTL_S = 6 * 3600  # models.dev changes slowly
PAIRS_TTL_S = 600  # which (provider, model) pairs exist in the data
PAIRS_WINDOW = "INTERVAL 30 DAY"

# Gateway provider slug -> models.dev provider ids to try first. These are provider names,
# not prices, and anything not listed falls back to a catalog-wide search by model id.
PROVIDER_HINTS: dict[str, list[str]] = {
    "azure-openai": ["azure", "openai"],
    "aws-bedrock": ["amazon-bedrock"],
    "google-vertex-ai": ["google-vertex", "google"],
    "openai": ["openai"],
    "anthropic": ["anthropic"],
    "grok": ["xai"],
    "xai": ["xai"],
    "custom-vercel": ["vercel"],
}
# When several providers list the same model id, prefer the first-party maker.
FIRST_PARTY = ["openai", "anthropic", "google", "xai", "deepseek", "zai", "mistral", "meta"]
_REGION_PREFIX = re.compile(r"^(?:us|eu|apac|ap|global|us-gov)\.", re.I)

# (input, output, cache read, cache write) in $/token
Price = tuple[float, float, float, float]


@dataclass
class _Catalog:
    # provider id -> casefolded model id -> price
    by_provider: dict[str, dict[str, Price]] = field(default_factory=dict)
    # casefolded model id -> [(provider id, price)]
    by_model: dict[str, list[tuple[str, Price]]] = field(default_factory=dict)


def _build_catalog(raw: dict[str, Any]) -> _Catalog:
    cat = _Catalog()
    for pid, provider in raw.items():
        for mid, model in (provider.get("models") or {}).items():
            cost = model.get("cost") or {}
            inp = cost.get("input")
            if inp is None:
                continue
            inp_pt = float(inp) / 1e6
            cache_read = cost.get("cache_read")
            cache_write = cost.get("cache_write")
            price: Price = (
                inp_pt,
                float(cost.get("output") or 0) / 1e6,
                float(cache_read) / 1e6 if cache_read is not None else inp_pt,
                float(cache_write) / 1e6 if cache_write is not None else inp_pt,
            )
            key = str(model.get("id") or mid).casefold()
            cat.by_provider.setdefault(pid, {})[key] = price
            cat.by_model.setdefault(key, []).append((pid, price))
    return cat


def _pick(candidates: list[tuple[str, Price]]) -> Price | None:
    if not candidates:
        return None
    for pid in FIRST_PARTY:
        for cand_pid, price in candidates:
            if cand_pid == pid:
                return price
    return candidates[0][1]


def resolve(cat: _Catalog, provider: str, model: str) -> Price | None:
    """Find the price for a span's (gateway provider, model id), or None if models.dev has none.

    Order: full id first (through the provider the call used, then any provider), then the
    creator-less name ("openai/gpt-6" -> "gpt-6", "openai.gpt-6" -> "gpt-6") the same way.
    """
    m = model.strip().casefold()
    if not m:
        return None
    stripped = _REGION_PREFIX.sub("", m)  # bedrock: "us.openai.gpt-5.6-luna"
    exact = list(dict.fromkeys([m, stripped]))
    names = []
    for form in exact:
        for sep in ("/", "."):
            head, _, tail = form.partition(sep)
            if tail and head.isalpha():
                names.append(tail)
    names = [n for n in dict.fromkeys(names) if n not in exact]
    hinted = PROVIDER_HINTS.get(provider.casefold(), [])
    for forms in (exact, names):
        for form in forms:
            for pid in hinted:
                price = cat.by_provider.get(pid, {}).get(form)
                if price:
                    return price
        for form in forms:
            price = _pick(cat.by_model.get(form, []))
            if price:
                return price
    return None


@dataclass
class Snapshot:
    keys: list[str]
    inp: list[float]
    out: list[float]
    cache_read: list[float]
    cache_write: list[float]
    unresolved: list[tuple[str, str]]


_lock = threading.Lock()
_catalog: tuple[float, _Catalog] | None = None
_snapshot: tuple[float, Snapshot] | None = None


def _get_catalog() -> _Catalog | None:
    global _catalog
    now = time.monotonic()
    if _catalog and now - _catalog[0] < CATALOG_TTL_S:
        return _catalog[1]
    try:
        req = urllib.request.Request(MODELS_DEV_URL, headers={"User-Agent": "llm-cost-observability"})
        with urllib.request.urlopen(req, timeout=15) as resp:  # raises on HTTP errors
            _catalog = (now, _build_catalog(json.load(resp)))
        log.info("loaded models.dev catalog: %d model ids", len(_catalog[1].by_model))
    except Exception as exc:  # network down, bad JSON, ...
        log.warning("models.dev fetch failed (%s); %s", exc, "using stale prices" if _catalog else "no prices")
        if _catalog:  # keep serving the last good copy, retry after a short back-off
            _catalog = (now - CATALOG_TTL_S + 300, _catalog[1])
    return _catalog[1] if _catalog else None


def _distinct_pairs() -> list[tuple[str, str]]:
    result = get_client().query(
        "SELECT DISTINCT llm_meta.provider, llm_meta.model FROM otel_traces "
        f"WHERE ServiceName = 'ai-gateway' AND Timestamp >= now() - {PAIRS_WINDOW}"
    )
    return [(p, m) for p, m in result.result_rows if m]


def get_snapshot() -> Snapshot:
    """Prices for every (provider, model) pair seen recently, as parallel arrays for SQL."""
    global _snapshot
    now = time.monotonic()
    if _snapshot and now - _snapshot[0] < PAIRS_TTL_S:
        return _snapshot[1]
    with _lock:
        if _snapshot and time.monotonic() - _snapshot[0] < PAIRS_TTL_S:
            return _snapshot[1]
        keys, inp, out, cache_read, cache_write, unresolved = [], [], [], [], [], []
        cat = _get_catalog()
        if cat is not None:
            try:
                for provider, model in _distinct_pairs():
                    price = resolve(cat, provider, model)
                    if price:
                        keys.append(f"{provider}|{model}")
                        inp.append(price[0])
                        out.append(price[1])
                        cache_read.append(price[2])
                        cache_write.append(price[3])
                    else:
                        unresolved.append((provider, model))
            except Exception as exc:
                log.warning("could not list models to price: %s", exc)
        if unresolved:
            log.info("no models.dev price for: %s", unresolved)
        snap = Snapshot(keys, inp, out, cache_read, cache_write, unresolved)
        # A catalog/list failure yields an empty snapshot; retry soon instead of caching it for 10 min.
        ttl_credit = 0 if cat is not None and keys else PAIRS_TTL_S - 30
        _snapshot = (time.monotonic() - ttl_credit, snap)
        return snap


def query_params() -> dict[str, Any]:
    """ClickHouse query parameters consumed by span_queries.SPEND_EXPR (never empty arrays)."""
    snap = get_snapshot()
    # transform() needs non-empty arrays to infer types; this sentinel never matches a real row.
    return {
        "px_keys": ["", *snap.keys],
        "px_in": [0.0, *snap.inp],
        "px_out": [0.0, *snap.out],
        "px_cr": [0.0, *snap.cache_read],
        "px_cw": [0.0, *snap.cache_write],
    }
