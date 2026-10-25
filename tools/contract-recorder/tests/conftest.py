"""Import modułów narzędzia: katalog nadrzędny na ścieżce sys.path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
