"""Wejście usługi — ``python -m app.gpu_agent``."""

import sys

from app.gpu_agent.server import main

if __name__ == "__main__":
    sys.exit(main())
