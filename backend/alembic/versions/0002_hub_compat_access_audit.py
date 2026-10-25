# DDL z kontraktu WP E2-4 C1 (1:1, jedna instrukcja = jeden string). Nagłówka
# `# ruff: noqa: E501` (jak w 0001) tu NIE ma: żadna linia nie przekracza 100 znaków,
# a RUF100 słusznie zgłasza wtedy nieużywaną dyrektywę (verify-fast musi zostać zielony).
"""Tabele hub-compat: assistant_access i audit_log (kontrakt WP E2-4 C1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# DDL wg C1 — każda instrukcja CREATE jako osobny string. Wykonanie przez exec_driver_sql
# (spójnie z 0001; text() traktowałby fragmenty DDL jako parametry wiązane).
_TABLES_DDL: tuple[str, ...] = (
    """CREATE TABLE assistant_access (
  email VARCHAR(255) NOT NULL,
  chat_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_by VARCHAR(255) NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (email, chat_id),
  KEY ix_assistant_access_chat_id (chat_id),
  CONSTRAINT fk_assistant_access_chat FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE audit_log (
  id BIGINT NOT NULL AUTO_INCREMENT,
  ts BIGINT NOT NULL,
  actor_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  actor_label VARCHAR(255) NOT NULL,
  action VARCHAR(64) NOT NULL,
  target_type VARCHAR(32) NOT NULL,
  target_id VARCHAR(64) NOT NULL,
  details JSON NULL,
  ip VARCHAR(45) NULL,
  PRIMARY KEY (id),
  KEY ix_audit_log_ts (ts)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

# Kolejność DROP wg C1 — najpierw dziecko (audit_log bez FK, ale zgodnie z kontraktem).
_DROP_ORDER: tuple[str, ...] = (
    "audit_log",
    "assistant_access",
)


def upgrade() -> None:
    """Tworzy tabele assistant_access i audit_log (C1)."""
    bind = op.get_bind()
    for ddl in _TABLES_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa tabele hub-compat w kolejności z kontraktu C1."""
    bind = op.get_bind()
    for name in _DROP_ORDER:
        # Nazwy tabel pochodzą ze stałej _DROP_ORDER — f-string nie wnosi ryzyka iniekcji.
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {name}")
