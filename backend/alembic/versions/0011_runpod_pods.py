"""Pody RunPod uruchamiane z panelu (`runpod_pods`) — modele OCR hostowane na GPU w chmurze.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Jeden wiersz = jedno wdrożenie modelu (cykl życia poda). `status`: requested → provisioning →
# starting → loading → ready → terminating → terminated | failed. `api_token_enc` to zaszyfrowany
# klucz vLLM (`--api-key`), bo adres proxy RunPod jest publiczny. `pending_parse` — dokumenty do
# sparsowania, gdy pod będzie gotowy. Klucz API RunPod leży w `wd_settings` (zaszyfrowany).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE runpod_pods (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  status VARCHAR(16) NOT NULL,
  pod_id VARCHAR(64) NULL,
  gpu_id VARCHAR(128) NOT NULL,
  gpu_name VARCHAR(128) NOT NULL,
  vram_gb INT NOT NULL,
  cloud VARCHAR(16) NOT NULL,
  data_center_ids JSON NOT NULL DEFAULT '[]',
  data_center_id VARCHAR(32) NULL,
  price_per_hr DECIMAL(8,3) NOT NULL DEFAULT 0,
  base_url VARCHAR(255) NULL,
  api_token_enc VARBINARY(512) NULL,
  pending_parse JSON NOT NULL DEFAULT '[]',
  error VARCHAR(1000) NULL,
  created_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  create_time BIGINT NOT NULL,
  update_time BIGINT NOT NULL,
  ready_time BIGINT NULL,
  busy_time BIGINT NULL,
  end_time BIGINT NULL,
  PRIMARY KEY (id),
  KEY ix_runpod_pods_status (status, model_name)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

_DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE runpod_pods",)


def upgrade() -> None:
    """Tworzy `runpod_pods`."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `runpod_pods`."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
