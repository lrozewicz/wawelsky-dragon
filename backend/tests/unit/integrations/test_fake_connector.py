"""Testy test-double'a konektora (kontrakt C8; brief T2)."""

import asyncio
from pathlib import Path

import pytest

from app.integrations.base import ChangeSet, ConnectionReport, Container
from tests.fakes.integrations import FakeConnector, fake_load_config, make_item

C1 = Container(id="c1", name="Biblioteka")


async def test_script_two_pages_in_one_pass_then_empty() -> None:
    fake = FakeConnector()
    page_a = ChangeSet(items=[make_item(item_id="i1")], cursor="cur-a")
    page_b = ChangeSet(items=[make_item(item_id="i2")], cursor="cur-b")
    fake.script("c1", [page_a, page_b])

    assert [cs async for cs in fake.changes({}, C1, None)] == [page_a, page_b]

    # następny przebieg (kolejne wywołanie changes) — skrypt wyczerpany
    assert [cs async for cs in fake.changes({}, C1, None)] == [ChangeSet(items=[], cursor=None)]


async def test_script_run_adds_another_pass() -> None:
    fake = FakeConnector()
    first = ChangeSet(items=[make_item(item_id="i1")], cursor="c1")
    second = ChangeSet(items=[make_item(item_id="i2")], cursor="c2")
    fake.script("c1", [first])
    fake.script_run("c1", [second])

    assert [cs async for cs in fake.changes({}, C1, None)] == [first]
    assert [cs async for cs in fake.changes({}, C1, None)] == [second]
    assert [cs async for cs in fake.changes({}, C1, None)] == [ChangeSet(items=[], cursor=None)]


async def test_script_reset_signal_then_full_state() -> None:
    fake = FakeConnector()
    first = [ChangeSet(items=[make_item(item_id="i1")], cursor="cur-1")]
    after_reset = [
        ChangeSet(items=[make_item(item_id="i1"), make_item(item_id="i9")], cursor="cur-2")
    ]
    fake.script_reset("c1", first=first, after_reset=after_reset)

    assert [cs async for cs in fake.changes({}, C1, None)] == first

    # cursor != None -> sygnał resetu (silnik ustawia cursor=None i powtarza changes)
    reset = [cs async for cs in fake.changes({}, C1, "cur-1")]
    assert reset == [ChangeSet(items=[], cursor=None, reset_required=True)]

    # kolejne wywołanie z cursor=None -> pełny stan po resecie
    assert [cs async for cs in fake.changes({}, C1, None)] == after_reset


async def test_empty_pass_repeats_for_unknown_container() -> None:
    fake = FakeConnector()
    assert [cs async for cs in fake.changes({}, C1, "cur-x")] == [
        ChangeSet(items=[], cursor="cur-x")
    ]


async def test_calls_log_records_changes_and_download(tmp_path: Path) -> None:
    fake = FakeConnector()
    fake.script("c1", [ChangeSet(items=[], cursor=None)])

    async for _ in fake.changes({}, C1, "c0"):
        pass
    await fake.download({}, make_item(), tmp_path / "d.bin", max_bytes=100)

    assert fake.calls == [("changes", "c1", "c0"), ("download", "c1", "i1")]


async def test_connection_resolve_containers_and_web_link() -> None:
    fake = FakeConnector()
    fake.containers = [C1]

    report = await fake.test_connection({}, dataset_exists=True)
    assert report == ConnectionReport(ok=True, checks=[], resolved={})
    assert await fake.resolve({}) == {}
    assert await fake.list_containers({}) == [C1]
    assert await fake.web_link({}, "c1", "i1") is None


async def test_download_writes_file_and_returns_size(tmp_path: Path) -> None:
    fake = FakeConnector()
    fake.files[("c1", "i1")] = b"12345"
    dest = tmp_path / "out.bin"

    written = await fake.download({}, make_item(), dest, max_bytes=100)

    assert written == 5  # noqa: PLR2004 — długość danych skonstruowanych w teście
    assert dest.read_bytes() == b"12345"


async def test_download_uses_default_content(tmp_path: Path) -> None:
    fake = FakeConnector()
    dest = tmp_path / "default.bin"

    assert await fake.download({}, make_item(), dest, max_bytes=100) == 7  # noqa: PLR2004 — len("content")
    assert dest.read_bytes() == b"content"


async def test_download_too_large_raises_without_writing(tmp_path: Path) -> None:
    fake = FakeConnector()
    fake.files[("c1", "i1")] = b"12345"
    dest = tmp_path / "big.bin"

    with pytest.raises(ValueError, match="too large"):
        await fake.download({}, make_item(), dest, max_bytes=3)

    assert not dest.exists()


async def test_download_failure_raises_configured_exception(tmp_path: Path) -> None:
    fake = FakeConnector()
    fake.fail_download[("c1", "i1")] = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await fake.download({}, make_item(), tmp_path / "fail.bin", max_bytes=100)


async def test_download_waits_for_block_event(tmp_path: Path) -> None:
    fake = FakeConnector()
    fake.block = asyncio.Event()
    dest = tmp_path / "blocked.bin"

    task = asyncio.create_task(fake.download({}, make_item(), dest, max_bytes=100))
    await asyncio.sleep(0)  # jedno przejście pętli: zadanie dochodzi do await block.wait()
    assert not task.done()

    fake.block.set()
    assert await task == 7  # noqa: PLR2004 — len("content")
    assert dest.read_bytes() == b"content"


async def test_fake_load_config_returns_empty_cfg() -> None:
    assert await fake_load_config(object()) == {}
