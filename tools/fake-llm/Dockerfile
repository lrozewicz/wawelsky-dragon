# Obraz fake-llm (C7 [R-8]) — dwa etapy, oba python:3.13-slim; uv zostaje tylko w builderze.

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY fake_llm ./fake_llm
COPY fixtures ./fixtures
RUN uv sync --frozen --no-dev

FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"]

CMD ["uvicorn", "fake_llm.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
