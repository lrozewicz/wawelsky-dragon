"""Fixture stosu MCP (K17 §1, SC-E6-2-01): API WD + serwer MCP jako podprocesy.

Wzór uruchamiania API na bazie testowej: ``tests/contract/ragflow/harness.py``
(``start_server``: świeża baza ``wd_h_*``, migracja alembic, api+worker, ``/health/ready``).
Serwer MCP startuje jako ``python -m app.mcp`` z ``WD_MCP_PORT`` i ``WD_MCP_API_BASE``;
fixture dostarcza dataset użytkownika A z jednym polskim chunkiem (ingestia przez API WD,
embeddings z fake-llm jak w innych testach kontraktowych).

Stałe i ``McpStack`` mieszkają w ``support.py`` — wspólny moduł bez podwójnego importu conftest.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.contract.mcp_wd.support import (
    DATASET_NAME,
    DOCUMENT_NAME,
    DOCUMENT_TEXT,
    LOG_TAIL_LINES,
    MCP_READY_INTERVAL_S,
    MCP_READY_TIMEOUT_S,
    McpStack,
    ingest_dataset,
)
from tests.contract.ragflow.harness import start_server

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _free_port() -> int:
    """Wolny port TCP na 127.0.0.1: bind na 0, odczyt, zamknięcie (jak harness)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _mcp_logs(log_path: Path) -> str:
    """Ostatnie linie logu serwera MCP — do komunikatów błędów."""
    if not log_path.exists():
        return ""
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-LOG_TAIL_LINES:])


def _start_mcp(log_dir: Path, api_base: str) -> tuple[subprocess.Popen[bytes], str]:
    """Startuje ``python -m app.mcp``; czeka na ``GET /healthz``. Zwraca (proces, base_url)."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = log_dir / "mcp.log"
    env = dict(os.environ) | {"WD_MCP_PORT": str(port), "WD_MCP_API_BASE": api_base}
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.mcp"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    deadline = time.monotonic() + MCP_READY_TIMEOUT_S
    while True:
        if proc.poll() is not None:
            logs = _mcp_logs(log_path)
            raise RuntimeError(
                f"proces MCP zakończony przedwcześnie (kod {proc.returncode})\n{logs}"
            )
        try:
            if httpx.get(base_url + "/healthz", timeout=5).status_code == httpx.codes.OK:
                return proc, base_url
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"brak gotowości /healthz MCP po {MCP_READY_TIMEOUT_S} s\n{_mcp_logs(log_path)}"
            )
        time.sleep(MCP_READY_INTERVAL_S)


@pytest.fixture(scope="session")
def mcp_stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[McpStack]:
    """Stos MCP na świeżej bazie: API WD + dataset PL użytkownika A + proces ``app.mcp``."""
    tmp = tmp_path_factory.mktemp("mcp_stack")
    with start_server(tmp) as server:
        api_key = server.reset()
        api_base = server.base_url + "/api/v1"
        dataset_id = ingest_dataset(
            api_base,
            api_key,
            dataset_name=DATASET_NAME,
            document_name=DOCUMENT_NAME,
            text=DOCUMENT_TEXT,
        )
        procs: list[subprocess.Popen[bytes]] = []
        try:
            mcp_proc, mcp_base_url = _start_mcp(server.log_dir, api_base)
            procs.append(mcp_proc)
            yield McpStack(
                api_base=api_base,
                mcp_url=mcp_base_url + "/mcp",
                api_key=api_key,
                dataset_id=dataset_id,
                mcp_pid=mcp_proc.pid,
                log_dir=server.log_dir,
            )
        finally:
            for proc in procs:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
