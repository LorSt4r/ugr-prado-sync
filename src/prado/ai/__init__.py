"""
Pluggable BYO-AI Layer for PradoOS.

Provides:
- 100% Free & Deterministic rule-based fallback by default
- Local Ollama integration
- External OpenAI / DeepSeek / Gemini compatible completions
- Factory function get_ai_provider()
"""

from __future__ import annotations

from typing import Optional

from prado.ai.base import (
    AIConfig,
    AIProvider,
    DailyStudyPlan,
    ForumSummary,
    StudyBlock,
    StudyPlan,
)
from prado.ai.deterministic import DeterministicFallbackProvider
from prado.ai.external import ExternalAIProvider
from prado.ai.ollama import OllamaProvider


def get_ai_provider(config: Optional[AIConfig] = None) -> AIProvider:
    """
    Factory creating configured AIProvider with guaranteed deterministic fallback.
    Free by default if no configuration or key is provided.
    """
    if config is None or not config.enabled or config.provider == "none":
        return DeterministicFallbackProvider()

    if config.provider == "ollama":
        provider = OllamaProvider(
            base_url=config.base_url or "http://localhost:11434",
            model=config.model or "llama3.2",
            timeout_seconds=config.timeout_seconds,
        )
        if provider.is_available():
            return provider
        return DeterministicFallbackProvider()

    if config.provider in ("openai", "deepseek", "gemini", "custom"):
        if not config.api_key:
            return DeterministicFallbackProvider()
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        }
        target_url = config.base_url or base_urls.get(config.provider, "https://api.openai.com/v1")
        return ExternalAIProvider(
            api_key=config.api_key,
            base_url=target_url,
            model=config.model or "gpt-4o-mini",
            timeout_seconds=config.timeout_seconds,
        )

    return DeterministicFallbackProvider()


__all__ = [
    "AIConfig",
    "AIProvider",
    "DailyStudyPlan",
    "DeterministicFallbackProvider",
    "ExternalAIProvider",
    "ForumSummary",
    "OllamaProvider",
    "StudyBlock",
    "StudyPlan",
    "get_ai_provider",
]
