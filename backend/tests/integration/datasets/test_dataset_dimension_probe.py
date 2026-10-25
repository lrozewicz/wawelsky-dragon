"""Sonda wymiaru embeddingów przy create/update datasetu (usterka #2, kontrakt T2 E5-H1).

Model z `dimension=NULL` (np. dodany ręcznie w bazie) nie może już wywracać `create`/`update`
błędem "has no dimension": WD wykonuje jedno wywołanie embeddingu, zapisuje zmierzony wymiar
i działa dalej. Testy jadą na prawdziwej MariaDB i fake-llm (marker db).
"""

from collections.abc import Sequence

import pytest

from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.errors import ValidationFailed
from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef
from app.services.datasets import DatasetService
from tests.integration.datasets.conftest import (
    count_sql,
    exec_sql,
    principal,
    seed_default_models,
    seed_model,
    seed_user,
)

pytestmark = pytest.mark.db

EMBEDDING_DIM = 1024  # fake-embed-1024
OTHER_EMBEDDING_DIM = 3072  # fake-embed-3072
# Bazowy URL nieosiągalny + klucz w URL: powód błędu nie może wyciec do komunikatu.
UNREACHABLE_BASE_URL = "http://sekret-probe-key@127.0.0.1:1/v1"


class _CountingGateway:
    """Bramka-dekorator: liczy wywołania `embed`, resztę metod deleguje do prawdziwej bramki."""

    def __init__(self, inner: LLMGateway) -> None:
        self._inner = inner
        self.embed_calls = 0

    async def embed(self, model: ModelRef, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls += 1
        return await self._inner.embed(model, texts)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


async def _dimension_of(container: Container, name: str) -> int | None:
    """Zapisany w `models` wymiar modelu o nazwie (None gdy wiersz/kolumna pusta)."""
    rows = await count_sql(
        container.sessionmaker,
        "SELECT id FROM models WHERE name = :name AND dimension = :dim",
        name=name,
        dim=EMBEDDING_DIM,
    )
    return EMBEDDING_DIM if rows == 1 else None


async def test_create_detects_missing_dimension(container: Container) -> None:
    """create z modelem embeddingów bez wymiaru: sonda ustawia embedding_dim=1024 (#2)."""
    await seed_model(container.sessionmaker, "fake-embed-1024", "embedding")  # dimension NULL
    await seed_model(container.sessionmaker, "fake-chat", "chat")
    user_id, email = await seed_user(container.sessionmaker)
    rec = await DatasetService(container).create(principal(user_id, email), name="ds")
    assert rec.embedding_model == "fake-embed-1024"
    assert rec.embedding_dim == EMBEDDING_DIM
    assert await _dimension_of(container, "fake-embed-1024") == EMBEDDING_DIM


async def test_update_detects_missing_dimension(container: Container) -> None:
    """update(embedding_model) na model bez wymiaru: sonda ustawia embedding_dim=3072 (#2)."""
    await seed_default_models(container.sessionmaker)
    await seed_model(
        container.sessionmaker,
        "fake-embed-3072",
        "embedding",
        is_default=False,  # domyślny embedding już istnieje (uq_models_default_key)
    )
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name="ds")
    fresh = await DatasetService(container).update(
        alice, rec.id, {"embedding_model": "fake-embed-3072"}
    )
    assert fresh.embedding_model == "fake-embed-3072"
    assert fresh.embedding_dim == OTHER_EMBEDDING_DIM
    assert await _dimension_of(container, "fake-embed-3072") is None  # 3072 ≠ 1024
    assert (
        await count_sql(
            container.sessionmaker,
            "SELECT id FROM models WHERE name = :name AND dimension = :dim",
            name="fake-embed-3072",
            dim=OTHER_EMBEDDING_DIM,
        )
        == 1
    )


async def test_create_unavailable_gateway(container: Container) -> None:
    """Sonda na nieosiągalną bramkę → ValidationFailed 'unavailable', bez klucza (#2)."""
    await seed_model(container.sessionmaker, "fake-embed-1024", "embedding")  # dimension NULL
    await seed_model(container.sessionmaker, "fake-chat", "chat")
    await exec_sql(
        container.sessionmaker,
        "UPDATE models SET base_url = :url WHERE name = :name",
        url=UNREACHABLE_BASE_URL,
        name="fake-embed-1024",
    )
    user_id, email = await seed_user(container.sessionmaker)
    with pytest.raises(ValidationFailed) as exc:
        await DatasetService(container).create(principal(user_id, email), name="ds")
    message = str(exc.value)
    assert exc.value.code == RetCode.ARGUMENT_ERROR
    assert message.startswith("embedding model fake-embed-1024 unavailable: ")
    assert "unavailable" in message
    assert "has no dimension" not in message
    assert "sekret-probe-key" not in message  # URL z kluczem nie wycieka do komunikatu


async def test_no_probe_when_dimension_known(container: Container) -> None:
    """Model z zapisanym wymiarem → create/update nie wołają sondy (licznik bramki)."""
    await seed_default_models(container.sessionmaker)
    await seed_model(
        container.sessionmaker,
        "fake-embed-3072",
        "embedding",
        dimension=OTHER_EMBEDDING_DIM,
        is_default=False,
    )
    spy = _CountingGateway(container.llm)
    container.llm = spy
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name="ds")
    assert rec.embedding_dim == EMBEDDING_DIM
    fresh = await DatasetService(container).update(
        alice, rec.id, {"embedding_model": "fake-embed-3072"}
    )
    assert fresh.embedding_dim == OTHER_EMBEDDING_DIM
    assert spy.embed_calls == 0
