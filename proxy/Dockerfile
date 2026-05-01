FROM ghcr.io/astral-sh/uv:0.10.9 AS uv
FROM ghcr.io/berriai/litellm:main-stable

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
COPY requirements.txt .
RUN uv pip install --python /app/.venv/bin/python --no-cache -r requirements.txt

COPY clickhouse_logger.py /app/clickhouse_logger.py
COPY auth.py /app/auth.py
COPY config.yaml /app/config.yaml

ENV PYTHONPATH=/app
EXPOSE 4000

CMD ["--config", "/app/config.yaml", "--port", "4000", "--num_workers", "2"]
