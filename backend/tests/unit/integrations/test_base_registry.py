"""Testy portów konektora, konfiguracji i rejestru (K12 §2-§3; brief T2)."""

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from app.integrations.base import (
    ChangeSet,
    ConnectionReport,
    Container,
    RemoteItem,
    SyncCounts,
)
from app.integrations.config import IntegrationsConfig
from app.integrations.registry import clear, get, register, registered_types
from tests.fakes.integrations import FakeConnector, fake_load_config, make_item


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    clear()
    yield
    clear()


def test_register_and_get() -> None:
    connector = FakeConnector()
    register("fake", connector, fake_load_config)
    assert get("fake") == (connector, fake_load_config)


def test_get_unknown_type_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get("nope")


def test_registered_types_sorted() -> None:
    register("b", FakeConnector(), fake_load_config)
    register("a", FakeConnector(), fake_load_config)
    assert registered_types() == ["a", "b"]


def test_register_overwrites_same_type() -> None:
    first = FakeConnector()
    second = FakeConnector()
    register("fake", first, fake_load_config)
    register("fake", second, fake_load_config)
    assert registered_types() == ["fake"]
    assert get("fake") == (second, fake_load_config)


def test_clear_empties_registry() -> None:
    register("fake", FakeConnector(), fake_load_config)
    clear()
    assert registered_types() == []
    with pytest.raises(KeyError):
        get("fake")


def test_container_is_frozen() -> None:
    container = Container(id="c1", name="docs")
    assert container == Container(id="c1", name="docs")
    with pytest.raises(FrozenInstanceError):
        container.name = "other"  # type: ignore[misc]


def test_remote_item_is_frozen() -> None:
    item = make_item()
    with pytest.raises(FrozenInstanceError):
        item.name = "other"  # type: ignore[misc]


def test_make_item_defaults() -> None:
    assert make_item() == RemoteItem(
        container_id="c1",
        item_id="i1",
        name="a.txt",
        path="/a.txt",
        size=1,
        content_tag="c1",
        meta_tag="m1",
        modified_at=None,
        web_url=None,
        is_folder=False,
        deleted=False,
    )


def test_make_item_keyword_overrides() -> None:
    when = datetime(2025, 1, 2, 3, 4, 5)
    item = make_item(
        container_id="c2",
        item_id="i2",
        name="b.pdf",
        path="/dir/b.pdf",
        size=None,
        content_tag=None,
        meta_tag=None,
        is_folder=True,
        deleted=True,
        web_url="https://sp/b.pdf",
        modified_at=when,
    )
    assert item == RemoteItem(
        container_id="c2",
        item_id="i2",
        name="b.pdf",
        path="/dir/b.pdf",
        size=None,
        content_tag=None,
        meta_tag=None,
        modified_at=when,
        web_url="https://sp/b.pdf",
        is_folder=True,
        deleted=True,
    )


def test_changeset_defaults_and_equality() -> None:
    item = make_item()
    changeset = ChangeSet(items=[item], cursor="cur")
    assert changeset.reset_required is False
    assert changeset == ChangeSet(items=[item], cursor="cur", reset_required=False)


def test_sync_counts_defaults_and_mutation() -> None:
    counts = SyncCounts()
    assert (counts.added, counts.updated, counts.renamed) == (0, 0, 0)
    assert (counts.deleted, counts.failed, counts.skipped) == (0, 0, 0)
    counts.renamed += 1
    assert counts.renamed == 1


def test_connection_report_shape_is_frozen() -> None:
    report = ConnectionReport(
        ok=True,
        checks=[{"name": "graph_auth", "ok": True, "message": "ok"}],
        resolved={"site_id": "s1"},
    )
    assert report.ok is True
    assert report.resolved["site_id"] == "s1"
    with pytest.raises(FrozenInstanceError):
        report.ok = False


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("tick_seconds", 30),
        ("stale_lock_minutes", 15),
        ("heartbeat_seconds", 60),
        ("wait_timeout_seconds", 600),
        ("cancel_wait_seconds", 10),
        ("events_retention_days", 90),
        ("events_flush_every", 50),
        ("events_flush_seconds", 2.0),
        ("purge_excluded_containers", False),
    ],
)
def test_integrations_config_defaults(field: str, expected: object) -> None:
    assert getattr(IntegrationsConfig(), field) == expected


def test_integrations_config_is_frozen() -> None:
    config = IntegrationsConfig()
    with pytest.raises(FrozenInstanceError):
        config.tick_seconds = 1  # type: ignore[misc]
