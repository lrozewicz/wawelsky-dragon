"""Profil wizji modelu OCR/VLM: sposób promptowania i parsowania odpowiedzi strony.

Profil mówi, jak rozmawiać z modelem: ``otsl`` (Xiaomi-OCR-0: Markdown z tabelami OTSL) albo
``html`` (ogólny VLM: gotowy HTML). Źródłem prawdy jest ``models.extra["recognition_profile"]``
(dla modeli hostowanych na RunPod ustawia go opis ``HostedModel``). Zgadywanie po nazwie zostaje
tylko jako zapas dla modeli zarejestrowanych ręcznie, bez tego pola.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

VisionProfile = Literal["html", "otsl"]

PROFILE_KEY = "recognition_profile"


def vision_profile(model_name: str, extra: Mapping[str, Any] | None = None) -> VisionProfile:
    """Profil z ``extra[recognition_profile]``; bez niego po nazwie (Xiaomi-OCR → ``otsl``)."""
    declared = (extra or {}).get(PROFILE_KEY)
    if declared == "otsl":
        return "otsl"
    if declared == "html":
        return "html"
    lowered = model_name.lower()
    return "otsl" if "xiaomi-ocr" in lowered or "fake-ocr" in lowered else "html"
