"""Snapshot H15: reguła `S` w ruff, zbiór plików z `noqa: S608`, brak cichych f-stringów SQL.

Cel: każdy f-string SQL bez `noqa: S608` przechodzi przegląd (wpis w `REVIEWED_SQL_FSTRINGS`
albo w raporcie `work/wp/E5-2a/reports/h15-s608.md`). **Nowy plik w `app/` z f-stringiem SQL
i bez `noqa` ⇒ czerwień ⇒ przegląd H15.** Wyjątki są per-linia (nie per-plik), bo wyjątek dla
całego pliku przepuściłby po cichu nowe f-stringi w tym samym pliku; numer linii też nie —
przesuwa się przy każdej edycji. Uzasadnienie: `docs/decisions/DEC-212.md`.
"""

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND.parent
APP = BACKEND / "app"

# Regex z briefu T3 pkt 5(c): f-string zaczynający się od czasownika SQL, z interpolacją `{`.
SQL_FSTRING_RE = re.compile(r"""f["'](SELECT|INSERT|UPDATE|DELETE)\b[^"']*\{""")

# Wygenerowane: `git grep -l "noqa: S608" -- backend/app` (33 pliki na HEAD).
S608_FILES = frozenset(
    {
        "backend/app/db/repositories/agent_sessions.py",
        "backend/app/db/repositories/agents.py",
        "backend/app/db/repositories/audit_log.py",
        "backend/app/db/repositories/chat_sessions.py",
        "backend/app/db/repositories/chats.py",
        "backend/app/db/repositories/chunk_vectors.py",
        "backend/app/db/repositories/chunks.py",
        "backend/app/db/repositories/datasets.py",
        "backend/app/db/repositories/documents_query.py",
        "backend/app/db/repositories/embedding_check.py",
        "backend/app/db/repositories/files.py",
        "backend/app/db/repositories/integrations/admin.py",
        "backend/app/db/repositories/integrations/catalog.py",
        "backend/app/db/repositories/integrations/core.py",
        "backend/app/db/repositories/integrations/runs.py",
        "backend/app/db/repositories/integrations/sharepoint.py",
        "backend/app/db/repositories/kb_export_data.py",
        "backend/app/db/repositories/maintenance.py",
        "backend/app/db/repositories/models.py",
        "backend/app/db/repositories/provider_instances.py",
        "backend/app/db/repositories/retrieval.py",
        "backend/app/db/repositories/searches.py",
        "backend/app/db/repositories/user_resources.py",
        "backend/app/db/repositories/users.py",
        "backend/app/db/repositories/web_search_providers.py",
        "backend/app/tools/ragflow_migrate/diff.py",
        "backend/app/tools/ragflow_migrate/source.py",
        "backend/app/tools/ragflow_migrate/stages/chats.py",
        "backend/app/tools/ragflow_migrate/stages/datasets.py",
        "backend/app/tools/ragflow_migrate/stages/doc_docs.py",
        "backend/app/tools/ragflow_migrate/stages/doc_files.py",
        "backend/app/tools/ragflow_migrate/stages/doc_links.py",
        "backend/app/tools/ragflow_migrate/stages/integration_sql.py",
        "backend/app/tools/ragflow_migrate/stages/keys.py",
        "backend/app/tools/ragflow_migrate/stages/sessions.py",
        "backend/app/tools/ragflow_migrate/stages/users.py",
        "backend/app/tools/rotate_crypto_key.py",
    }
)

# Trafienia regexu poza S608_FILES, które przeszły przegląd H15 (DEC-212). Pary
# (ścieżka względem korzenia repo, treść linii po strip()); zmiana treści linii ⇒ czerwień.
REVIEWED_SQL_FSTRINGS = frozenset(
    {
        # `columns` i `_FROM`: stałe albo argumenty prywatnego `_statement` wołanego tylko
        # ze stałymi ("COUNT(*)", _COLUMNS, _FROM); `clauses`: stałe literały z bind-parametrami;
        # `tail`: ORDER_BY_COLUMNS[orderby] (biała lista) + ASC/DESC.
        (
            "backend/app/db/repositories/ingestion_logs.py",
            'sql = f"SELECT {columns}{_FROM} WHERE " + " AND ".join(clauses) + tail',
        ),
    }
)


def _files_with_noqa() -> set[str]:
    """Ścieżki (względem korzenia repo) plików `app/**/*.py` z `noqa: S608`."""
    return {
        str(path.relative_to(REPO_ROOT))
        for path in APP.rglob("*.py")
        if "noqa: S608" in path.read_text()
    }


def _sql_fstring_lines() -> set[tuple[str, str]]:
    """Pary (ścieżka, treść linii) trafień regexu SQL w plikach spoza `S608_FILES`."""
    hits: set[tuple[str, str]] = set()
    for path in APP.rglob("*.py"):
        relative = str(path.relative_to(REPO_ROOT))
        if relative in S608_FILES:
            continue
        for line in path.read_text().splitlines():
            if SQL_FSTRING_RE.search(line):
                hits.add((relative, line.strip()))
    return hits


def test_ruff_select_includes_bandit_s() -> None:
    """(a) `tool.ruff.lint.select` w `backend/pyproject.toml` zawiera `S` (reguły bandit)."""
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    assert "S" in config["tool"]["ruff"]["lint"]["select"]


def test_s608_file_set_is_exact() -> None:
    """(b) Zbiór plików z `noqa: S608` jest dokładnie równy `S608_FILES` (nowy plik ⇒ czerwień)."""
    assert _files_with_noqa() == set(S608_FILES)


def test_no_unreviewed_sql_fstrings_outside_s608_files() -> None:
    """(c) Trafienia f-stringów SQL poza `S608_FILES` to dokładnie przejrzane wyjątki (DEC-212)."""
    assert _sql_fstring_lines() == set(REVIEWED_SQL_FSTRINGS)
