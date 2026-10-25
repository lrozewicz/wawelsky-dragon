"""Rejestr etapów migracji (kontrakt §2) — etapy dodają zadania E4-6a i E4-6b."""

from app.tools.ragflow_migrate.stages.access import AccessStage
from app.tools.ragflow_migrate.stages.base import Stage
from app.tools.ragflow_migrate.stages.chats import ChatsStage
from app.tools.ragflow_migrate.stages.datasets import DatasetsStage
from app.tools.ragflow_migrate.stages.documents import DocumentsStage
from app.tools.ragflow_migrate.stages.integrations import IntegrationsStage
from app.tools.ragflow_migrate.stages.keys import KeysStage
from app.tools.ragflow_migrate.stages.models import ModelsStage
from app.tools.ragflow_migrate.stages.sessions import SessionsStage
from app.tools.ragflow_migrate.stages.users import UsersStage

#: Kolejność etapów w biegu (E4-6b wstawia kolejne wg 03 §11.3).
ORDER: tuple[str, ...] = (
    "users",
    "models",
    "datasets",
    "documents",
    "chats",
    "sessions",
    "keys",
    "access",
    "integrations",
)

#: Nazwa etapu -> instancja; E4-6a dodał `users`..`keys`, T1 WP E4-6b2 dodał `chats`,
#: T2 WP E4-6b2 dodał `sessions`, T3 — `access`; E4-6b1: `documents` (T4a), `integrations` (T7).
STAGES: dict[str, Stage] = {
    "users": UsersStage(),
    "models": ModelsStage(),
    "datasets": DatasetsStage(),
    "documents": DocumentsStage(),
    "chats": ChatsStage(),
    "sessions": SessionsStage(),
    "keys": KeysStage(),
    "access": AccessStage(),
    "integrations": IntegrationsStage(),
}
