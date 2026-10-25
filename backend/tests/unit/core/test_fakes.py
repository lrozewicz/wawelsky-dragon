"""Testy fałszywek testowych: FrozenClock i SeqIdGenerator (kontrakt C7)."""

from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

_DEFAULT_MS = 1790157600000
_ADVANCE_MS = 500
_ADVANCED_MS = 1790157600500
_SEQ_FIRST = "00000000000000000000000000000001"
_SEQ_SECOND = "00000000000000000000000000000002"


def test_frozen_clock_starts_and_advances() -> None:
    clock = FrozenClock()
    assert clock.now_ms() == _DEFAULT_MS
    clock.advance(_ADVANCE_MS)
    assert clock.now_ms() == _ADVANCED_MS


def test_seq_id_generator_counts_from_one() -> None:
    gen = SeqIdGenerator()
    assert gen.new_id() == _SEQ_FIRST
    assert gen.new_id() == _SEQ_SECOND
