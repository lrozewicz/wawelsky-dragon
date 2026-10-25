"""Testy pomiaru OCR rocznika (`wdperf.gus_ocr`, kontrakt C8 / C4 WP E5-H8e).

Część czysta (``line_seconds``, ``parse_stages``, ``parse_mem_usage``, ``format_table``,
``validate_embedding_model``) bez sieci; część sieciowa na atrapie ``httpx.MockTransport``
(ponowne logowanie przy 401, profilaktyczne odświeżenie, próbkowanie RSS do końca biegu,
``first_ocr_request`` ze statystyk fake-llm).
"""

import time

import httpx
import pytest
from wdperf import gus_ocr

# Przykładowy log z komunikatami z kontraktu C1 WP E5-H8a (znaczniki HH:MM:SS jak w progress_msg).
SAMPLE_LOG = "\n".join(
    [
        "10:00:00 Converting pages 25/120",
        "10:00:05 Converting pages 120/120",
        "10:00:06 Converted 120 pages (120 to recognize)",
        "10:00:08 OCR pages 10/120 (fake-vision)",
        "10:00:15 OCR pages 120/120 (fake-vision)",
        "10:00:16 OCR finished: 120 pages (fake-vision)",
        "10:00:18 Embedding chunks (64/180)",
        "10:00:20 Embedding chunks (128/180)",
        "10:00:22 Embedding chunks (180/180)",
        "10:00:23 Indexing done (5.01s). Done.",
    ]
)


# ---------------------------------------------------------------------------
# Parsowanie logu (część czysta)
# ---------------------------------------------------------------------------


def test_line_seconds_parses_leading_timestamp() -> None:
    assert gus_ocr.line_seconds("10:00:06 Converted 120 pages") == 36006


def test_line_seconds_without_timestamp_is_none() -> None:
    assert gus_ocr.line_seconds("Converted 120 pages") is None


def test_parse_stages_all_present() -> None:
    stages = gus_ocr.parse_stages(SAMPLE_LOG)
    assert stages == {
        "render": 6.0,
        "first_ocr_request": 8.0,
        "ocr": 10.0,
        "embedding": 4.0,
        "total": 23.0,
    }


def test_parse_stages_first_ocr_request_before_converted() -> None:
    """Potok równoległy: pierwsza linia ``OCR pages`` bywa PRZED ``Converted`` (kontrakt C4)."""
    log = "\n".join(
        [
            "10:00:00 OCR concurrency: 3 (fake-ocr)",
            "10:00:05 OCR pages 10/120 (fake-ocr)",
            "10:00:06 Converted 120 pages (120 to recognize)",
            "10:00:15 OCR pages 120/120 (fake-ocr)",
            "10:00:16 OCR finished: 120 pages (fake-ocr)",
        ]
    )
    stages = gus_ocr.parse_stages(log)
    # first_ocr_request od pierwszej linii `OCR pages` (przed `Converted`), nie od renderu.
    assert stages["first_ocr_request"] == 5.0
    assert stages["render"] == 6.0


def test_parse_stages_falls_back_to_ocr_concurrency() -> None:
    """Bez ``OCR pages`` znacznikiem jest wpis ``OCR concurrency`` (kontrakt C4)."""
    log = "10:00:00 OCR concurrency: 3 (fake-ocr)\n10:00:07 Converted 5 pages (5 to recognize)"
    stages = gus_ocr.parse_stages(log)
    assert stages["first_ocr_request"] == 0.0


def test_parse_stages_without_ocr_and_vision_has_no_first_ocr_request() -> None:
    log = "10:00:00 Converting pages 1/1\n10:00:02 Converted 1 pages (text layer)"
    stages = gus_ocr.parse_stages(log)
    assert stages["first_ocr_request"] is None
    assert stages["ocr"] is None
    assert stages["render"] == 2.0


def test_parse_stages_missing_markers_are_none() -> None:
    stages = gus_ocr.parse_stages("10:00:00 Converting pages 1/1")
    assert stages["render"] is None
    assert stages["embedding"] is None
    assert stages["total"] is None


def test_parse_stages_empty_log_is_all_none() -> None:
    assert gus_ocr.parse_stages("") == dict.fromkeys(gus_ocr.STAGE_ORDER)


def test_parse_stages_midnight_wrap() -> None:
    log = "23:59:58 Converting pages 1/1\n00:00:03 Converted 1 pages (text layer)"
    assert gus_ocr.parse_stages(log)["render"] == 5.0


def test_parse_mem_usage_mib() -> None:
    assert gus_ocr.parse_mem_usage("744.5MiB / 4GiB") == 744.5 * 1024.0**2


def test_parse_mem_usage_gib() -> None:
    assert gus_ocr.parse_mem_usage("1.5GiB / 16GiB") == 1.5 * 1024.0**3


def test_parse_mem_usage_invalid_is_none() -> None:
    assert gus_ocr.parse_mem_usage("--") is None


def test_format_table_lists_every_stage_and_rss() -> None:
    stages = gus_ocr.parse_stages(SAMPLE_LOG)
    table = gus_ocr.format_table(stages, 744.0)
    for name in gus_ocr.STAGE_ORDER:
        assert name in table
    assert "worker_peak_rss_mb" in table
    assert "744" in table


def test_format_table_missing_values_show_na() -> None:
    table = gus_ocr.format_table(dict.fromkeys(gus_ocr.STAGE_ORDER), None)
    assert table.count("n/a") == len(gus_ocr.STAGE_ORDER) + 1


# ---------------------------------------------------------------------------
# Argumenty CLI i walidacja --embedding-model
# ---------------------------------------------------------------------------


def test_build_parser_accepts_documented_flags() -> None:
    args = gus_ocr.build_parser().parse_args(
        ["--base-url", "http://h:1", "--email", "a@b", "--vision-model", "fake-vision"]
    )
    assert args.base_url == "http://h:1"
    assert args.vision_model == "fake-vision"
    assert args.password is None


def test_build_parser_timeout_min_defaults_to_30() -> None:
    """`--timeout-min` domyślnie 30 minut (kontrakt C8)."""
    args = gus_ocr.build_parser().parse_args(["--base-url", "http://h:1", "--email", "a@b"])
    assert args.timeout_min == 30


def test_build_parser_timeout_min_is_overridable() -> None:
    """`--timeout-min N` nadpisuje domyślny limit oczekiwania (kontrakt C8)."""
    args = gus_ocr.build_parser().parse_args(
        ["--base-url", "http://h:1", "--email", "a@b", "--timeout-min", "5"]
    )
    assert args.timeout_min == 5


def test_help_documents_embedding_model_format_and_first_ocr_request() -> None:
    """`--help` opisuje format `<model>@<dostawca>` (z przykładem) i `first_ocr_request`."""
    help_text = gus_ocr.build_parser().format_help()
    assert gus_ocr.EMBEDDING_MODEL_EXAMPLE in help_text
    assert "first_ocr_request" in help_text
    assert "--fake-llm-url" in help_text


def test_validate_embedding_model_accepts_model_at_provider() -> None:
    assert gus_ocr.validate_embedding_model("a/b@c") == "a/b@c"
    assert (
        gus_ocr.validate_embedding_model(gus_ocr.EMBEDDING_MODEL_EXAMPLE)
        == gus_ocr.EMBEDDING_MODEL_EXAMPLE
    )


@pytest.mark.parametrize("value", ["a/b", "@c", "a@", "a@b@c"])
def test_validate_embedding_model_rejects_bad_format(value: str) -> None:
    """Błędny format (`a/b`, `@c`, `a@`, `a@b@c`) → błąd z przykładem (kontrakt C4)."""
    with pytest.raises(gus_ocr.GusOcrError) as error:
        gus_ocr.validate_embedding_model(value)
    assert gus_ocr.EMBEDDING_MODEL_EXAMPLE in str(error.value)


async def test_run_rejects_bad_embedding_model_before_network(tmp_path) -> None:
    args = _args(tmp_path, "--embedding-model", "a@b@c")
    with pytest.raises(gus_ocr.GusOcrError) as error:
        await gus_ocr.run(args)
    assert gus_ocr.EMBEDDING_MODEL_EXAMPLE in str(error.value)


# ---------------------------------------------------------------------------
# Atrapa API (httpx.MockTransport): odświeżanie tokenu, RSS, first_ocr_request
# ---------------------------------------------------------------------------


class _Server:
    """Atrapa API WD + fake-llm: logowanie, dataset, upload, parse, dokumenty i statystyki."""

    def __init__(self) -> None:
        self.logins = 0
        self.docs_runs: list[str] = ["DONE"]
        self.docs_401_left = 0
        self.progress_msg = ""
        self.chat_totals: list[int] = []
        self._last_total = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/login":
            self.logins += 1
            return httpx.Response(
                200, json={"code": 0, "data": {"access_token": f"tok{self.logins}"}}
            )
        if path == "/api/v1/datasets" and request.method == "POST":
            return httpx.Response(200, json={"code": 0, "data": {"id": "ds1"}})
        if path == "/api/v1/datasets/ds1/documents/parse":
            return httpx.Response(200, json={"code": 0})
        if path == "/api/v1/datasets/ds1/documents":
            if request.method == "POST":
                return httpx.Response(200, json={"code": 0, "data": [{"id": "doc1"}]})
            if self.docs_401_left > 0:
                self.docs_401_left -= 1
                return httpx.Response(401, json={"code": 401, "message": "unauthorized"})
            run = self.docs_runs.pop(0) if len(self.docs_runs) > 1 else self.docs_runs[0]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "docs": [
                            {
                                "id": "doc1",
                                "run": run,
                                "chunk_count": 3,
                                "progress_msg": self.progress_msg,
                            }
                        ]
                    },
                },
            )
        if path == "/v1/fake/stats":
            if self.chat_totals:
                self._last_total = self.chat_totals.pop(0)
            return httpx.Response(
                200, json={"chat_completions": {"fake-ocr": self._last_total}}
            )
        raise AssertionError(f"nieoczekiwane żądanie: {request.method} {path}")


def _args(tmp_path, *extra: str):
    """Argumenty CLI z tymczasowym PDF-em i dowolnymi dodatkami."""
    pdf = tmp_path / "corpus.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    return gus_ocr.build_parser().parse_args(
        [
            "--base-url",
            "http://api.test",
            "--email",
            "a@b",
            "--password",
            "pw",
            "--pdf",
            str(pdf),
            *extra,
        ]
    )


async def test_wait_done_relogins_on_401_and_continues() -> None:
    """401 na polling → ponowne logowanie i kontynuacja (kontrakt C4)."""
    server = _Server()
    server.docs_401_left = 1
    server.docs_runs = ["DONE"]
    async with httpx.AsyncClient(
        base_url="http://api.test", transport=server.transport()
    ) as client:
        session = gus_ocr._Session(client, "a@b", "pw")
        await session.login()
        doc = await gus_ocr._wait_done(session, "ds1", time.perf_counter() + 30.0, 30)
    assert server.logins == 2  # logowanie startowe + ponowne po 401
    assert doc["run"] == "DONE"


async def test_session_relogins_proactively_after_interval() -> None:
    """Po ``TOKEN_REFRESH_S`` sesja loguje się profilaktycznie (bieg > 15 min, kontrakt C4)."""
    server = _Server()
    server.docs_runs = ["DONE"]
    clock = [0.0]
    async with httpx.AsyncClient(
        base_url="http://api.test", transport=server.transport()
    ) as client:
        session = gus_ocr._Session(client, "a@b", "pw", now=lambda: clock[0])
        await session.login()
        clock[0] = gus_ocr.TOKEN_REFRESH_S + 1.0
        await session.get("/api/v1/datasets/ds1/documents")
    assert server.logins == 2


async def test_run_samples_rss_until_run_end(monkeypatch, tmp_path) -> None:
    """RSS próbkowany do końca biegu; szczyt (rosnące próbki) w wyniku (kontrakt C4)."""
    samples: list[float] = []

    def fake_mem_usage(container: str) -> str:
        samples.append(float(len(samples) + 1))
        return f"{len(samples) * 100}MiB / 8GiB"

    monkeypatch.setattr(gus_ocr, "_mem_usage", fake_mem_usage)
    monkeypatch.setattr(gus_ocr, "POLL_INTERVAL_S", 0.02)
    monkeypatch.setattr(gus_ocr, "STATS_INTERVAL_S", 0.005)
    server = _Server()
    server.docs_runs = ["RUNNING", "RUNNING", "DONE"]
    server.progress_msg = (
        "10:00:00 Converting pages 1/3\n"
        "10:00:05 OCR pages 1/3 (fake-ocr)\n"
        "10:00:09 Indexing done (0.01s). Done."
    )
    result = await gus_ocr.run(
        _args(tmp_path, "--worker-container", "w"), transport=server.transport()
    )
    # Próbkowanie trwa przez cały bieg (wiele próbek, nie jedna na dokument), szczyt = ostatnia.
    assert len(samples) >= 3
    assert samples[-1] == max(samples)
    assert result["worker_peak_rss_mb"] == round(max(samples) * 100 * 1024**2 / 1_000_000, 1)
    # Bez --fake-llm-url źródłem first_ocr_request jest log zadania.
    assert result["first_ocr_request_source"] == "log"
    assert result["stages_s"]["first_ocr_request"] == 5.0


async def test_run_takes_first_ocr_request_from_fake_llm_stats(monkeypatch, tmp_path) -> None:
    """Z ``--fake-llm-url`` pierwszy wzrost licznika czatu wyznacza ``first_ocr_request``."""
    monkeypatch.setattr(gus_ocr, "POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(gus_ocr, "FAKE_STATS_INTERVAL_S", 0.005)
    server = _Server()
    server.docs_runs = ["RUNNING", "RUNNING", "RUNNING", "DONE"]
    # Baseline 0, pierwszy poll 0 (bez wzrostu), drugi poll 4 → pierwszy wzrost.
    server.chat_totals = [0, 0, 4]
    result = await gus_ocr.run(
        _args(tmp_path, "--fake-llm-url", "http://fake.test"), transport=server.transport()
    )
    assert result["first_ocr_request_source"] == "fake-llm-stats"
    assert result["stages_s"]["first_ocr_request"] is not None
