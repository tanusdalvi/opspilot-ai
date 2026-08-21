"""Thin wrapper around the official Google GenAI (Gemini) Python SDK.

All Gemini SDK usage in OpsPilot AI is funneled through
:class:`GeminiNarratorClient` so no other module touches the SDK
directly. The client:

* reads ``GEMINI_API_KEY`` from the environment via
  ``core.config.get_gemini_api_key`` (never hard-coded, never logged),
* raises the project's :class:`ConfigurationError` when no key exists,
* requests JSON output at ``temperature=0`` for deterministic settings,
* returns plain response text for the investigator to validate.

Tests never use this class against the network; they inject fake clients
that expose the same single public method ``generate_json(prompt) -> str``.
"""

from __future__ import annotations

from core.config import get_gemini_api_key
from core.exceptions import AgentError, ConfigurationError

DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"


class GeminiNarratorClient:
    """Minimal Gemini client exposing one method: ``generate_json``.

    Args:
        api_key: Explicit API key; when ``None``, falls back to the
            environment configuration. An empty or missing key raises
            :class:`ConfigurationError` before any SDK import/use.
        model: Gemini model identifier used for generation.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_GEMINI_MODEL) -> None:
        resolved = api_key.strip() if isinstance(api_key, str) else api_key
        if not resolved:
            resolved = get_gemini_api_key()
        if not resolved:
            raise ConfigurationError(
                "Gemini API key is not configured; set the GEMINI_API_KEY "
                "environment variable (see .env.example) or pass an "
                "injectable client to investigate()."
            )
        self._model = model
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ConfigurationError(
                "The google-genai package is not installed; run "
                "'pip install -r requirements.txt'."
            ) from exc
        self._client = genai.Client(api_key=resolved)
        self._config_factory = genai_types.GenerateContentConfig

    def generate_json(self, prompt: str) -> str:
        """Send ``prompt`` to Gemini and return its raw text response.

        Generation uses ``temperature=0`` and a JSON response mime type.

        Raises:
            AgentError: When the call fails or Gemini returns no text.
                Error details never include the API key.
        """
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=self._config_factory(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:
            raise AgentError(f"Gemini generation failed: {type(exc).__name__}") from exc
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise AgentError("Gemini returned an empty response")
        return text
