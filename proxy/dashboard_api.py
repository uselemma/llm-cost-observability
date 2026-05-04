"""Dashboard API mounted onto the LiteLLM FastAPI app.

Routes:
    POST /api/login                       — exchange any LITELLM_KEYS secret for a signed cookie
    POST /api/logout                      — clear cookie
    GET  /api/calls?...                   — list recent rows from litellm_logs
    GET  /api/calls/{request_id}          — single row, including bodies

Static:
    GET  /                               — SPA index.html, replacing LiteLLM's default UI
    GET  /assets/*                       — built SPA assets
    GET  /ui/*                           — compatibility route for LiteLLM UI links
    GET  /dashboard/*                    — compatibility route for old dashboard links

Auth: any secret from LITELLM_KEYS works as a login. The matched env (dev/prod)
is stamped into the session token so /api/calls auto-scopes to that env —
a dev key can't see prod traffic. Cookies are signed with a key derived from
LITELLM_KEYS itself, so rotating keys invalidates all sessions.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import BaseRoute
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel
from proxy.cel_filter import compile_cel_filter, list_queryable_cel_fields

try:
    from litellm.proxy.proxy_server import app as proxy_app
except Exception:  # pragma: no cover
    proxy_app = None

COOKIE_NAME = "dashboard_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days
DASHBOARD_DIST = os.environ.get("DASHBOARD_DIST", "/app/dashboard_dist")


def _parse_keys(raw: str) -> dict[str, str]:
    """Same shape as proxy/auth.py — secret -> env."""
    out: dict[str, str] = {}
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        sk, _, env = entry.partition(":")
        if sk and env:
            out[sk] = env
    return out


_KEYS = _parse_keys(os.environ["LITELLM_KEYS"])
_signer = URLSafeTimedSerializer(
    hashlib.sha256(os.environ["LITELLM_KEYS"].encode()).hexdigest(),
    salt="llm-cost-observability-dashboard",
)


def _ch_client():
    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
    )


def _require_session(
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        return _signer.loads(session, max_age=SESSION_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="invalid or expired session")


router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    secret: str


@router.post("/login", status_code=204)
async def login(payload: LoginRequest, response: Response) -> None:
    matched_env: str | None = None
    for sk, env in _KEYS.items():
        if hmac.compare_digest(payload.secret, sk):
            matched_env = env
            break
    if matched_env is None:
        raise HTTPException(status_code=401, detail="invalid secret")
    token = _signer.dumps({"iat": int(time.time()), "env": matched_env})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=os.environ.get("DASHBOARD_COOKIE_SECURE", "true").lower() == "true",
        samesite="lax",
        path="/",
    )


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.get("/me")
async def me(session: dict[str, Any] = Depends(_require_session)) -> dict[str, Any]:
    return {"authenticated": True, "env": session.get("env")}


# --- Calls list & detail -----------------------------------------------------

LIST_COLUMNS = [
    "request_id",
    "timestamp",
    "model",
    "provider",
    "team",
    "status",
    "finish_reason",
    "spend_usd",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "ttft_ms",
    "tags",
    "substring(output_text, 1, 240) AS output_preview",
]


def _parse_query_datetime(value: str, field: str) -> str:
    """Parse incoming datetime query params into ClickHouse-safe timestamps.

    Accepts minute-level strings like `YYYY-MM-DDTHH:mm` from the dashboard
    picker, plus full ISO datetimes.
    """
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"invalid {field} datetime, expected ISO format",
        )
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


@router.get("/calls")
async def list_calls(
    request: Request,
    session: dict[str, Any] = Depends(_require_session),
    since: str | None = None,
    until: str | None = None,
    model: str | None = None,
    status: str | None = None,
    tag: list[str] = Query(default_factory=list),
    cel: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    where: list[str] = ["team = {env:String}"]
    params: dict[str, Any] = {"env": session["env"]}

    if since:
        where.append("timestamp >= {since:DateTime64(3)}")
        params["since"] = _parse_query_datetime(since, "since")
    else:
        where.append("timestamp >= now() - INTERVAL 24 HOUR")

    if until:
        where.append("timestamp <= {until:DateTime64(3)}")
        params["until"] = _parse_query_datetime(until, "until")
    if model:
        where.append("model = {model:String}")
        params["model"] = model
    if status:
        where.append("status = {status:String}")
        params["status"] = status
    if tag:
        # Group selected tags by their key (prefix before first ':').
        # OR within a key, AND across keys.
        groups: dict[str, list[str]] = defaultdict(list)
        for t in tag:
            key, _, _ = t.partition(":")
            groups[key].append(t)
        for i, vals in enumerate(groups.values()):
            ors: list[str] = []
            for j, v in enumerate(vals):
                pname = f"tag_{i}_{j}"
                ors.append(f"has(tags, {{{pname}:String}})")
                params[pname] = v
            where.append("(" + " OR ".join(ors) + ")")
    if cel and cel.strip():
        try:
            cel_sql, cel_params = compile_cel_filter(cel.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid cel filter: {exc}")
        where.append(f"({cel_sql})")
        params.update(cel_params)
    if q:
        where.append("(positionCaseInsensitive(output_text, {q:String}) > 0 OR positionCaseInsensitive(input_messages, {q:String}) > 0)")
        params["q"] = q

    where_sql = " AND ".join(where) if where else "1=1"

    sql = f"""
        SELECT {", ".join(LIST_COLUMNS)}
        FROM litellm_logs
        WHERE {where_sql}
        ORDER BY timestamp DESC
        LIMIT {limit} OFFSET {offset}
    """

    client = _ch_client()
    result = client.query(sql, parameters=params)
    rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
    for r in rows:
        r["timestamp"] = (
            r["timestamp"].replace(tzinfo=timezone.utc).isoformat()
            if r.get("timestamp") is not None
            else None
        )
    return {"rows": rows, "limit": limit, "offset": offset}


@router.get("/calls/{request_id}")
async def get_call(
    request_id: str,
    session: dict[str, Any] = Depends(_require_session),
) -> dict[str, Any]:
    client = _ch_client()
    result = client.query(
        "SELECT * FROM litellm_logs WHERE request_id = {rid:String} AND team = {env:String} ORDER BY timestamp DESC LIMIT 1",
        parameters={"rid": request_id, "env": session["env"]},
    )
    if not result.result_rows:
        raise HTTPException(status_code=404, detail="not found")
    row = dict(zip(result.column_names, result.result_rows[0]))
    row["timestamp"] = (
        row["timestamp"].replace(tzinfo=timezone.utc).isoformat()
        if row.get("timestamp") is not None
        else None
    )
    return row


@router.get("/tags")
async def list_tags(session: dict[str, Any] = Depends(_require_session)) -> dict[str, Any]:
    client = _ch_client()
    result = client.query(
        """
        SELECT DISTINCT t
        FROM litellm_logs
        ARRAY JOIN tags AS t
        WHERE timestamp >= now() - INTERVAL 7 DAY
          AND team = {env:String}
          AND NOT startsWith(t, 'env:')
        ORDER BY t
        """,
        parameters={"env": session["env"]},
    )
    return {"tags": [r[0] for r in result.result_rows]}


@router.get("/models")
async def list_models(session: dict[str, Any] = Depends(_require_session)) -> dict[str, Any]:
    client = _ch_client()
    result = client.query(
        "SELECT model, count() AS n FROM litellm_logs WHERE timestamp >= now() - INTERVAL 7 DAY AND team = {env:String} GROUP BY model ORDER BY n DESC",
        parameters={"env": session["env"]},
    )
    return {"models": [r[0] for r in result.result_rows]}


@router.get("/cel-fields")
async def list_cel_fields(
    _session: dict[str, Any] = Depends(_require_session),
) -> dict[str, Any]:
    return {"fields": list_queryable_cel_fields()}


# --- Mount on the LiteLLM app -----------------------------------------------

def _remove_litellm_default_ui_routes(routes: list[BaseRoute]) -> None:
    """Let the custom dashboard own root while leaving API routes untouched."""
    routes[:] = [
        route
        for route in routes
        if not _is_litellm_default_ui_route(route)
    ]


def _is_litellm_default_ui_route(route: BaseRoute) -> bool:
    path = getattr(route, "path", None)
    if path is None:
        return False
    methods = getattr(route, "methods", set()) or set()
    if path == "/" and (methods & {"GET", "HEAD"}):
        return True
    return path == "/ui" or path.startswith("/ui/")


if proxy_app is not None:
    proxy_app.include_router(router)

    if os.path.isdir(DASHBOARD_DIST):
        _remove_litellm_default_ui_routes(proxy_app.router.routes)

        # Serve assets at /assets/* for the root-mounted SPA.
        proxy_app.mount(
            "/assets",
            StaticFiles(directory=os.path.join(DASHBOARD_DIST, "assets")),
            name="dashboard_assets_root",
        )

        # Keep old /dashboard links working after the dashboard moved to root.
        @proxy_app.get("/dashboard")
        @proxy_app.get("/dashboard/")
        async def redirect_dashboard() -> RedirectResponse:
            return RedirectResponse(url="/", status_code=307)

        @proxy_app.get("/ui")
        @proxy_app.get("/ui/")
        @proxy_app.get("/ui/{path:path}")
        async def redirect_litellm_ui(path: str = "") -> RedirectResponse:
            return RedirectResponse(url="/", status_code=307)

        @proxy_app.get("/dashboard/{path:path}")
        async def serve_legacy_dashboard(path: str = "") -> FileResponse:
            return FileResponse(os.path.join(DASHBOARD_DIST, "index.html"))

        # Root SPA fallback. This is registered after LiteLLM's API routes, so
        # known OpenAI-compatible endpoints continue to resolve normally.
        @proxy_app.get("/")
        @proxy_app.get("/{path:path}")
        async def serve_dashboard(path: str = "") -> FileResponse:
            return FileResponse(os.path.join(DASHBOARD_DIST, "index.html"))
