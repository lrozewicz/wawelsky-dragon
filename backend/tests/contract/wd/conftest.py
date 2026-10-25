"""Fixture'y testów katalogu ``tests/contract/wd`` — re-eksport ``admin_support`` (kontrakt §6).

Podkatalogi ``users``/``access``/``system`` mają własne ``conftest.py`` z tym samym re-eksportem
(czytelność: każdy pakiet testów deklaruje swoje fixture'y), a testy leżące bezpośrednio w ``wd``
(``test_k3_input_redaction.py``) korzystają z tego pliku.
"""

from tests.contract.wd.admin_support import *  # noqa: F403
