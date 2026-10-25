"""Link podpisany eksportu bazy wiedzy (brief T0; kontrakt E7-1a §2).

Przykłady wejście→wyjście z briefu przepisane dosłownie. Podpis to hex(HMAC-SHA256)
i deterministyczny; weryfikacja przyjmuje zły/pusty/nie-ASCII `sig` jako ``False`` (bez wyjątku).
Slug jest ASCII (ł→l, bez znaków łączących), ``[a-z0-9-]``, nie dłuższy niż 64 znaki.
"""

from pathlib import Path

from app.services.kb_export_link import (
    EXPORT_LINK_TTL_S,
    EXPORTS_DIR,
    download_path,
    export_file_name,
    export_package_path,
    sign_export,
    verify_export,
)


def test_sign_export_is_hex_sha256_and_deterministic() -> None:
    sig = sign_export("k", "t1", 100)
    assert len(sig) == 64  # noqa: PLR2004 — 64 znaki hexa SHA-256 dosłownie z briefu T0
    assert sig == sig.lower()
    assert all(c in "0123456789abcdef" for c in sig)
    assert sig == sign_export("k", "t1", 100)


def test_sign_export_matches_contract_vector() -> None:
    # Wektor policzony niezależnie: hmac.new(b"k", b"export:t1:100", sha256).hexdigest().
    # Pinuje formułę HMAC-SHA256(secret, "export:{task_id}:{exp}") z CONTRACT §2
    # (kolejność ``task_id``/``exp`` i sekret).
    assert sign_export("k", "t1", 100) == (
        "69ecc7065899301d67c50e0b299b496b8c4c03c1abc5ebd4631e88c69fce1f03"
    )


def test_export_link_ttl_matches_contract() -> None:
    assert EXPORT_LINK_TTL_S == 86_400  # noqa: PLR2004 — TTL 24 h dosłownie z CONTRACT §2


def test_sign_export_changes_with_exp() -> None:
    assert sign_export("k", "t1", 100) != sign_export("k", "t1", 101)


def test_verify_export_accepts_matching_signature() -> None:
    assert verify_export("k", "t1", 100, sign_export("k", "t1", 100)) is True


def test_verify_export_rejects_wrong_exp() -> None:
    assert verify_export("k", "t1", 101, sign_export("k", "t1", 100)) is False


def test_verify_export_rejects_wrong_task_id() -> None:
    assert verify_export("k", "t2", 100, sign_export("k", "t1", 100)) is False


def test_verify_export_rejects_empty_signature() -> None:
    assert verify_export("k", "t1", 100, "") is False


def test_verify_export_rejects_non_hex_signature() -> None:
    assert verify_export("k", "t1", 100, "zz") is False


def test_verify_export_rejects_non_ascii_signature() -> None:
    assert verify_export("k", "t1", 100, "ąćę") is False


def test_verify_export_rejects_wrong_secret() -> None:
    assert verify_export("x", "t1", 100, sign_export("k", "t1", 100)) is False


def test_download_path() -> None:
    assert download_path("t1", 100, "ab") == "/api/wd/v1/exports/t1/download?exp=100&sig=ab"


def test_export_file_name_folds_diacritics() -> None:
    assert export_file_name("Zażółć gęślą jaźń") == "zazolc-gesla-jazn.wdkb.zip"


def test_export_file_name_slugifies_words() -> None:
    assert export_file_name("Rocznik Statystyczny GUS 2024") == (
        "rocznik-statystyczny-gus-2024.wdkb.zip"
    )


def test_export_file_name_empty_becomes_dataset() -> None:
    assert export_file_name("!!!") == "dataset.wdkb.zip"


def test_export_file_name_truncates_to_64_slug_chars() -> None:
    name = export_file_name("a" * 200)
    assert name == ("a" * 64) + ".wdkb.zip"


def test_export_package_path() -> None:
    assert export_package_path("/data", "t1") == Path("/data/exports/t1.wdkb.zip")


def test_export_package_path_accepts_path_root() -> None:
    assert export_package_path(Path("/data"), "t1") == Path("/data") / EXPORTS_DIR / "t1.wdkb.zip"
