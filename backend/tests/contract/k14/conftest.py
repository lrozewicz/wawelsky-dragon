"""Fixture'y testów wygasania kluczy API (K14 §2) — re-eksport wspólnych z ``tests.contract.wd``.

Trasy wszystkich rodzin uwierzytelniania kluczem (``/api/v1/**``, ``/v1/**``, ``/api/wd/v1/**``)
obsługuje ta sama aplikacja co testy WD, więc ``app``/``container``/``settings`` bierzemy
z ``admin_support`` (jak podkatalogi ``tests/contract/wd/*``).
"""

from tests.contract.wd.admin_support import *  # noqa: F403
