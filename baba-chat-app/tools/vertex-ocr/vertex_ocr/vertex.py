"""Google Gen AI Vertex backend using Application Default Credentials only."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .models import OCRResult


DEFAULT_MODEL = "gemini-3.7-flash"
DEFAULT_THINKING_LEVEL = "LOW"
DEFAULT_MEDIA_RESOLUTION = "ULTRA_HIGH"
SUPPORTED_THINKING_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH"})
SUPPORTED_MEDIA_RESOLUTIONS = frozenset({"LOW", "MEDIUM", "HIGH", "ULTRA_HIGH"})


def _normalize_setting(value: str, *, name: str, supported: frozenset[str]) -> str:
    normalized = str(value).strip().replace("-", "_").upper()
    if normalized not in supported:
        supported_values = ", ".join(sorted(supported))
        raise ValueError(f"Unsupported {name} {value!r}; choose one of: {supported_values}")
    return normalized


def normalize_thinking_level(value: str) -> str:
    """Return the canonical Gemini 3 thinking level."""

    return _normalize_setting(
        value,
        name="thinking level",
        supported=SUPPORTED_THINKING_LEVELS,
    )


def normalize_media_resolution(value: str) -> str:
    """Return the canonical input image media resolution."""

    return _normalize_setting(
        value,
        name="media resolution",
        supported=SUPPORTED_MEDIA_RESOLUTIONS,
    )


class VertexDependencyError(RuntimeError):
    """Raised when the isolated Vertex dependency is not installed."""


class VertexGeminiOCR:
    """Thread-local google-genai clients configured for Vertex AI and ADC."""

    def __init__(
        self,
        *,
        project: str,
        location: str,
        model: str,
        thinking_level: str = DEFAULT_THINKING_LEVEL,
        media_resolution: str = DEFAULT_MEDIA_RESOLUTION,
        max_output_tokens: int = 8192,
    ) -> None:
        if not project:
            raise ValueError("A Google Cloud project is required for Vertex OCR")
        if not location:
            raise ValueError("A Vertex location is required for Vertex OCR")
        self.project = project
        self.location = location
        self.model = model
        self.thinking_level = normalize_thinking_level(thinking_level)
        self.media_resolution = normalize_media_resolution(media_resolution)
        self.max_output_tokens = max_output_tokens
        self._thread_local = threading.local()
        self._clients: list[Any] = []
        self._clients_lock = threading.Lock()

    def _get_client(self) -> Any:
        client = getattr(self._thread_local, "client", None)
        if client is not None:
            return client
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise VertexDependencyError(
                "google-genai is not installed. Install tools/vertex-ocr/requirements.txt."
            ) from exc

        # vertexai=True selects the Vertex AI backend. No API key is passed or read here.
        client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
            http_options=types.HttpOptions(api_version="v1"),
        )
        self._thread_local.client = client
        with self._clients_lock:
            self._clients.append(client)
        return client

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            text = response.text
        except Exception:
            text = None
        if isinstance(text, str) and text.strip():
            return text

        candidates = getattr(response, "candidates", None) or []
        fragments: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text:
                    fragments.append(part_text)
        return "".join(fragments)

    @staticmethod
    def _usage_metadata(response: Any) -> dict[str, Any]:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return {}
        values: dict[str, Any] = {}
        for name in (
            "prompt_token_count",
            "candidates_token_count",
            "total_token_count",
            "cached_content_token_count",
            "thoughts_token_count",
        ):
            value = getattr(metadata, name, None)
            if value is not None:
                values[name] = int(value) if isinstance(value, (int, float)) else str(value)
        return values

    def _generation_config(self, types: Any) -> Any:
        """Build the request config using the current google-genai SDK API."""

        # google-genai 1.75.0 exposes thinking through GenerateContentConfig's
        # thinking_config field and ThinkingConfig's thinking_level field.
        thinking_level = types.ThinkingLevel(self.thinking_level)
        return types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=self.max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
        )

    def _image_part(self, types: Any, image_bytes: bytes) -> Any:
        """Build an inline image part with the requested tokenization quality."""

        # ULTRA_HIGH is a PartMediaResolutionLevel in google-genai. It is not
        # a member of the SDK's top-level MediaResolution enum, so the value
        # belongs on Part.from_bytes rather than GenerateContentConfig.
        resolution_type = getattr(types, "PartMediaResolutionLevel", None)
        if resolution_type is None:
            raise VertexDependencyError(
                "The installed google-genai SDK lacks PartMediaResolutionLevel. "
                "Install the current tools/vertex-ocr/requirements.txt dependencies."
            )
        media_resolution = resolution_type(f"MEDIA_RESOLUTION_{self.media_resolution}")
        return types.Part.from_bytes(
            data=image_bytes,
            mime_type="image/png",
            media_resolution=media_resolution,
        )

    def transcribe(self, image_path: Path, prompt: str) -> OCRResult:
        """Send one rendered PNG to Gemini on Vertex AI."""

        try:
            from google.genai import types
        except ImportError as exc:
            raise VertexDependencyError(
                "google-genai is not installed. Install tools/vertex-ocr/requirements.txt."
            ) from exc

        image_bytes = image_path.read_bytes()
        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=[
                prompt,
                self._image_part(types, image_bytes),
            ],
            config=self._generation_config(types),
        )
        text = self._response_text(response)
        if not text.strip():
            raise RuntimeError("Vertex returned no text for the rendered page")
        return OCRResult(
            text=text,
            usage=self._usage_metadata(response),
            response_id=getattr(response, "response_id", None),
            model_version=getattr(response, "model_version", None),
        )

    def close(self) -> None:
        """Close all clients created by worker threads."""

        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            close = getattr(client, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass
