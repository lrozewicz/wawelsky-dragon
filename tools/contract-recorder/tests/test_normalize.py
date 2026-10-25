"""Testy normalizacji golden files (SP-5, kontrakt C2) — bez Dockera."""

import json

from normalize import (
    DATETIME,
    FLOAT,
    HTTP_DATE,
    IGNORE,
    TOKEN,
    TS_MS,
    TS_S,
    IdRegistry,
    normalize_json,
    normalize_sse,
)


class TestIdRegistry:
    def test_same_value_same_token(self):
        ids = IdRegistry()
        assert ids.token("dataset", "ab12" + "0" * 28) == "<ID:dataset#1>"
        assert ids.token("dataset", "ab12" + "0" * 28) == "<ID:dataset#1>"

    def test_numbering_per_kind(self):
        ids = IdRegistry()
        first = ids.token("dataset", "a" * 32)
        document = ids.token("document", "b" * 32)
        second = ids.token("dataset", "c" * 32)
        assert first == "<ID:dataset#1>"
        assert document == "<ID:document#1>"
        assert second == "<ID:dataset#2>"

    def test_numbering_per_kind_independent(self):
        ids = IdRegistry()
        assert ids.token("chat", "a" * 32) == "<ID:chat#1>"
        assert ids.token("id", "b" * 32) == "<ID:id#1>"
        assert ids.token("chat", "c" * 32) == "<ID:chat#2>"


class TestNormalizeJson:
    def test_timestamp_ms(self):
        ids = IdRegistry()
        assert normalize_json({"create_time": 1727430000123}, ids) == {
            "create_time": TS_MS
        }

    def test_http_date(self):
        ids = IdRegistry()
        normalized = normalize_json({"date": "Sat, 27 Sep 2026 10:00:00 GMT"}, ids)
        assert normalized == {"date": HTTP_DATE}

    def test_datetime(self):
        ids = IdRegistry()
        normalized = normalize_json({"process_begin_at": "2026-09-27 10:00:00"}, ids)
        assert normalized == {"process_begin_at": DATETIME}

    def test_similarity_float_nested_lists(self):
        ids = IdRegistry()
        payload = {
            "data": {
                "chunks": [
                    {"similarity": 0.8234, "vector_similarity": 0.91, "keep": 5},
                    {"similarity": 0.1234},
                ]
            }
        }
        normalized = normalize_json(payload, ids)
        assert normalized["data"]["chunks"][0]["similarity"] == FLOAT
        assert normalized["data"]["chunks"][0]["vector_similarity"] == FLOAT
        assert normalized["data"]["chunks"][0]["keep"] == 5
        assert normalized["data"]["chunks"][1]["similarity"] == FLOAT

    def test_hex32_detected_as_id(self):
        ids = IdRegistry()
        normalized = normalize_json({"tenant_id": "e" * 32}, ids)
        assert normalized == {"tenant_id": "<ID:id#1>"}

    def test_captured_value_reuses_registered_token(self):
        ids = IdRegistry()
        assert ids.token("dataset", "a" * 32) == "<ID:dataset#1>"
        normalized = normalize_json({"id": "a" * 32, "owner": "b" * 32}, ids)
        assert normalized == {"id": "<ID:dataset#1>", "owner": "<ID:id#1>"}

    def test_key_order_preserved(self):
        ids = IdRegistry()
        normalized = normalize_json(
            {"zeta": 1, "create_time": 1727430000123, "alpha": 2}, ids
        )
        assert list(normalized) == ["zeta", "create_time", "alpha"]

    def test_token_key(self):
        ids = IdRegistry()
        assert normalize_json({"token": "rec-abc123"}, ids) == {"token": TOKEN}

    def test_scalar_list_uses_parent_key(self):
        ids = IdRegistry()
        ids.token("dataset", "a" * 32)
        normalized = normalize_json({"ids": ["a" * 32, "x"]}, ids)
        assert normalized == {"ids": ["<ID:dataset#1>", "x"]}

    def test_created_seconds(self):
        ids = IdRegistry()
        assert normalize_json({"created": 1727430000}, ids) == {"created": TS_S}

    def test_created_at_float_seconds(self):
        ids = IdRegistry()
        assert normalize_json({"created_at": 1790477599.7435365}, ids) == {
            "created_at": TS_S
        }

    def test_iso_t_datetime(self):
        ids = IdRegistry()
        normalized = normalize_json({"create_date": "2026-09-27T10:53:09"}, ids)
        assert normalized == {"create_date": DATETIME}

    def test_hex16_detected_as_id(self):
        ids = IdRegistry()
        assert normalize_json({"id": "85372c757c28fc5a"}, ids) == {"id": "<ID:id#1>"}

    def test_uuid_detected_as_id(self):
        ids = IdRegistry()
        value = "7ffcd794-f527-4f74-a8ac-e48f14a7513f"
        assert normalize_json({"id": value}, ids) == {"id": "<ID:id#1>"}

    def test_chatcmpl_detected_as_id(self):
        ids = IdRegistry()
        value = "chatcmpl-" + "0f716632ba2011f19fa3d999fa7f6291"
        assert normalize_json({"id": value}, ids) == {"id": "<ID:id#1>"}

    def test_prompt_timings_normalized(self):
        ids = IdRegistry()
        value = (
            "## Time elapsed:  \n  - Total: 83.6ms  \n  - Retrieval: 52.8ms  \n"
            "  - Token speed: 5381/s"
        )
        normalized = normalize_json({"prompt": value}, ids)
        assert normalized == {
            "prompt": (
                "## Time elapsed:  \n  - Total: <MS>  \n  - Retrieval: <MS>  \n"
                "  - Token speed: <SPEED>/s"
            )
        }

    def test_progress_msg_ignored(self):
        ids = IdRegistry()
        value = "Indexing done (0.53s). Task done (1.24s)"
        assert normalize_json({"progress_msg": value}, ids) == {"progress_msg": IGNORE}


class TestNormalizeE2Rules:
    """Reguły dodane w E2-0 (brief T2-normalize)."""

    def test_hex32_inside_text_replaced(self):
        ids = IdRegistry()
        value = "Chat(00564be4d3f14f4a8e0f6d3a7b1c41af) not found."
        assert normalize_json({"message": value}, ids) == {
            "message": "Chat(<ID:id#1>) not found."
        }

    def test_two_distinct_ids_in_text_numbered_and_reused(self):
        ids = IdRegistry()
        first = "00564be4d3f14f4a8e0f6d3a7b1c41af"
        second = "9f8e7d6c5b4a39281706f5e4d3c2b1a0"
        value = f"doc {first} and {second} then {first} again"
        assert normalize_json({"message": value}, ids) == {
            "message": "doc <ID:id#1> and <ID:id#2> then <ID:id#1> again"
        }

    def test_hex_in_text_uses_shared_registry(self):
        ids = IdRegistry()
        assert ids.token("dataset", "0" * 32) == "<ID:dataset#1>"
        normalized = normalize_json({"message": "dataset " + "0" * 32}, ids)
        assert normalized == {"message": "dataset <ID:dataset#1>"}

    def test_prompt_not_affected_by_hex_in_text(self):
        ids = IdRegistry()
        value = "context id 00564be4d3f14f4a8e0f6d3a7b1c41af and 12.5ms"
        assert normalize_json({"prompt": value}, ids) == {
            "prompt": "context id 00564be4d3f14f4a8e0f6d3a7b1c41af and <MS>"
        }

    def test_dict_key_hex32_replaced(self):
        ids = IdRegistry()
        payload = {"thumbnails": {"00564be4d3f14f4a8e0f6d3a7b1c41af": "aGVsbG8="}}
        assert normalize_json(payload, ids) == {"thumbnails": {"<ID:id#1>": "aGVsbG8="}}

    def test_dict_key_order_preserved(self):
        ids = IdRegistry()
        payload = {"m": {"d" * 32: "x", "zz": 1, "a" * 32: "y"}}
        normalized = normalize_json(payload, ids)
        assert list(normalized["m"]) == ["<ID:id#1>", "zz", "<ID:id#2>"]

    def test_beta_is_token(self):
        assert normalize_json({"beta": "sup3r-s3cret"}, IdRegistry()) == {"beta": TOKEN}

    def test_create_timestamp_flt_is_float(self):
        ids = IdRegistry()
        assert normalize_json({"create_timestamp_flt": 1790477599.7435365}, ids) == {
            "create_timestamp_flt": FLOAT
        }

    def test_elapsed_is_ignored(self):
        assert normalize_json({"elapsed": "0.4239"}, IdRegistry()) == {
            "elapsed": IGNORE
        }

    def test_task_executor_heartbeats_subtree_ignored(self):
        ids = IdRegistry()
        payload = {
            "data": {
                "task_executor_heartbeats": {"h1": {"beat": [1, 2], "ts": 17}},
                "keep": 1,
            }
        }
        assert normalize_json(payload, ids) == {
            "data": {"task_executor_heartbeats": IGNORE, "keep": 1}
        }

    def test_task_executor_heartbeats_list_ignored(self):
        ids = IdRegistry()
        normalized = normalize_json(
            {"task_executor_heartbeats": ["a", "b"], "other": ["a"]}, ids
        )
        assert normalized == {"task_executor_heartbeats": IGNORE, "other": ["a"]}

    def test_task_executor_heartbeats_scalar_ignored(self):
        ids = IdRegistry()
        assert normalize_json({"task_executor_heartbeats": 17}, ids) == {
            "task_executor_heartbeats": IGNORE
        }

    def test_regression_previous_shapes_unchanged(self):
        ids = IdRegistry()
        payload = {"message": "ok", "id": "a" * 32, "similarity": 0.5}
        assert normalize_json(payload, ids) == {
            "message": "ok",
            "id": "<ID:id#1>",
            "similarity": FLOAT,
        }

    def test_plain_string_unchanged(self):
        assert normalize_json({"message": "abc"}, IdRegistry()) == {"message": "abc"}

    def test_longer_hex_run_not_split(self):
        ids = IdRegistry()
        value = "hash " + "a" * 64
        assert normalize_json({"message": value}, ids) == {"message": value}


class TestNormalizeT4Determinism:
    """Reguła z briefu T4: ``used_token`` (int) -> ``<FLOAT>``.

    Licznik zużycia kontekstu zmienia się między biegami (zależnie od stanu stosu),
    więc jego wartość — także całkowita — nie wchodzi do złota.
    """

    def test_used_token_int_is_float(self):
        ids = IdRegistry()
        assert normalize_json({"used_token": 1234}, ids) == {"used_token": FLOAT}

    def test_used_token_zero_is_float(self):
        assert normalize_json({"used_token": 0}, IdRegistry()) == {"used_token": FLOAT}


class TestNormalizeSse:
    def test_prefix_without_space_preserved(self):
        ids = IdRegistry()
        raw = b'data:{"code":0,"data":true}\n\n'
        assert normalize_sse(raw, ids) == raw

    def test_prefix_with_space_preserved(self):
        ids = IdRegistry()
        raw = b'data: {"a": 1}\n\n'
        result = normalize_sse(raw, ids)
        assert result == b'data: {"a":1}\n\n'

    def test_done_frame_unchanged(self):
        ids = IdRegistry()
        raw = b"data:[DONE]\n\n"
        assert normalize_sse(raw, ids) == raw

    def test_terminator_preserved(self):
        ids = IdRegistry()
        raw = b'data:{"code":0,"message":"","data":"x"}\n\ndata:{"code":0,"data":true}\n\n'
        result = normalize_sse(raw, ids)
        assert result.endswith(b'data:{"code":0,"data":true}\n\n')
        assert result.count(b"\n\n") == 2

    def test_ids_normalized_inside_frames(self):
        ids = IdRegistry()
        raw = b'data:{"code":0,"data":{"id":"' + b"a" * 32 + b'","n":1}}\n\n'
        result = normalize_sse(raw, ids)
        payload = json.loads(result.decode("utf-8").removeprefix("data:"))
        assert payload == {"code": 0, "data": {"id": "<ID:id#1>", "n": 1}}

    def test_multiline_stream_full_roundtrip(self):
        ids = IdRegistry()
        raw = (
            b'data:{"code": 0, "message": "", "data": {"answer": "cz"}}\n\n'
            b'data:{"code": 0, "message": "", "data": true}\n\n'
        )
        result = normalize_sse(raw, ids)
        assert result == (
            b'data:{"code":0,"message":"","data":{"answer":"cz"}}\n\n'
            b'data:{"code":0,"message":"","data":true}\n\n'
        )

    def test_non_json_frame_untouched(self):
        ids = IdRegistry()
        raw = b"event: ping\n\n"
        assert normalize_sse(raw, ids) == raw

    def test_hex32_inside_message_normalized(self):
        ids = IdRegistry()
        raw = (
            b'data:{"code":102,"message":"Chat('
            + b"00564be4d3f14f4a8e0f6d3a7b1c41af"
            + b') not found."}\n\n'
        )
        assert normalize_sse(raw, ids) == (
            b'data:{"code":102,"message":"Chat(<ID:id#1>) not found."}\n\n'
        )


class TestNormalizeT5AgentFields:
    """Reguły z briefu T5: pola niedeterministyczne agentów.

    ``elapsed_time`` / ``_elapsed_time`` (czasy wykonania komponentów agenta)
    oraz ``_created_time`` (``perf_counter``) zmieniają się między biegami;
    ``version_title`` zawiera datę utworzenia sesji.
    """

    def test_elapsed_time_float_is_float(self):
        ids = IdRegistry()
        assert normalize_json({"elapsed_time": 0.00028401}, ids) == {
            "elapsed_time": FLOAT
        }

    def test_elapsed_time_int_is_float(self):
        ids = IdRegistry()
        assert normalize_json({"elapsed_time": 1}, ids) == {"elapsed_time": FLOAT}

    def test_underscore_elapsed_time_float_is_float(self):
        ids = IdRegistry()
        assert normalize_json({"outputs": {"_elapsed_time": 0.00015367}}, ids) == {
            "outputs": {"_elapsed_time": FLOAT}
        }

    def test_elapsed_time_nested_in_list(self):
        ids = IdRegistry()
        payload = {"data": {"outputs": [{"elapsed_time": 0.5, "_elapsed_time": 0.4}]}}
        assert normalize_json(payload, ids) == {
            "data": {"outputs": [{"elapsed_time": FLOAT, "_elapsed_time": FLOAT}]}
        }

    def test_created_time_ignored_top_level(self):
        ids = IdRegistry()
        assert normalize_json({"_created_time": 1292620.0835}, ids) == {
            "_created_time": IGNORE
        }

    def test_created_time_ignored_any_depth(self):
        ids = IdRegistry()
        payload = {
            "data": {
                "outputs": {"_created_time": 1292629.7037},
                "list": [{"_created_time": 1292620.0835}],
            }
        }
        assert normalize_json(payload, ids) == {
            "data": {
                "outputs": {"_created_time": IGNORE},
                "list": [{"_created_time": IGNORE}],
            }
        }

    def test_version_title_datetime_masked(self):
        ids = IdRegistry()
        value = "recorder_wd_rec_e6_agents_chatbot_2026-10-11 21:57:01"
        assert normalize_json({"version_title": value}, ids) == {
            "version_title": "recorder_wd_rec_e6_agents_chatbot_" + DATETIME
        }

    def test_version_title_datetime_masked_nested(self):
        ids = IdRegistry()
        payload = {
            "data": {"version_title": "wd_rec_e6_2026-10-11 21:57:01"},
            "list": [{"version_title": "wd_2026-10-11 21:57:11"}],
        }
        assert normalize_json(payload, ids) == {
            "data": {"version_title": "wd_rec_e6_" + DATETIME},
            "list": [{"version_title": "wd_" + DATETIME}],
        }

    def test_version_title_without_date_unchanged(self):
        ids = IdRegistry()
        assert normalize_json({"version_title": "recorder_plain"}, ids) == {
            "version_title": "recorder_plain"
        }


class TestNormalizeT5Sse:
    def test_elapsed_times_normalized_inside_frame(self):
        ids = IdRegistry()
        raw = (
            b'data:{"code":0,"data":{"elapsed_time":0.0002,'
            b'"outputs":{"_elapsed_time":0.0001,"_created_time":1292620.08}}}\n\n'
        )
        result = normalize_sse(raw, ids)
        payload = json.loads(result.decode("utf-8").removeprefix("data:"))
        assert payload == {
            "code": 0,
            "data": {
                "elapsed_time": FLOAT,
                "outputs": {"_elapsed_time": FLOAT, "_created_time": IGNORE},
            },
        }

    def test_version_title_normalized_inside_frame(self):
        ids = IdRegistry()
        raw = (
            b'data:{"code":0,"data":{"version_title":'
            b'"recorder_wd_rec_e6_agents_chatbot_2026-10-11 21:57:01"}}\n\n'
        )
        result = normalize_sse(raw, ids)
        payload = json.loads(result.decode("utf-8").removeprefix("data:"))
        assert payload == {
            "code": 0,
            "data": {"version_title": "recorder_wd_rec_e6_agents_chatbot_" + DATETIME},
        }
