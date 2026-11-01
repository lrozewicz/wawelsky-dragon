"""Agent GPU: jedyny element WD z dostępem do Dockera (wyjątek od H11, profil compose ``gpu``).

Dostęp do ``docker.sock`` to w praktyce root na hoście, więc API celowo jest wąskie: lista GPU,
start modelu z ``HOSTED_MODELS`` (obraz i argumenty wyłącznie z kodu, z żądania tylko nazwa modelu,
nazwa kontenera, GPU i klucz vLLM, każde walidowane) oraz odczyt i usunięcie kontenerów tego agenta
(etykieta właściciela). Każde żądanie poza ``/health`` wymaga tokenu. Bez portu na hoście.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import quote

from app.gpu_agent.docker_api import DockerApi, DockerError
from app.services.runpod.hosted import PROVIDER_LOCAL, HostedModel, get_model

logger = logging.getLogger("app.gpu_agent")

PORT = 9390
OWNER_LABEL = "wd.gpu-agent.owner"
MIB_PER_GB = 1024
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_NO_CONTENT = 204
HTTP_NOT_MODIFIED = 304
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
MAX_BODY = 4096
MAX_GPU_UTIL = 0.85
SMI_FIELDS = 7
_NAME_RE = re.compile(r"wd-gpu-[a-z0-9]{6,40}")
_GPU_RE = re.compile(r"GPU-[0-9a-f-]{8,64}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=index,uuid,name,memory.total,memory.free,memory.used,utilization.gpu",
    "--format=csv,noheader,nounits",
)


class AgentError(Exception):
    """Błąd żądania z kodem HTTP."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class GpuInfo:
    """Karta z ``nvidia-smi``; pamięć w MiB."""

    index: int
    uuid: str
    name: str
    memory_total_mb: int
    memory_free_mb: int
    memory_used_mb: int
    utilization_pct: int | None


def parse_smi(output: str) -> list[GpuInfo]:
    """Wiersze CSV ``nvidia-smi``; niepełne pomija, ``[N/A]`` w obciążeniu daje ``None``."""
    gpus: list[GpuInfo] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != SMI_FIELDS:
            continue
        index, uuid, name, total, free, used, util = parts
        gpus.append(
            GpuInfo(
                index=int(index),
                uuid=uuid,
                name=name,
                memory_total_mb=int(total),
                memory_free_mb=int(free),
                memory_used_mb=int(used),
                utilization_pct=int(util) if util.isdigit() else None,
            )
        )
    return gpus


def query_gpus() -> list[GpuInfo]:
    """Karty widoczne w kontenerze agenta; brak ``nvidia-smi`` albo sterownika = pusta lista."""
    try:
        done = subprocess.run(  # noqa: S603 — stałe argumenty
            _SMI_COMMAND, capture_output=True, text=True, timeout=15, check=True
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("nvidia-smi unavailable")
        return []
    return parse_smi(done.stdout)


def gpu_util_for(model: HostedModel, gpu: GpuInfo) -> float:
    """Ułamek pamięci karty dla vLLM: tyle, ile zaleca model, nie więcej niż ``MAX_GPU_UTIL``."""
    return min(MAX_GPU_UTIL, model.recommended_vram_gb * MIB_PER_GB / gpu.memory_total_mb)


class Agent:
    """Start i zatrzymanie kontenerów modeli; pobieranie obrazu trwa w wątku w tle."""

    def __init__(
        self,
        docker: DockerApi,
        query: Callable[[], list[GpuInfo]],
        *,
        network: str,
        hf_volume: str,
    ) -> None:
        self._docker = docker
        self._query = query
        self._network = network
        self._hf_volume = hf_volume
        self._lock = threading.Lock()
        # Kontenery w drodze (przed `docker start`) albo z nieudanym startem.
        self._phases: dict[str, dict[str, str | None]] = {}

    def gpus(self) -> list[dict[str, Any]]:
        return [asdict(gpu) for gpu in self._query()]

    def start(self, body: dict[str, Any], *, background: bool = True) -> dict[str, Any]:
        """Waliduje żądanie i uruchamia start; obraz i argumenty pochodzą z ``HOSTED_MODELS``."""
        model = get_model(str(body.get("model", "")))
        if model is None or model.provider != PROVIDER_LOCAL:
            raise AgentError(HTTP_BAD_REQUEST, "model is not allowed")
        name = str(body.get("name", ""))
        uuid = str(body.get("gpu", ""))
        token = str(body.get("api_token", ""))
        if not _NAME_RE.fullmatch(name):
            raise AgentError(HTTP_BAD_REQUEST, "invalid container name")
        if not _GPU_RE.fullmatch(uuid):
            raise AgentError(HTTP_BAD_REQUEST, "invalid GPU id")
        if not _TOKEN_RE.fullmatch(token):
            raise AgentError(HTTP_BAD_REQUEST, "invalid API token")
        gpu = next((g for g in self._query() if g.uuid == uuid), None)
        if gpu is None:
            raise AgentError(HTTP_BAD_REQUEST, "unknown GPU")
        if gpu.memory_free_mb < model.min_vram_gb * MIB_PER_GB:
            raise AgentError(HTTP_CONFLICT, f"{model.min_vram_gb} GB of free VRAM is required")
        with self._lock:
            if name in self._phases:
                raise AgentError(HTTP_CONFLICT, "container is already starting")
            self._phases[name] = {"state": "pulling", "error": None}
        spec = self._container_spec(model, gpu, token)
        if background:
            threading.Thread(target=self._run, args=(name, model, spec), daemon=True).start()
        else:
            self._run(name, model, spec)
        return {"name": name, "state": "pulling"}

    def state(self, name: str) -> dict[str, Any] | None:
        """Etap startu albo stan kontenera; ``None``, gdy go nie ma lub nie należy do agenta."""
        self._check_name(name)
        with self._lock:
            phase = self._phases.get(name)
        if phase is not None:
            return {"name": name, **phase}
        info = self._inspect(name)
        if info is None:
            return None
        running = bool(info.get("State", {}).get("Running"))
        return {
            "name": name,
            "state": "running" if running else "exited",
            "error": None if running else f"exit code {info.get('State', {}).get('ExitCode')}",
        }

    def stop(self, name: str) -> None:
        """Usuwa kontener agenta (cudzych nie dotyka); start w toku zostaje anulowany."""
        self._check_name(name)
        with self._lock:
            self._phases.pop(name, None)
        if self._inspect(name) is None:
            return
        status, raw = self._docker.request(
            "DELETE", f"/containers/{quote(name)}?force=true&v=false"
        )
        if status not in {HTTP_NO_CONTENT, HTTP_NOT_FOUND}:
            raise DockerError(f"docker rm failed: {status} {raw[:200]!r}")

    @staticmethod
    def _check_name(name: str) -> None:
        if not _NAME_RE.fullmatch(name):
            raise AgentError(HTTP_BAD_REQUEST, "invalid container name")

    def _inspect(self, name: str) -> dict[str, Any] | None:
        status, raw = self._docker.request("GET", f"/containers/{quote(name)}/json")
        if status == HTTP_NOT_FOUND:
            return None
        if status != HTTP_OK:
            raise DockerError(f"docker inspect failed: {status}")
        info: dict[str, Any] = json.loads(raw)
        if info.get("Config", {}).get("Labels", {}).get(OWNER_LABEL) != self._network:
            return None
        return info

    def _container_spec(self, model: HostedModel, gpu: GpuInfo, token: str) -> dict[str, Any]:
        return {
            "Image": model.image,
            "Cmd": model.cmd(token, gpu_util=gpu_util_for(model, gpu)),
            "Env": ["HF_HUB_ENABLE_HF_TRANSFER=0", f"NVIDIA_VISIBLE_DEVICES={gpu.uuid}"],
            "Labels": {OWNER_LABEL: self._network, "wd.gpu-agent.model": model.name},
            "HostConfig": {
                "Runtime": "nvidia",
                "NetworkMode": self._network,
                "IpcMode": "host",  # zalecenie vLLM, jak usługa `ocr` w compose
                "Binds": [f"{self._hf_volume}:/root/.cache/huggingface"],
            },
        }

    def _run(self, name: str, model: HostedModel, spec: dict[str, Any]) -> None:
        try:
            self._pull(model.image)
            if not self._advance(name, "creating"):
                return
            status, raw = self._docker.request(
                "POST", f"/containers/create?name={quote(name)}", spec
            )
            if status != HTTP_CREATED:
                raise DockerError(f"docker create failed: {status} {raw[:300]!r}")
            status, raw = self._docker.request("POST", f"/containers/{quote(name)}/start")
            if status not in {HTTP_NO_CONTENT, HTTP_NOT_MODIFIED}:
                raise DockerError(f"docker start failed: {status} {raw[:300]!r}")
            with self._lock:
                cancelled = name not in self._phases
                self._phases.pop(name, None)
            if cancelled:
                self.stop(name)
        except (DockerError, OSError) as exc:
            logger.warning("model start failed", extra={"container": name, "error": str(exc)})
            with self._lock:
                if name in self._phases:
                    self._phases[name] = {"state": "failed", "error": str(exc)[:500]}

    def _advance(self, name: str, state: str) -> bool:
        with self._lock:
            if name not in self._phases:
                return False
            self._phases[name] = {"state": state, "error": None}
            return True

    def _pull(self, image: str) -> None:
        status, _ = self._docker.request("GET", f"/images/{quote(image, safe='')}/json")
        if status == HTTP_OK:
            return
        repo, _, tag = image.rpartition(":")
        status, raw = self._docker.request(
            "POST", f"/images/create?fromImage={quote(repo, safe='')}&tag={quote(tag)}"
        )
        if status != HTTP_OK:
            raise DockerError(f"docker pull failed: {status} {raw[:300]!r}")
        for line in raw.splitlines():
            event = json.loads(line) if line.strip() else {}
            if "error" in event:
                raise DockerError(f"docker pull failed: {event['error']}"[:500])


def make_handler(agent: Agent, token: str) -> type[BaseHTTPRequestHandler]:
    """Klasa obsługi żądań związana z agentem i tokenem."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "wd-gpu-agent"

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug(format, *args)

        def _send(self, status: int, payload: Any = None) -> None:
            data = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            given = self.headers.get("Authorization", "")
            return hmac.compare_digest(given.encode(), f"Bearer {token}".encode())

        def _dispatch(self, action: Callable[[], tuple[int, Any]]) -> None:
            if not self._authorized():
                self._send(HTTP_UNAUTHORIZED, {"error": "unauthorized"})
                return
            try:
                self._send(*action())
            except AgentError as exc:
                self._send(exc.status, {"error": exc.message})
            except (DockerError, OSError) as exc:
                logger.warning("docker request failed", extra={"error": str(exc)})
                self._send(502, {"error": "docker request failed"})

        def _container_name(self) -> str:
            return self.path.removeprefix("/containers/")

        def _read_state(self) -> tuple[int, Any]:
            found = agent.state(self._container_name())
            return (HTTP_OK, found) if found else (HTTP_NOT_FOUND, {"error": "not found"})

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise AgentError(HTTP_BAD_REQUEST, "invalid body")
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError as exc:
                raise AgentError(HTTP_BAD_REQUEST, "invalid JSON") from exc
            if not isinstance(body, dict):
                raise AgentError(HTTP_BAD_REQUEST, "invalid body")
            return body

        def _stop(self) -> tuple[int, Any]:
            agent.stop(self._container_name())
            return HTTP_NO_CONTENT, None

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(HTTP_OK, {"status": "ok"})
            elif self.path == "/gpus":
                self._dispatch(lambda: (HTTP_OK, {"gpus": agent.gpus()}))
            elif self.path.startswith("/containers/"):
                self._dispatch(self._read_state)
            else:
                self._send(HTTP_NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/containers":
                self._send(HTTP_NOT_FOUND, {"error": "not found"})
                return
            self._dispatch(lambda: (HTTP_CREATED, agent.start(self._read_body())))

        def do_DELETE(self) -> None:
            if not self.path.startswith("/containers/"):
                self._send(HTTP_NOT_FOUND, {"error": "not found"})
                return
            self._dispatch(self._stop)

    return Handler


def main() -> int:
    """Start serwera; bez tokenu albo nazwy sieci agent nie wstaje (kod 2)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("WD_GPU_AGENT_TOKEN", "")
    network = os.environ.get("WD_GPU_AGENT_NETWORK", "")
    hf_volume = os.environ.get("WD_GPU_HF_VOLUME", "wd-gpu-hf-cache")
    if len(token) < 16 or not network:  # noqa: PLR2004
        logger.error(
            "WD_GPU_AGENT_TOKEN (min. 16 characters) and WD_GPU_AGENT_NETWORK are required"
        )
        return 2
    agent = Agent(DockerApi(), query_gpus, network=network, hf_volume=hf_volume)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(agent, token))  # noqa: S104
    logger.info("gpu agent listening on port %s", PORT)
    server.serve_forever()
    return 0
