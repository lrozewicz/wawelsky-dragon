"""Katalog GPU RunPod: parsowanie, filtrowanie (VRAM, region, kraj) i zamienniki.

Czyste funkcje bez I/O. Kraj centrum danych wynika z jego id (``EU-RO-1`` → ``RO``,
``US-TX-3`` → ``US``), region z ``GET /catalog/datacenters``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


@dataclass(frozen=True)
class DataCenter:
    id: str
    name: str
    region: str
    country: str
    availability: str = "NONE"


@dataclass(frozen=True)
class Gpu:
    id: str
    name: str
    vram_gb: int
    price_per_hr: float
    availability: str
    manufacturer: str = "NVIDIA"
    data_centers: tuple[DataCenter, ...] = field(default_factory=tuple)

    @property
    def available(self) -> bool:
        return _RANK.get(self.availability, 0) > 0


_CONTINENTS = frozenset({"EU", "EUR", "AP", "AS", "OC", "AF", "SA", "ME", "NA"})


def country_of(data_center_id: str) -> str:
    """Kod kraju z id centrum: ``EU-RO-1`` → ``RO``, ``EUR-IS-1`` → ``IS``, ``US-TX-3`` → ``US``.

    Pierwszy człon to kontynent (``EU``, ``EUR``, ``AP``…) albo sam kraj (``US``, ``CA``);
    nieznany układ → ``""``.
    """
    parts = data_center_id.upper().split("-")
    if parts[0] in _CONTINENTS:
        return parts[1] if len(parts) > 1 and len(parts[1]) == 2 else ""  # noqa: PLR2004
    return parts[0] if len(parts[0]) == 2 else ""  # noqa: PLR2004


def parse_data_centers(payload: list[dict[str, Any]]) -> dict[str, DataCenter]:
    """Słownik ``id → DataCenter`` z ``GET /catalog/datacenters``."""
    result: dict[str, DataCenter] = {}
    for row in payload:
        dc_id = str(row.get("id", ""))
        if dc_id:
            result[dc_id] = DataCenter(
                id=dc_id,
                name=str(row.get("name", dc_id)),
                region=str(row.get("region", "UNKNOWN")),
                country=country_of(dc_id),
            )
    return result


def parse_gpus(
    payload: list[dict[str, Any]],
    data_centers: dict[str, DataCenter] | None = None,
    *,
    cloud: str = "SECURE",
) -> list[Gpu]:
    """GPU z katalogu: tylko NVIDIA dostępne w danym cloudzie; cena za 1 GPU/h."""
    known = data_centers or {}
    cloud_key = cloud.lower()
    gpus: list[Gpu] = []
    for row in payload:
        if row.get("manufacturer", "NVIDIA") != "NVIDIA" or not row.get(cloud_key, False):
            continue
        centers = tuple(
            DataCenter(
                id=str(dc["id"]),
                name=str(dc.get("name", dc["id"])),
                region=known[str(dc["id"])].region if str(dc["id"]) in known else "UNKNOWN",
                country=country_of(str(dc["id"])),
                availability=str(dc.get("availability", "NONE")),
            )
            for dc in row.get("dataCenters", []) or []
            if dc.get("id")
        )
        price = float((row.get("price") or {}).get(cloud_key, 0) or 0)
        gpus.append(
            Gpu(
                id=str(row["id"]),
                name=str(row.get("name", row["id"])),
                vram_gb=int(row.get("memory", 0) or 0),
                price_per_hr=price,
                availability=str(row.get("availability", "NONE")),
                data_centers=centers,
            )
        )
    return gpus


def filter_gpus(  # noqa: PLR0913 — filtry z panelu
    gpus: list[Gpu],
    *,
    min_vram: int | None = None,
    max_vram: int | None = None,
    region: str | None = None,
    country: str | None = None,
    only_available: bool = False,
) -> list[Gpu]:
    """Filtry panelu; region/kraj zawężają też listę centrów danych przy GPU.

    Wynik rosnąco po cenie, potem po VRAM. GPU bez ceny (0) trafia na koniec — to zwykle pozycje
    niedostępne w danym cloudzie.
    """
    result: list[Gpu] = []
    for gpu in gpus:
        if min_vram is not None and gpu.vram_gb < min_vram:
            continue
        if max_vram is not None and gpu.vram_gb > max_vram:
            continue
        centers = tuple(
            dc
            for dc in gpu.data_centers
            if (region is None or dc.region == region)
            and (country is None or dc.country == country.upper())
            and dc.availability != "NONE"
        )
        if (region is not None or country is not None) and not centers:
            continue
        shown = Gpu(
            gpu.id,
            gpu.name,
            gpu.vram_gb,
            gpu.price_per_hr,
            gpu.availability if not (region or country) else _best(centers),
            gpu.manufacturer,
            centers if (region or country) else gpu.data_centers,
        )
        if only_available and not shown.available:
            continue
        result.append(shown)
    return sorted(result, key=lambda g: (g.price_per_hr <= 0, g.price_per_hr, g.vram_gb, g.id))


def _best(centers: tuple[DataCenter, ...]) -> str:
    return max((dc.availability for dc in centers), key=lambda a: _RANK.get(a, 0), default="NONE")


def alternatives(gpus: list[Gpu], chosen: Gpu, *, limit: int = 5) -> list[Gpu]:
    """Dostępne zamienniki o VRAM ≥ wybranego: najpierw najbliższy VRAM, potem najtańsze."""
    candidates = [
        g
        for g in gpus
        if g.id != chosen.id and g.vram_gb >= chosen.vram_gb and g.available and g.price_per_hr > 0
    ]
    return sorted(candidates, key=lambda g: (g.vram_gb, g.price_per_hr, g.id))[:limit]


def placement(gpu: Gpu, *, region: str | None = None, country: str | None = None) -> list[str]:
    """Id centrów danych do ``dataCenterIds`` (pusta lista = dowolne), zgodnie z filtrami."""
    if region is None and country is None:
        return []
    return [
        dc.id
        for dc in gpu.data_centers
        if (region is None or dc.region == region)
        and (country is None or dc.country == country.upper())
        and dc.availability != "NONE"
    ]
