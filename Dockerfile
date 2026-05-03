FROM node:20-alpine AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci || npm install
COPY dashboard/ .
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM ghcr.io/berriai/litellm:main-stable
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
COPY proxy/requirements.txt .
RUN uv pip install --python /app/.venv/bin/python --no-cache -r requirements.txt

COPY proxy/clickhouse_logger.py /app/clickhouse_logger.py
COPY proxy/auth.py              /app/auth.py
COPY proxy/dashboard_api.py     /app/dashboard_api.py
COPY proxy/config.yaml          /app/config.yaml
COPY --from=dashboard /dashboard/dist /app/dashboard_dist

ENV PYTHONPATH=/app DASHBOARD_DIST=/app/dashboard_dist
EXPOSE 4000

ENTRYPOINT []
CMD ["sh", "-c", "litellm --config /app/config.yaml --port 4000 --num_workers $(nproc)"]
