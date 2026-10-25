# Obraz backendu (kontrakt WP E0-3 C1; docs/architecture/11-infrastruktura.md §4.1).
# Etapy: base (python:3.13-slim + uv + użytkownik wd), builder (zależności prod),
# dev (builder + zależności dev + reload), pruned (builder bez źródeł C/Cython, testów pakietów i __pycache__),
# runtime (czysty — venv z pruned, bez kompilatorów), runtime-ocr (+ tesseract itd.),
# test-ocr (dev + tesseract/wvHtml/catppt + tests — tylko krok binaries w verify-full.sh, poza image-size),
# test (dev + tests: lint, typy i testy jednostkowe — kontrakt wspólnego CI, github.com/lrozewicz/.github).

FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Warsaw \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken

RUN groupadd --gid 10001 wd \
    && useradd --uid 10001 --gid 10001 --create-home wd

WORKDIR /app

FROM base AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Najpierw tylko metadane zależności — cache warstw przy zmianach w app/
COPY pyproject.toml uv.lock .python-version ./
# package = false w pyproject — projekt nie jest instalowany, tylko zależności
RUN uv sync --frozen --no-dev --no-install-project
# Pliki BPE cl100k_base do cache tiktoken — runtime działa bez sieci (K5 §3.6)
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

FROM builder AS dev

RUN uv sync --frozen --no-install-project

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000","--reload"]

# Odchudzenie venv (WP E1-H1 T2): źródła C/Cython, testy pakietów, bytecode — runtime ich nie potrzebuje.
# Jedyny import „from ..tests" w zależnościach (openpyxl/reader/excel.py) jest w try/except ImportError — wheel
# openpyxl nie zawiera katalogu tests, więc usuwanie niczego nie psuje (T2 pkt 2).
FROM builder AS pruned

RUN SP=/opt/venv/lib/python3.13/site-packages \
    && find "$SP" -type f \( -name '*.c' -o -name '*.pyx' -o -name '*.pxd' -o -name '*.h' \) -not -path '*/include/*' -delete \
    && find "$SP" -mindepth 2 -type d \( -name tests -o -name test \) -prune -exec rm -r {} + \
    && find /opt/venv -type d -name __pycache__ -prune -exec rm -r {} +

FROM base AS runtime

COPY --from=pruned /opt/venv /opt/venv
COPY --from=builder /opt/tiktoken /opt/tiktoken

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

# pip z obrazu bazowego nie jest potrzebny w runtime (zależności są w /opt/venv), a niesie własną kopię certifi
# (`pip/_vendor/certifi`), którą skanery zgłaszają jako CRITICAL, gdy obraz bazowy jest starszy niż poprawka.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
    /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

# Katalog danych z właścicielem wd — nowy nazwany wolumen app-data:/data przejmuje właściciela z obrazu (K5 §2.6)
RUN mkdir -p /data && chown wd:wd /data

USER wd
EXPOSE 8000
# Bez HEALTHCHECK — robi to compose (C5)
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000"]

FROM runtime AS runtime-ocr

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng wv catdoc poppler-utils \
    && rm -rf /var/lib/apt/lists/*
USER wd

FROM dev AS test-ocr

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng wv catdoc poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY tests ./tests

# Kontrakt wspólnego CI (etap `test`): to samo co krok backendu w `.claude/verify-fast.sh`, ale tylko to, co działa
# bez MariaDB, bramki LLM i repo poza kontekstem budowy (`backend/`). Testy narzędzi repozytorium (`tools/`,
# compose, `.env.example`, fixture frontu) potrzebują całego repo i nie biegną tutaj. Błąd kroku = czerwony PR.
FROM dev AS test

COPY tests ./tests
COPY wdeval ./wdeval
COPY openapi.json ./
RUN ruff check . \
    && ruff format --check . \
    && mypy app \
    && lint-imports \
    && pytest -q -n 4 -p no:cacheprovider \
        --ignore=tests/unit/tools --ignore=tests/unit/test_security_audit.py \
        --ignore=tests/unit/test_check_compose.py --ignore=tests/unit/test_compose_clean_install.py \
        --ignore=tests/unit/core/test_env_example.py --ignore=tests/unit/core/test_version.py \
        --ignore=tests/unit/parsing/test_ocr_fixture.py --ignore=tests/unit/test_sql_noqa_h15.py \
        --ignore=tests/integration/web_search/test_searxng_fake_searx.py \
        -m "not db and not contract and not fakellm and not live and not corpus and not keycloak and not e2e and not binaries"
