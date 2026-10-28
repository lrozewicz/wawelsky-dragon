"""Modele, które WD potrafi uruchomić na RunPod: obraz, polecenie vLLM i wymagania sprzętowe.

Dodanie modelu = jeden wpis w ``HOSTED_MODELS`` (nic więcej nie zna nazwy konkretnego modelu):
panel, cykl życia poda, rejestracja w WD i parsowanie czytają wszystko z ``HostedModel``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.parsing.vision_profile import PROFILE_KEY

PORT = 8000
POD_NAME_PREFIX = "wd-"
INSTANCE_PREFIX = "runpod-"


@dataclass(frozen=True)
class HostedModel:
    """Opis modelu hostowanego jako serwer zgodny z OpenAI (vLLM)."""

    name: str  # nazwa w rejestrze WD i ``--served-model-name``
    title: str
    hf_model: str
    image: str
    model_type: str  # typ w tabeli models (np. ``image2text``)
    min_vram_gb: int  # poniżej tego vLLM nie wystartuje (model + KV cache)
    recommended_vram_gb: int
    container_disk_gb: int
    max_model_len: int
    max_concurrency: int  # ``extra.max_concurrency`` modelu w rejestrze (równoległe strony OCR)
    startup_timeout_s: int  # pobranie obrazu i wag + start vLLM
    # Jak WD rozmawia z modelem przy parsowaniu stron (`html` | `otsl`); trafia do `models.extra`.
    recognition_profile: str | None = None
    # Dodatkowe argumenty `vllm serve` specyficzne dla modelu (np. limity multimodalne).
    extra_args: tuple[str, ...] = ()

    @property
    def instance_name(self) -> str:
        return f"{INSTANCE_PREFIX}{self.name}"

    def registry_extra(self) -> dict[str, Any]:
        """``models.extra`` modelu w rejestrze WD (równoległość i profil rozpoznawania)."""
        extra: dict[str, Any] = {"max_concurrency": self.max_concurrency}
        if self.recognition_profile:
            extra[PROFILE_KEY] = self.recognition_profile
        return extra

    def cmd(self, api_token: str) -> list[str]:
        """Argumenty vLLM (ENTRYPOINT to ``vllm serve``); token chroni publiczny adres proxy."""
        return [
            "--model",
            self.hf_model,
            "--served-model-name",
            self.name,
            "--max-model-len",
            str(self.max_model_len),
            "--gpu-memory-utilization",
            "0.85",
            "--max-num-seqs",
            str(self.max_concurrency * 2),
            *self.extra_args,
            "--api-key",
            api_token,
            "--port",
            str(PORT),
        ]


HOSTED_MODELS: dict[str, HostedModel] = {
    "xiaomi-ocr-0-runpod": HostedModel(
        # Inna nazwa niż lokalny `xiaomi-ocr-0` z compose: nazwy modeli w rejestrze są unikalne.
        name="xiaomi-ocr-0-runpod",
        title="Xiaomi-OCR-0 (RunPod)",
        hf_model="SeerRay-Lab/Xiaomi-OCR-0",
        image="vllm/vllm-openai:v0.30.0",
        model_type="image2text",
        min_vram_gb=16,
        recommended_vram_gb=24,
        container_disk_gb=40,
        max_model_len=16384,
        max_concurrency=16,
        startup_timeout_s=1500,
        recognition_profile="otsl",
        extra_args=("--limit-mm-per-prompt", json.dumps({"image": 1, "video": 0})),
    )
}


def get_model(name: str) -> HostedModel | None:
    """Model hostowany po nazwie albo ``None``."""
    return HOSTED_MODELS.get(name)


def pod_body(  # noqa: PLR0913 — parametry ciała żądania
    model: HostedModel,
    *,
    pod_name: str,
    gpu_id: str,
    api_token: str,
    cloud: str,
    data_center_ids: list[str],
) -> dict[str, Any]:
    """Ciało ``POST /pods``: 1 GPU, port 8000 przez proxy HTTP, vLLM z kluczem API."""
    body: dict[str, Any] = {
        "name": f"{POD_NAME_PREFIX}{pod_name}",
        "image": model.image,
        "cmd": model.cmd(api_token),
        "ports": [f"{PORT}/http"],
        "disk": model.container_disk_gb,
        "cloud": cloud,
        "gpu": {"id": gpu_id, "count": 1},
        "env": {"HF_HUB_ENABLE_HF_TRANSFER": "0"},
    }
    if data_center_ids:
        body["dataCenterIds"] = data_center_ids
    return body


def proxy_url(pod_id: str) -> str:
    """Publiczny adres proxy RunPod portu vLLM (bazowy URL API zgodnego z OpenAI).

    Host jest zawsze ``*.proxy.runpod.net``; id poda pochodzi z API RunPod i jest walidowane,
    więc nie da się nim podstawić innego hosta (SSRF, H13).
    """
    if re.fullmatch(r"[a-z0-9]{6,40}", pod_id) is None:
        raise ValueError("invalid RunPod pod id")
    return f"https://{pod_id}-{PORT}.proxy.runpod.net/v1"
