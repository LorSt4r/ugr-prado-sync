"""
Module execution entry point (`python -m prado`).
"""

from __future__ import annotations

import sys

from prado.cli import main

if __name__ == "__main__":
    sys.exit(main())
