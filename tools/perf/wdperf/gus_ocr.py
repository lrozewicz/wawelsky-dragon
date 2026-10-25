"""Pomiar etapów parsowania rocznika przez OCR (kontrakt C8, WP E5-H8b).

Loguje się kontem administratora, tworzy dataset (opcjonalnie z parserem = model wizji),
wgrywa PDF, zleca parsowanie i czeka na koniec (limit ``--timeout-min``, domyślnie 30 min).
Token odświeża przy 401 (ponowne logowanie tymi samymi poświadczeniami) i profilaktycznie co
``TOKEN_REFRESH_S``, więc bieg > 15 min kończy się wynikiem (kontrakt C4 WP E5-H8e).
Z ``progress_msg`` dokumentu
odczytuje znaczniki ``HH:MM:SS`` i liczy czasy etapów: ``render`` (start → ostatnie
``Converted``), ``first_ocr_request`` (start → pierwsze ``OCR pages``, a bez OCR — pierwsze
``OCR concurrency``; przy ``--fake-llm-url`` — start → pierwszy wzrost licznika czatu
fake-llm, pole ``first_ocr_request_source`` mówi, którą metodę zastosowano), ``ocr``
(``Converted`` → ``OCR finished``), ``embedding`` (pierwsze →
ostatnie ``Embedding chunks``) i ``total`` (start → ``Indexing done``). Równolegle próbkuje
``docker stats`` do końca biegu i raportuje szczyt RSS workera. Uruchamiane z ``backend/``:

``cd backend && PYTHONPATH=../tools/perf:. uv run --frozen python -m wdperf.gus_ocr ...``

Część czysta (``line_seconds``, ``parse_stages``, ``parse_mem_usage``, ``format_table``) nie
dotyka sieci i jest testowana bez stosu.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

# Znacznik czasu na początku linii logu zadania (``clock_hms`` w backendzie): ``HH:MM:SS``.
TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\b")
# Znaczniki etapów (kontrakt C1 WP E5-H8a).
CONVERTED_RE = re.compile(r"Converted \d+ pages")
OCR_PAGES_RE = re.compile(r"OCR pages")
# Zapasowy znacznik OCR, gdy brak ``OCR pages``: wpis ``OCR concurrency`` przed konwersją.
OCR_CONCURRENCY_RE = re.compile(r"OCR concurrency")
OCR_FINISHED_RE = re.compile(r"OCR finished")
EMBEDDING_RE = re.compile(r"Embedding chunks")
INDEXING_DONE_RE = re.compile(r"Indexing done")
# Jednostki ``docker stats`` dla pamięci.
MEM_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)")

# Limit oczekiwania na parsowanie (C8: domyślnie 30 min, nadpisywalny flagą `--timeout-min`).
DEFAULT_TIMEOUT_MIN = 30
# Odstęp między odpytaniami listy dokumentów.
POLL_INTERVAL_S = 2.0
# Odstęp próbkowania ``docker stats``.
STATS_INTERVAL_S = 5.0
# Profilaktyczne odświeżenie tokenu co 10 min (kontrakt C4) — bieg GUS trwa > 15 min.
TOKEN_REFRESH_S = 600.0
# Odstęp odpytania ``GET /v1/fake/stats`` przy pomiarze ``first_ocr_request`` (kontrakt C4).
FAKE_STATS_INTERVAL_S = 1.0
# Przykład formatu ``--embedding-model`` w ``--help`` i w komunikacie błędu walidacji (kontrakt C4).
EMBEDDING_MODEL_EXAMPLE = "openai/text-embedding-3-large@OpenAI-API-Compatible"
# Domyślna nazwa pliku korpusu (C8).
DEFAULT_PDF_NAME = "gus_rocznik_statystyczny_rp_2024.pdf"
# Stany ``run`` dokumentu (present.documents.RUN_NAMES).
PENDING_RUNS = frozenset({"UNSTART", "RUNNING", "SCHEDULE"})
DONE_RUN = "DONE"
FAIL_RUN = "FAIL"
# Jednostki pamięci ``docker stats`` → bajty (1 MB = 1 000 000 B).
_MEM_FACTORS = {
    "b": 1.0,
    "kib": 1024.0,
    "mib": 1024.0**2,
    "gib": 1024.0**3,
    "kb": 1000.0,
    "mb": 1000.0**2,
    "gb": 1000.0**3,
}

# Kolumny czytelnej tabeli wyników.
STAGE_ORDER: tuple[str, ...] = (
    "render",
    "first_ocr_request",
    "ocr",
    "embedding",
    "total",
)


class GusOcrError(RuntimeError):
    """Pomiar nie zakończył się poprawnie (HTTP, koperta API, błąd dokumentu albo limit czasu)."""


def line_seconds(line: str) -> int | None:
    """Sekundy dnia ze znacznika ``HH:MM:SS`` na początku linii; brak → ``None``."""
    match = TIME_RE.match(line)
    if match is None:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))


def _times(log: str, pattern: re.Pattern[str]) -> list[int]:
    """Sekundy wszystkich linii logu pasujących do `pattern` (w kolejności wystąpienia)."""
    hits: list[int] = []
    for line in log.split("\n"):
        if pattern.search(line) is not None:
            seconds = line_seconds(line)
            if seconds is not None:
                hits.append(seconds)
    return hits


def _span(start: int | None, end: int | None) -> float | None:
    """Różnica sekund między dwoma znacznikami; zawinięcie przez północ koryguje +24 h."""
    if start is None or end is None:
        return None
    return float(end - start if end >= start else end + 86_400 - start)


def parse_stages(log: str) -> dict[str, float | None]:
    """Czasy etapów parsowania (sekundy) z ``progress_msg``; brakujące znaczniki → ``None``.

    ``first_ocr_request`` to pierwsza linia ``OCR pages`` (pierwsze żądanie do modelu wizji w
    potoku równoległym bywa przed ``Converted``), a gdy jej brak — pierwszy wpis ``OCR concurrency``
    (kontrakt C4 WP E5-H8e).
    """
    timestamps = [
        seconds for line in log.split("\n") if (seconds := line_seconds(line)) is not None
    ]
    start = timestamps[0] if timestamps else None

    converted = _times(log, CONVERTED_RE)
    ocr_pages = _times(log, OCR_PAGES_RE)
    ocr = ocr_pages if ocr_pages else _times(log, OCR_CONCURRENCY_RE)
    ocr_finished = _times(log, OCR_FINISHED_RE)
    embedding = _times(log, EMBEDDING_RE)
    indexing = _times(log, INDEXING_DONE_RE)

    return {
        "render": _span(start, converted[-1] if converted else None),
        "first_ocr_request": _span(start, ocr[0] if ocr else None),
        "ocr": _span(
            converted[-1] if converted else None, ocr_finished[-1] if ocr_finished else None
        ),
        "embedding": _span(
            embedding[0] if embedding else None, embedding[-1] if embedding else None
        ),
        "total": _span(start, indexing[-1] if indexing else None),
    }


def parse_mem_usage(text: str) -> float | None:
    """Bajty zużycia pamięci z ``docker stats`` (``"744MiB / 4GiB"``); brak → ``None``."""
    first = text.split("/", 1)[0].strip()
    match = MEM_RE.fullmatch(first)
    if match is None:
        return None
    factor = _MEM_FACTORS.get(match.group(2).lower())
    if factor is None:
        return None
    return float(match.group(1)) * factor


def _fmt(seconds: float | None) -> str:
    """Sekundy z jednym miejscem po przecinku; brak → ``n/a``."""
    return "n/a" if seconds is None else f"{seconds:.1f}"


def _fmt_rss(mb: float | None) -> str:
    """RSS w MB bez miejsc po przecinku; brak → ``n/a``."""
    return "n/a" if mb is None else f"{mb:.0f}"


def format_table(stages: dict[str, float | None], peak_rss_mb: float | None) -> str:
    """Czytelna tabela etapów (sekundy) + wiersz ``worker_peak_rss_mb``."""
    lines = ["stage                 seconds"]
    lines.extend(f"{name:<21} {_fmt(stages.get(name)):>7}" for name in STAGE_ORDER)
    lines.append(f"{'worker_peak_rss_mb':<21} {_fmt_rss(peak_rss_mb):>7}")
    return "\n".join(lines)


def _mem_usage(container: str) -> str | None:
    """Pierwszy token ``MemUsage`` z ``docker stats``; brak kontenera/błędu → ``None``."""
    result = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0]


async def _peak_rss_mb(container: str | None, stop: asyncio.Event) -> float | None:
    """Próbkuje RSS workera co ``STATS_INTERVAL_S`` do ``stop``; kontener nieznany → ``None``."""
    if container is None:
        return None
    peak = 0.0
    seen = False
    while not stop.is_set():
        usage = await asyncio.to_thread(_mem_usage, container)
        if usage is not None:
            current = parse_mem_usage(usage)
            if current is not None:
                peak = max(peak, current)
                seen = True
        try:
            await asyncio.wait_for(stop.wait(), timeout=STATS_INTERVAL_S)
        except TimeoutError:
            continue
    return peak / 1_000_000 if seen else None


def _payload(response: httpx.Response) -> dict[str, Any]:
    """Koperta RAGFlow: HTTP 200 + ``code == 0``, inaczej ``GusOcrError``."""
    if response.status_code != 200:
        raise GusOcrError(f"HTTP {response.status_code}: {response.text[:200]}")
    body = response.json()
    if body.get("code") != 0:
        raise GusOcrError(f"code {body.get('code')}: {body.get('message')}")
    return body


class _HelpFormatter(argparse.HelpFormatter):
    """``--help`` o szerokości co najmniej 100 kolumn i bez łamania wyrazów na myślnikach.

    Bez tego argparse dzieli przykład ``--embedding-model`` (``openai/text-`` /
    ``embedding-3-large@…``), więc ``--help`` nie pokazuje go dosłownie.
    """

    def __init__(self, prog: str) -> None:
        super().__init__(prog, width=max(shutil.get_terminal_size().columns, 100))

    def _split_lines(self, text: str, width: int) -> list[str]:
        return textwrap.wrap(text, width, break_on_hyphens=False) or [""]


def build_parser() -> argparse.ArgumentParser:
    """CLI pomiaru OCR rocznika (``python -m wdperf.gus_ocr ...``)."""
    parser = argparse.ArgumentParser(
        prog="wdperf.gus_ocr",
        formatter_class=_HelpFormatter,
        description=(
            "Pomiar etapów OCR rocznika. first_ocr_request to czas od startu do pierwszego "
            "żądania do modelu wizji: z faktycznych żądań fake-llm (--fake-llm-url, "
            "GET /v1/fake/stats), a bez niego z logu zadania (pierwsza linia OCR pages, "
            "a gdy jej brak — OCR concurrency); źródło w polu first_ocr_request_source."
        ),
    )
    parser.add_argument("--base-url", required=True, help="bazowy URL API WD, np. http://host:port")
    parser.add_argument("--email", required=True, help="e-mail administratora")
    parser.add_argument(
        "--password",
        default=None,
        help="hasło administratora (domyślnie ze zmiennej WD_PERF_PASSWORD)",
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help="ścieżka PDF (domyślnie $WD_REAL_CORPUS/" + DEFAULT_PDF_NAME + ")",
    )
    parser.add_argument("--vision-model", default=None, help="nazwa modelu wizji (parser PDF)")
    parser.add_argument(
        "--embedding-model",
        default=None,
        help=(
            "model embeddingu datasetu w formacie <model>@<dostawca>, "
            f"np. {EMBEDDING_MODEL_EXAMPLE}"
        ),
    )
    parser.add_argument(
        "--fake-llm-url",
        default=None,
        help=(
            "bazowy URL fake-llm: mierzy first_ocr_request z GET /v1/fake/stats (pierwszy wzrost "
            "licznika żądań czatu); bez niego first_ocr_request liczy się z logu zadania"
        ),
    )
    parser.add_argument(
        "--worker-container", default=None, help="kontener workera do `docker stats`"
    )
    parser.add_argument(
        "--timeout-min",
        type=int,
        default=DEFAULT_TIMEOUT_MIN,
        help=f"limit oczekiwania na parsowanie w minutach (domyślnie {DEFAULT_TIMEOUT_MIN})",
    )
    return parser


def _resolve_password(args: argparse.Namespace) -> str:
    """Hasło z ``--password`` albo ``WD_PERF_PASSWORD``; brak → ``GusOcrError``."""
    password = args.password or os.environ.get("WD_PERF_PASSWORD")
    if not password:
        raise GusOcrError("brak hasła: podaj --password albo ustaw WD_PERF_PASSWORD")
    return password


def validate_embedding_model(value: str) -> str:
    """``<model>@<dostawca>``: dokładnie jedno ``@``, oba człony niepuste (kontrakt C4).

    Błędny format → ``GusOcrError`` z przykładem ``EMBEDDING_MODEL_EXAMPLE``.
    """
    model, sep, provider = value.partition("@")
    if not sep or not model or not provider or "@" in provider:
        raise GusOcrError(
            "--embedding-model: oczekiwano formatu <model>@<dostawca>, "
            f"np. {EMBEDDING_MODEL_EXAMPLE}"
        )
    return value


def _resolve_pdf(args: argparse.Namespace) -> str:
    """Ścieżka PDF z ``--pdf`` albo ``$WD_REAL_CORPUS/<domyślna nazwa>``; brak → ``GusOcrError``."""
    if args.pdf:
        return args.pdf
    corpus = os.environ.get("WD_REAL_CORPUS")
    if not corpus:
        raise GusOcrError("brak --pdf i nieustawione WD_REAL_CORPUS")
    return os.path.join(corpus, DEFAULT_PDF_NAME)


def _resolve_container(args: argparse.Namespace) -> str | None:
    """Kontener workera: ``--worker-container``/``WD_PERF_WORKER_CONTAINER``/kompozycja."""
    if args.worker_container:
        return args.worker_container
    env = os.environ.get("WD_PERF_WORKER_CONTAINER")
    if env:
        return env
    project = os.environ.get("COMPOSE_PROJECT_NAME")
    return f"{project}-worker-1" if project else None


class _Session:
    """Sesja API z tokenem: ponowne logowanie przy 401 i profilaktyczne co ``TOKEN_REFRESH_S``.

    ``now`` to szew testowy zegara (domyślnie ``time.monotonic``); przy 401 loguje się raz tymi
    samymi poświadczeniami i powtarza żądanie (kontrakt C4).
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        email: str,
        password: str,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._email = email
        self._password = password
        self._now = now
        self._headers: dict[str, str] = {}
        self._token_at = 0.0

    async def login(self) -> None:
        """Loguje się tymi samymi poświadczeniami i zapamiętuje token dostępu."""
        login = _payload(
            await self._client.post(
                "/api/v1/auth/login",
                json={"email": self._email, "password": self._password},
            )
        )
        self._headers = {"Authorization": f"Bearer {login['data']['access_token']}"}
        self._token_at = self._now()

    async def _refresh_if_stale(self) -> None:
        """Profilaktyczne odświeżenie, gdy token ma już ``TOKEN_REFRESH_S`` (kontrakt C4)."""
        if self._headers and self._now() - self._token_at >= TOKEN_REFRESH_S:
            await self.login()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Żądanie z tokenem; ``401`` → ponowne logowanie i jedna powtórka (kontrakt C4)."""
        await self._refresh_if_stale()
        response = await self._client.request(method, url, headers=self._headers, **kwargs)
        if response.status_code == 401:
            await self.login()
            response = await self._client.request(method, url, headers=self._headers, **kwargs)
        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """``GET`` przez ``request`` (z odświeżaniem tokenu)."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """``POST`` przez ``request`` (z odświeżaniem tokenu)."""
        return await self.request("POST", url, **kwargs)


async def _fake_chat_total(client: httpx.AsyncClient, fake_llm_url: str) -> int | None:
    """Suma licznika żądań czatu z ``GET /v1/fake/stats``; brak/błąd → ``None`` (kontrakt C4)."""
    url = f"{fake_llm_url.rstrip('/')}/v1/fake/stats"
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    counters = response.json().get("chat_completions")
    if not isinstance(counters, dict):
        return None
    return sum(int(value) for value in counters.values())


async def _first_ocr_request_s(
    client: httpx.AsyncClient,
    fake_llm_url: str,
    baseline: int,
    started: float,
    stop: asyncio.Event,
) -> float | None:
    """Czas (s) do pierwszego wzrostu licznika czatu fake-llm od ``started`` (kontrakt C4)."""
    while not stop.is_set():
        total = await _fake_chat_total(client, fake_llm_url)
        if total is not None and total > baseline:
            return time.monotonic() - started
        try:
            await asyncio.wait_for(stop.wait(), timeout=FAKE_STATS_INTERVAL_S)
        except TimeoutError:
            continue
    return None


async def _wait_done(
    session: _Session,
    dataset_id: str,
    deadline: float,
    timeout_min: int,
) -> dict[str, Any]:
    """Czeka na zakończenie zadania dokumentu (``DONE``/``FAIL``); limit czasu → ``GusOcrError``."""
    while True:
        body = _payload(await session.get(f"/api/v1/datasets/{dataset_id}/documents"))
        docs = body["data"]["docs"]
        if docs and all(doc["run"] not in PENDING_RUNS for doc in docs):
            return docs[0]
        if time.perf_counter() >= deadline:
            raise GusOcrError(f"przekroczono limit {timeout_min} min oczekiwania na parsowanie")
        await asyncio.sleep(POLL_INTERVAL_S)


async def run(
    args: argparse.Namespace,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Logowanie, dataset, upload, parsowanie, próbkowanie RSS i wynik pomiaru (C8).

    ``transport`` to szew testowy (``httpx.MockTransport``) — produkcyjnie ``None``.
    """
    password = _resolve_password(args)
    pdf = _resolve_pdf(args)
    container = _resolve_container(args)
    embedding_model = (
        validate_embedding_model(args.embedding_model) if args.embedding_model else None
    )
    timeout = httpx.Timeout(120.0)

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), timeout=timeout, transport=transport
    ) as client:
        session = _Session(client, args.email, password)
        await session.login()

        dataset_body: dict[str, Any] = {"name": f"perf-gus-ocr-{int(time.time())}"}
        if embedding_model:
            dataset_body["embedding_model"] = embedding_model
        if args.vision_model:
            dataset_body["parser_config"] = {"layout_recognize": args.vision_model}
        dataset = _payload(await session.post("/api/v1/datasets", json=dataset_body))["data"]
        dataset_id = str(dataset["id"])

        pdf_bytes = await asyncio.to_thread(Path(pdf).read_bytes)
        uploaded = _payload(
            await session.post(
                f"/api/v1/datasets/{dataset_id}/documents",
                files={"file": (os.path.basename(pdf), pdf_bytes, "application/pdf")},
            )
        )["data"]
        document_id = str(uploaded[0]["id"])

        stop = asyncio.Event()
        sampler = asyncio.create_task(_peak_rss_mb(container, stop))
        stats_task: asyncio.Task[float | None] | None = None
        deadline = time.perf_counter() + args.timeout_min * 60.0
        try:
            if args.fake_llm_url:
                baseline = await _fake_chat_total(client, args.fake_llm_url)
                if baseline is not None:
                    started = time.monotonic()
                    stats_task = asyncio.create_task(
                        _first_ocr_request_s(
                            client, args.fake_llm_url, baseline, started, stop
                        )
                    )
            parse = await session.post(
                f"/api/v1/datasets/{dataset_id}/documents/parse",
                json={"document_ids": [document_id]},
            )
            if parse.status_code != 200:
                raise GusOcrError(f"parse: HTTP {parse.status_code}: {parse.text[:200]}")
            doc = await _wait_done(session, dataset_id, deadline, args.timeout_min)
        finally:
            stop.set()
            peak_rss_mb = await sampler
            measured_first_ocr = await stats_task if stats_task is not None else None

    stages = parse_stages(str(doc.get("progress_msg", "")))
    first_ocr_source = "log"
    if measured_first_ocr is not None:
        stages["first_ocr_request"] = measured_first_ocr
        first_ocr_source = "fake-llm-stats"
    failed = doc.get("run") != DONE_RUN
    result: dict[str, Any] = {
        "tool": "wdperf",
        "version": 1,
        "scenario": "q34-gus-ocr",
        "pdf": os.path.basename(pdf),
        "vision_model": args.vision_model,
        "embedding_model": embedding_model,
        "run": doc.get("run"),
        "chunks": int(doc.get("chunk_count", 0)),
        "stages_s": stages,
        "first_ocr_request_source": first_ocr_source,
        "worker_peak_rss_mb": None if peak_rss_mb is None else round(peak_rss_mb, 1),
        "failed": failed,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; rc 1 gdy pomiar zgłosi błąd albo dokument nie skończył ``DONE``."""
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except (GusOcrError, httpx.HTTPError, OSError) as error:
        print(f"gus_ocr: {error}", file=sys.stderr)
        return 1
    print(format_table(result["stages_s"], result["worker_peak_rss_mb"]))
    print(
        json.dumps(
            {**result, "run": result["run"]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
