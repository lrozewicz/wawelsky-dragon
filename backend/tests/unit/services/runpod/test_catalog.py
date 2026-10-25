"""Katalog GPU RunPod: filtry (VRAM, region, kraj), zamienniki i kraj z id centrum danych."""

from app.services.runpod import catalog
from tests.fakes.runpod import DATA_CENTERS, GPU_ROWS

MIN_VRAM = 16


def _gpus(cloud: str = "SECURE") -> list[catalog.Gpu]:
    return catalog.parse_gpus(GPU_ROWS, catalog.parse_data_centers(DATA_CENTERS), cloud=cloud)


def test_country_of_data_center_ids() -> None:
    ids = ["EU-RO-1", "EUR-IS-1", "US-TX-3", "CA-MTL-3", "AP-JP-1", ""]
    assert [catalog.country_of(i) for i in ids] == ["RO", "IS", "US", "CA", "JP", ""]


def test_parse_skips_amd_and_other_clouds() -> None:
    assert "AMD Instinct MI300X OAM" not in {g.id for g in _gpus()}
    assert {g.id for g in _gpus("COMMUNITY")} == {"NVIDIA GeForce RTX 4090"}


def test_filter_by_vram_sorts_by_price() -> None:
    shown = catalog.filter_gpus(_gpus(), min_vram=16, max_vram=24)
    assert [g.id for g in shown] == [
        "NVIDIA RTX A4000",
        "NVIDIA L4",
        "NVIDIA GeForce RTX 4090",
    ]


def test_filter_only_available_hides_out_of_stock() -> None:
    ids = {g.id for g in catalog.filter_gpus(_gpus(), only_available=True)}
    assert "NVIDIA RTX A4000" not in ids and "NVIDIA A40" in ids


def test_filter_by_region_and_country_narrows_data_centers() -> None:
    europe = catalog.filter_gpus(_gpus(), region="EUROPE")
    rtx = next(g for g in europe if g.id == "NVIDIA GeForce RTX 4090")
    assert [dc.id for dc in rtx.data_centers] == ["EU-RO-1"]
    czech = catalog.filter_gpus(_gpus(), country="cz")
    assert [g.id for g in czech] == ["NVIDIA A40"]
    assert catalog.filter_gpus(_gpus(), region="ASIA") == []


def test_alternatives_have_at_least_the_vram_and_are_available() -> None:
    gpus = _gpus()
    chosen = next(g for g in gpus if g.id == "NVIDIA RTX A4000")  # 16 GB, brak mocy
    alts = catalog.alternatives(gpus, chosen)
    assert [g.id for g in alts] == ["NVIDIA L4", "NVIDIA GeForce RTX 4090", "NVIDIA A40"]
    assert all(g.vram_gb >= MIN_VRAM and g.available for g in alts)


def test_placement_limits_data_centers_to_filters() -> None:
    rtx = next(g for g in _gpus() if g.id == "NVIDIA GeForce RTX 4090")
    assert catalog.placement(rtx) == []
    assert catalog.placement(rtx, country="RO") == ["EU-RO-1"]
    assert catalog.placement(rtx, region="NORTH_AMERICA") == ["US-TX-3"]
