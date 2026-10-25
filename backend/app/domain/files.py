"""Typy plików menedżera plików (K16 §1 p. 6, CONTRACT E4-5a §D1.5).

``filename_type`` to 1:1 port ``api/utils/file_utils.py::filename_type`` z upstream v0.27.2
(wynik jako string, nie ``FileType``): rozszerzenie decyduje o typie, rozpoznajemy
``pdf``/``doc``/``visual``/``aural``, resztę (i nazwy niepoprawne) zwracamy jako ``other``.
"""

import os
import re
from typing import Final

# Stała na folder — `filename_type` jej nie zwraca, ale menedżer plików rozróżnia foldery (§D2).
FOLDER_TYPE: Final = "folder"

# Limit długości nazwy z upstream `api/constants.py`; dłuższa nazwa → `other`.
_FILE_NAME_LEN_LIMIT: Final = 255

_PDF_RE: Final = re.compile(r".*\.pdf$")
_DOC_RE: Final = re.compile(
    r".*\.(msg|eml|doc|docx|ppt|pptx|yml|xml|htm|json|jsonl|ldjson|csv|txt|ini|xls|xlsx|wps|rtf"
    r"|hlp|pages|numbers|key|md|mdx|py|js|java|c|cpp|h|php|go|ts|sh|cs|kt|html|sql|epub)$"
)
_AURAL_RE: Final = re.compile(r".*\.(wav|flac|ape|alac|wavpack|wv|mp3|aac|ogg|vorbis|opus)$")
_VISUAL_RE: Final = re.compile(
    r".*\.(jpg|jpeg|png|tif|gif|bmp|pcx|tga|exif|fpx|svg|psd|cdr|pcd|dxf|ufo|eps|ai|raw|wmf"
    r"|webp|avif|apng|icon|ico|mpg|mpeg|avi|rm|rmvb|mov|wmv|asf|dat|asx|wvx|mpe|mpa|mp4|mkv)$"
)


def filename_type(filename: str) -> str:
    """Typ pliku z rozszerzenia: ``pdf``/``doc``/``visual``/``aural``/``other`` (§D1.5).

    Nazwa jest normalizowana jak w upstream (basename, bez spacji na brzegach, małe litery);
    pusta lub dłuższa niż 255 znaków → ``other``.
    """
    base = os.path.basename(filename).strip()
    if not base or len(base) > _FILE_NAME_LEN_LIMIT:
        return "other"
    name = base.lower()
    if _PDF_RE.match(name):
        return "pdf"
    if _DOC_RE.match(name):
        return "doc"
    if _AURAL_RE.match(name):
        return "aural"
    if _VISUAL_RE.match(name):
        return "visual"
    return "other"
