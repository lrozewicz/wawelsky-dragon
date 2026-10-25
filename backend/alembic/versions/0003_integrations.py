# ruff: noqa: E501 - DDL przepisany 1:1 z kontraktu K12 §1 (długie linie CONSTRAINT/KEY), nie zawijamy.
"""Tabele integracji: 6 tabel frameworku konektorów (kontrakt K12 §1).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# DDL wg K12 §1 — każda instrukcja CREATE jako osobny string, w kolejności z kontraktu.
# Wykonanie przez exec_driver_sql (spójnie z 0001/0002; text() traktowałby fragmenty DDL
# jako parametry wiązane).
_TABLES_DDL: tuple[str, ...] = (
    """CREATE TABLE integrations (
  id BIGINT NOT NULL AUTO_INCREMENT,
  type VARCHAR(32) NOT NULL,
  name VARCHAR(255) NOT NULL,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  owner_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  config JSON NOT NULL,
  secret_enc TEXT NULL,
  secret_last4 VARCHAR(8) NULL,
  max_file_size_bytes BIGINT NOT NULL DEFAULT 209715200,
  ignored_extensions JSON NOT NULL,
  scan_interval_seconds INT NOT NULL DEFAULT 300,
  delete_propagation BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  is_running BOOLEAN NOT NULL DEFAULT FALSE,
  lock_acquired_at BIGINT NULL,
  lock_owner VARCHAR(64) NULL,
  cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  last_sync_at BIGINT NULL,
  last_sync_status ENUM('success','partial','failed','cancelled') NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_integrations_dataset (dataset_id),
  KEY ix_integrations_due (is_active, is_running, last_sync_at),
  CONSTRAINT ck_integrations_scan_interval CHECK (scan_interval_seconds >= 30),
  CONSTRAINT fk_integrations_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE integration_sharepoint (
  integration_id BIGINT NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  client_id VARCHAR(64) NOT NULL,
  site_url VARCHAR(1024) NOT NULL,
  site_id VARCHAR(512) NULL,
  site_display_name VARCHAR(512) NULL,
  excluded_library_names JSON NOT NULL,
  PRIMARY KEY (integration_id),
  CONSTRAINT fk_integration_sharepoint_integration FOREIGN KEY (integration_id) REFERENCES integrations (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE integration_containers (
  integration_id BIGINT NOT NULL,
  container_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(512) NOT NULL,
  delta_cursor TEXT NULL,
  last_sync_at BIGINT NULL,
  discovered_at BIGINT NOT NULL,
  PRIMARY KEY (integration_id, container_id),
  CONSTRAINT fk_integration_containers_integration FOREIGN KEY (integration_id) REFERENCES integrations (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE integration_item_mappings (
  integration_id BIGINT NOT NULL,
  container_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  item_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  document_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  content_tag VARCHAR(255) NULL,
  meta_tag VARCHAR(255) NULL,
  name VARCHAR(1024) NULL,
  path VARCHAR(2048) NULL,
  web_url VARCHAR(2048) NULL,
  last_status ENUM('ok','failed') NOT NULL,
  last_error VARCHAR(2000) NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (integration_id, container_id, item_id),
  KEY ix_integration_item_mappings_document (document_id),
  CONSTRAINT fk_integration_item_mappings_integration FOREIGN KEY (integration_id) REFERENCES integrations (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE integration_sync_runs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  integration_id BIGINT NOT NULL,
  integration_type VARCHAR(32) NOT NULL,
  run_trigger ENUM('schedule','manual','full') NOT NULL,
  started_at BIGINT NOT NULL,
  finished_at BIGINT NULL,
  status ENUM('running','success','partial','failed','cancelled') NOT NULL,
  added INT NOT NULL DEFAULT 0,
  updated INT NOT NULL DEFAULT 0,
  renamed INT NOT NULL DEFAULT 0,
  deleted INT NOT NULL DEFAULT 0,
  failed INT NOT NULL DEFAULT 0,
  skipped INT NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY ix_integration_sync_runs_integration (integration_id, id)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE integration_sync_events (
  id BIGINT NOT NULL AUTO_INCREMENT,
  run_id BIGINT NOT NULL,
  integration_id BIGINT NOT NULL,
  integration_type VARCHAR(32) NOT NULL,
  level ENUM('info','warn','error') NOT NULL,
  message VARCHAR(2000) NOT NULL,
  file_path VARCHAR(1024) NULL,
  container_id VARCHAR(255) NULL,
  container_name VARCHAR(512) NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (id),
  KEY ix_integration_sync_events_run (run_id, id),
  KEY ix_integration_sync_events_created (created_at)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

# Kolejność DROP wg K12 §1 — najpierw tabele zależne.
_DROP_ORDER: tuple[str, ...] = (
    "integration_sync_events",
    "integration_sync_runs",
    "integration_item_mappings",
    "integration_containers",
    "integration_sharepoint",
    "integrations",
)


def upgrade() -> None:
    """Tworzy 6 tabel integracji w kolejności z K12 §1."""
    bind = op.get_bind()
    for ddl in _TABLES_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa tabele integracji w kolejności z K12 §1."""
    bind = op.get_bind()
    for name in _DROP_ORDER:
        # Nazwy tabel pochodzą ze stałej _DROP_ORDER — f-string nie wnosi ryzyka iniekcji.
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {name}")
