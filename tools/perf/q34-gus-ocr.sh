#!/usr/bin/env bash
# Pomiar etapów parsowania rocznika GUS przez OCR (kontrakt C8, WP E5-H8b; C4 WP E5-H8e).
# Woła wdperf.gus_ocr z katalogu backend/ (importuje app.* i httpx z env backendu).
#
#   tools/perf/q34-gus-ocr.sh --base-url URL --email E --password P \
#     [--pdf PLIK] [--vision-model N] [--embedding-model MODEL@DOSTAWCA] \
#     [--fake-llm-url URL] [--worker-container C] [--timeout-min N]
#
# Hasło można podać zmienną WD_PERF_PASSWORD; PDF domyślnie bierze się z $WD_REAL_CORPUS.
# Lista modeli: bez `--vision-model` dataset bez parsera wizji; `--embedding-model` wymaga formatu
# <model>@<dostawca>, np. openai/text-embedding-3-large@OpenAI-API-Compatible (błędny format = błąd).
# first_ocr_request mierzy czas do pierwszego żądania do modelu wizji: z --fake-llm-url (GET /v1/fake/stats),
# a bez niego z logu zadania (pierwsza linia OCR pages, inaczej OCR concurrency) — źródło w polu
# first_ocr_request_source wyniku JSON. Token odświeżany przy 401 i profilaktycznie co 10 min (bieg > 15 min).
# Limit oczekiwania na parsowanie ustawia --timeout-min (minuty, domyślnie 30).
# Wynik: czytelna tabela + linia JSON; kod wyjścia != 0 przy błędzie dokumentu albo limicie czasu.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT/backend"
exec env PYTHONPATH="../tools/perf:." uv run --frozen python -m wdperf.gus_ocr "$@"
