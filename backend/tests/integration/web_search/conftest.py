"""Fixture'y integracyjne wyszukiwania w sieci (CONTRACT E6-3f §C4, §C6).

`fake_searx` uruchamia stub `tools/fake-searx` jako podproces na porcie efemerycznym
(`FAKE_SEARX_PORT`) i czeka na `/health` (§C6, SC-E6-3f-04).
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

#: Katalog pakietu `fake_searx` (poza backendem) — dokładany do `PYTHONPATH` podprocesu.
FAKE_SEARX_DIR = Path(__file__).resolve().parents[4] / "tools" / "fake-searx"
#: Limit oczekiwania na `/health` stubu (sekundy) i interwał sondy.
_HEALTH_TIMEOUT_S = 10.0
_HEALTH_POLL_S = 0.05


def free_port() -> int:
    """Wolny port TCP na `127.0.0.1` (bind → odczyt → zamknięcie)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_health(base_url: str) -> None:
    """Czeka na `/health` stubu; brak odpowiedzi w limicie → `RuntimeError`."""
    deadline = time.monotonic() + _HEALTH_TIMEOUT_S
    with httpx.Client(timeout=1.0) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(f"{base_url}/health").status_code == httpx.codes.OK:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(_HEALTH_POLL_S)
    raise RuntimeError("fake-searx nie wystawił /health w limicie")


@pytest.fixture
def fake_searx() -> Iterator[str]:
    """Stub fake-searx jako podproces; zwraca jego `base_url`, po teście kończy proces (§C6)."""
    port = free_port()
    env = {**os.environ, "FAKE_SEARX_PORT": str(port), "PYTHONPATH": str(FAKE_SEARX_DIR)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "fake_searx.app"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_health(base_url)
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=_HEALTH_TIMEOUT_S)
