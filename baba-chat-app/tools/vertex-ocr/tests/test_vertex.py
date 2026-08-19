from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vertex_ocr.vertex import VertexGeminiOCR

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None


class VertexSdkTests(unittest.TestCase):
    @unittest.skipUnless(genai_types is not None, "google-genai is installed in the OCR environment")
    def test_builds_thinking_config_and_ultra_high_image_part(self) -> None:
        client = VertexGeminiOCR(
            project="test-project",
            location="global",
            model="gemini-3.7-flash",
        )

        config = client._generation_config(genai_types)
        self.assertEqual(
            config.thinking_config.thinking_level,
            genai_types.ThinkingLevel.LOW,
        )

        part = client._image_part(genai_types, b"fake png bytes")
        self.assertEqual(
            part.media_resolution.level,
            genai_types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH,
        )
        self.assertEqual(part.inline_data.mime_type, "image/png")


if __name__ == "__main__":
    unittest.main()
