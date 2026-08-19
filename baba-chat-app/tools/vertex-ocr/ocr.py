#!/usr/bin/env python3
"""Executable wrapper for the Baba Chat Vertex OCR pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vertex_ocr.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

