"""Przepływ testu kształtów: datasets/documents/chunks/retrieval (C4.2, K6 §5 p. 4).

Każda operacja T2 wołana na prawdziwym serwerze; odpowiedź JSON walidowana modelem
200 z openapi.json w trybie ścisłym (``check``) — bez zmiany zachowania aplikacji.
"""

import time

import httpx

from tests.integration.api.openapi_shapes import check, check_raw

# Limit oczekiwania na DONE (s) i interwał odpytywania listy (wymóg 3 briefu).
_DONE_LIMIT_S = 300
_POLL_INTERVAL_S = 1
_OK = 200  # HTTP 200 dla downloadu (PLR2004)

# Treść uploadowanego dokumentu (≥ 300 bajtów UTF-8) — słowo-klucz „smok" dla retrievalu.
_WAWEL_TEXT = (
    "Legenda o smoku wawelskim należy do najstarszych opowieści Krakowa. "
    "Smok zamieszkiwał jaskinię u stóp wzgórza wawelskiego i co noc wymuszał "
    "na mieszkańcach okup w postaci bydła. Rycerz Dratewka podłożył lniane "
    "skóry wypchane siarką i saletrą; smok pożarł je, zapragnął pić i pił "
    "z Wisły aż pękł. Na miejscu jaskini, według podań, stanął zamek "
    "wawelski, a u jego podnóża pomnik smoka zione ogniem co kilka minut.\n"
    "Opowieść o smoku wawelskim powtarzana jest w podręcznikach i przewodnikach.\n"
)


def flow(client: httpx.Client) -> set[str]:  # noqa: PLR0915 — jeden przepływ T2 po kolei
    """Wywołuje operacje T2 i zwraca nazwy zwalidowanych komponentów (wymóg 3 briefu)."""
    validated: set[str] = set()

    # datasets_create → datasets_list → datasets_get → datasets_update.
    resp = client.post("/api/v1/datasets", json={"name": "wd_shapes_ds"})
    validated.add(check("datasets_create", resp))
    ds = str(resp.json()["data"]["id"])
    validated.add(check("datasets_list", client.get("/api/v1/datasets")))
    validated.add(check("datasets_get", client.get(f"/api/v1/datasets/{ds}")))
    validated.add(
        check("datasets_update", client.put(f"/api/v1/datasets/{ds}", json={"description": "opis"}))
    )

    # documents_upload (multipart) → documents_list → documents_parse.
    resp = client.post(
        f"/api/v1/datasets/{ds}/documents",
        files={"file": ("wawel.txt", _WAWEL_TEXT.encode("utf-8"), "text/plain")},
    )
    validated.add(check("documents_upload", resp))
    doc = str(resp.json()["data"][0]["id"])
    validated.add(check("documents_list", client.get(f"/api/v1/datasets/{ds}/documents")))
    validated.add(
        check(
            "documents_parse",
            client.post(f"/api/v1/datasets/{ds}/documents/parse", json={"document_ids": [doc]}),
        )
    )

    # Odpytywanie documents_list aż run == "DONE" (limit 300 s, wymóg 3).
    deadline = time.monotonic() + _DONE_LIMIT_S
    while True:
        last = client.get(f"/api/v1/datasets/{ds}/documents")
        if str(last.json()["data"]["docs"][0]["run"]) == "DONE":
            break
        if time.monotonic() > deadline:
            raise AssertionError(
                f"documents_parse nie doszedł do DONE w {_DONE_LIMIT_S}s: {last.text}"
            )
        time.sleep(_POLL_INTERVAL_S)
    validated.add(check("documents_list", last))

    # Ingestia i embedding (E2-1 DS2): podsumowanie, logi plików, log po id, embedding/check.
    validated.add(
        check(
            "datasets_ingestions_summary", client.get(f"/api/v1/datasets/{ds}/ingestions/summary")
        )
    )
    resp = client.get(
        f"/api/v1/datasets/{ds}/ingestions", params={"log_type": "file", "page_size": 30}
    )
    validated.add(check("datasets_ingestions_list", resp))
    log_id = str(resp.json()["data"]["logs"][0]["id"])
    validated.add(
        check("datasets_ingestions_get", client.get(f"/api/v1/datasets/{ds}/ingestions/{log_id}"))
    )
    validated.add(
        check(
            "datasets_embedding_check",
            client.post(
                f"/api/v1/datasets/{ds}/embedding/check", json={"embd_id": "fake-embed-1024"}
            ),
        )
    )

    # Metadane datasetu (E2-1 DS3): konfiguracja, podsumowanie, zmiana, spłaszczenie.
    validated.add(
        check("datasets_metadata_config_get", client.get(f"/api/v1/datasets/{ds}/metadata/config"))
    )
    validated.add(
        check(
            "datasets_metadata_config_update",
            client.put(
                f"/api/v1/datasets/{ds}/metadata/config",
                json={
                    "metadata": [{"key": "author", "type": "string"}],
                    "built_in_metadata": [],
                },
            ),
        )
    )
    validated.add(
        check("datasets_metadata_summary", client.get(f"/api/v1/datasets/{ds}/metadata/summary"))
    )
    validated.add(
        check(
            "datasets_metadata_update",
            client.post(
                f"/api/v1/datasets/{ds}/metadata/update",
                json={
                    "selector": {"document_ids": [doc]},
                    "updates": [{"key": "k", "value": "v"}],
                    "deletes": [],
                },
            ),
        )
    )
    validated.add(
        check(
            "datasets_metadata_flattened",
            client.get("/api/v1/datasets/metadata/flattened", params={"dataset_ids": ds}),
        )
    )

    # documents_stop na dokumencie DONE: success_count 0 + errors.
    validated.add(
        check(
            "documents_stop",
            client.post(f"/api/v1/datasets/{ds}/documents/stop", json={"document_ids": [doc]}),
        )
    )

    # documents_update (PATCH) → documents_update_legacy (PUT) → download (bez check).
    validated.add(
        check(
            "documents_update",
            client.patch(
                f"/api/v1/datasets/{ds}/documents/{doc}", json={"meta_fields": {"k": "v"}}
            ),
        )
    )
    validated.add(
        check(
            "documents_update_legacy",
            client.put(f"/api/v1/datasets/{ds}/documents/{doc}", json={"meta_fields": {"k": "v"}}),
        )
    )
    # documents_metadata_config (S-320, E6-1a): JSON-Schema metadanych dokumentu.
    validated.add(
        check(
            "documents_metadata_config",
            client.put(
                f"/api/v1/datasets/{ds}/documents/{doc}/metadata/config",
                json={"metadata": {"type": "object", "properties": {}}},
            ),
        )
    )
    validated.update(_documents_extra(client, ds, doc))

    # chunks_list → chunks_create → chunks_get → chunks_update(+legacy) → chunks_switch.
    validated.add(check("chunks_list", client.get(f"/api/v1/datasets/{ds}/documents/{doc}/chunks")))
    resp = client.post(
        f"/api/v1/datasets/{ds}/documents/{doc}/chunks",
        json={"content": "Smok wawelski — ręczny chunk"},
    )
    validated.add(check("chunks_create", resp))
    chunk = str(resp.json()["data"]["chunk"]["id"])
    validated.add(
        check("chunks_get", client.get(f"/api/v1/datasets/{ds}/documents/{doc}/chunks/{chunk}"))
    )
    validated.add(
        check(
            "chunks_update",
            client.patch(
                f"/api/v1/datasets/{ds}/documents/{doc}/chunks/{chunk}",
                json={"content": "zmieniony"},
            ),
        )
    )
    validated.add(
        check(
            "chunks_update_legacy",
            client.put(
                f"/api/v1/datasets/{ds}/documents/{doc}/chunks/{chunk}",
                json={"content": "zmieniony"},
            ),
        )
    )
    validated.add(
        check(
            "chunks_switch",
            client.patch(
                f"/api/v1/datasets/{ds}/documents/{doc}/chunks",
                json={"chunk_ids": [chunk], "available_int": 0},
            ),
        )
    )

    # retrieval_query → retrieval_search → retrieval_search_dataset.
    query = {"question": "smok", "dataset_ids": [ds]}
    validated.add(check("retrieval_query", client.post("/api/v1/retrieval", json=query)))
    validated.add(check("retrieval_search", client.post("/api/v1/datasets/search", json=query)))
    validated.add(
        check(
            "retrieval_search_dataset",
            client.post(f"/api/v1/datasets/{ds}/search", json=query),
        )
    )

    # Dify (E2-1 OD): POST, GET i health. Odpowiedź rekordów jest surowa (bez koperty code),
    # więc walidujemy ją ``check_raw`` modelem DifyRecords z openapi.json.
    dify = {
        "knowledge_id": ds,
        "query": "smok",
        "retrieval_setting": {"top_k": 10, "score_threshold": 0.0},
    }
    posted = client.post("/api/v1/dify/retrieval", json=dify)
    validated.add(check_raw("dify_retrieval_post", posted))
    validated.add(
        check_raw(
            "dify_retrieval_get",
            client.get(
                "/api/v1/dify/retrieval",
                params={
                    "knowledge_id": ds,
                    "query": "smok",
                    "top_k": "10",
                    "score_threshold": "0.0",
                },
            ),
        )
    )
    validated.add(check("dify_retrieval_health", client.get("/api/v1/dify/retrieval/health")))

    # chunks_delete → documents_parse_legacy → documents_stop_legacy.
    # DELETE z ciałem: httpx.Client.delete nie przyjmuje json= — wołamy request wprost.
    validated.add(
        check(
            "chunks_delete",
            client.request(
                "DELETE",
                f"/api/v1/datasets/{ds}/documents/{doc}/chunks",
                json={"chunk_ids": [chunk]},
            ),
        )
    )
    validated.add(
        check(
            "documents_parse_legacy",
            client.post(f"/api/v1/datasets/{ds}/chunks", json={"document_ids": [doc]}),
        )
    )
    validated.add(
        check(
            "documents_stop_legacy",
            client.request("DELETE", f"/api/v1/datasets/{ds}/chunks", json={"document_ids": [doc]}),
        )
    )
    validated.update(_documents_files(client, doc))

    # documents_delete → datasets_delete (sprzątanie).
    validated.add(
        check(
            "documents_delete",
            client.request("DELETE", f"/api/v1/datasets/{ds}/documents", json={"ids": [doc]}),
        )
    )
    validated.add(
        check("datasets_delete", client.request("DELETE", "/api/v1/datasets", json={"ids": [ds]}))
    )

    return validated


def _documents_extra(client: httpx.Client, ds: str, doc: str) -> set[str]:
    """Pobranie pliku oraz trasy E2-1 DOC (osobna funkcja: limit instrukcji w ``flow``)."""
    downloaded = client.get(f"/api/v1/datasets/{ds}/documents/{doc}")
    assert downloaded.status_code == _OK and downloaded.content, downloaded.text
    # documents_metadatas → documents_batch_update_status (fragment E2-1 DOC).
    return {
        check(
            "documents_metadatas",
            client.patch(
                f"/api/v1/datasets/{ds}/documents/metadatas",
                json={
                    "selector": {"document_ids": [doc]},
                    "updates": [{"key": "m", "value": "v"}],
                    "deletes": [],
                },
            ),
        ),
        check(
            "documents_batch_update_status",
            client.post(
                f"/api/v1/datasets/{ds}/documents/batch-update-status",
                json={"doc_ids": [doc], "status": "1"},
            ),
        ),
    }


def _documents_files(client: httpx.Client, doc: str) -> set[str]:
    """Trasy plikowe E2-1 DOC2 (osobna funkcja: limit instrukcji w ``flow``).

    Pobranie i preview pliku to odpowiedzi binarne (bez walidacji modelu — K6 §4 p. 1);
    ingest wołany z ``delete=true``, żeby krok był niezależny od stanu zadań dokumentu.
    """
    for path in (f"/api/v1/documents/{doc}", f"/api/v1/documents/{doc}/preview"):
        downloaded = client.get(path)
        assert downloaded.status_code == _OK and downloaded.content, downloaded.text
    return {
        check(
            "documents_ingest",
            client.post(
                "/api/v1/documents/ingest", json={"doc_ids": [doc], "run": "1", "delete": True}
            ),
        ),
        check(
            "documents_upload_info",
            client.post(
                "/api/v1/documents/upload",
                files={"file": ("wawel.txt", _WAWEL_TEXT.encode("utf-8"), "text/plain")},
            ),
        ),
        check("thumbnails_list", client.get("/api/v1/thumbnails", params={"doc_ids": doc})),
    }
