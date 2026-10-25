"""Re-eksport fixture'ów bazy dla testów API na MariaDB (brief T3) — fixture'y z
tests/integration/auth/conftest.py nie są widoczne w tests/integration/api/.
"""

from tests.integration.auth.conftest import auth_settings, migrated_db, sm  # noqa: F401
from tests.integration.conftest import fresh_db  # noqa: F401
