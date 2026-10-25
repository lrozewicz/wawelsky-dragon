#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# Zmodyfikowano dla Wawelsky Dragon: wartości wyłącznie ze środowiska — usunięto odczyt pliku
# `docker/.env` (nie istnieje w tym repo), a `HOST_ADDRESS` ustala harness w `conftest.py`
# przed importem tego modułu.
#
import logging
import os

import pytest


def _config_value(name: str, default: str | None = None) -> str | None:
    return os.getenv(name) or default


API_PROXY_SCHEME = _config_value("API_PROXY_SCHEME", "python")
IS_GO_PROXY = API_PROXY_SCHEME == "go"
SDK_UNAUTHORIZED_ERROR_MESSAGE = "Invalid access token" if IS_GO_PROXY else "<Unauthorized '401: Unauthorized'>"


HOST_ADDRESS = os.environ.get("HOST_ADDRESS", "http://127.0.0.1:9380")
logging.info("Resolved API proxy configuration: scheme=%s, is_go_proxy=%s, host_address=%s", API_PROXY_SCHEME, IS_GO_PROXY, HOST_ADDRESS)
VERSION = "v1"
ZHIPU_AI_API_KEY = os.getenv("ZHIPU_AI_API_KEY")
if ZHIPU_AI_API_KEY is None:
    pytest.exit("Error: Environment variable ZHIPU_AI_API_KEY must be set")

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
if SILICONFLOW_API_KEY is None:
    pytest.exit("Error: Environment variable SILICONFLOW_API_KEY must be set")

EMAIL = "qa@infiniflow.org"
# password is "123"
PASSWORD = """ctAseGvejiaSWWZ88T/m4FQVOpQyUvP+x7sXtdv3feqZACiQleuewkUi35E16wSd5C5QcnkkcV9cYc8TKPTRZlxappDuirxghxoOvFcJxFU4ixLsD
fN33jCHRoDUW81IH9zjij/vaw8IbVyb6vuwg6MX6inOEBRRzVbRYxXOu1wkWY6SsI8X70oF9aeLFp/PzQpjoe/YbSqpTq8qqrmHzn9vO+yvyYyvmDsphXe
X8f7fp9c7vUsfOCkM+gHY3PadG+QHa7KI7mzTKgUTZImK6BZtfRBATDTthEUbbaTewY4H0MnWiCeeDhcbeQao6cFy1To8pE3RpmxnGnS8BsBn8w=="""

INVALID_API_TOKEN = "invalid_key_123"
INVALID_ID_32 = "0" * 32
DATASET_NAME_LIMIT = 128
DOCUMENT_NAME_LIMIT = 255
CHAT_ASSISTANT_NAME_LIMIT = 255
SESSION_WITH_CHAT_NAME_LIMIT = 255

DEFAULT_PARSER_CONFIG = {
    "layout_recognize": "DeepDOC",
    "chunk_token_num": 512,
    "delimiter": "\n",
    "auto_keywords": 0,
    "auto_questions": 0,
    "html4excel": False,
    "image_context_size": 0,
    "table_context_size": 0,
    "topn_tags": 3,
    "llm_id": "glm-4-flash@CI@ZHIPU-AI",
    "parent_child": {
        "use_parent_child": False,
        "children_delimiter": "\n",
    },
    "children_delimiter": "",
}
