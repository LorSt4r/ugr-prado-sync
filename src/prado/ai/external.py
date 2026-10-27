"""
External API Provider for OpenAI / DeepSeek / Gemini / Groq Compatible Endpoints.

Interacts via standard /v1/chat/completions REST endpoint with Bearer authentication.
Gracefully degrades to deterministic rule-based intelligence upon missing keys or network errors.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

import requests

from prado.ai.base import AIProvider, ForumSummary, StudyPlan
from prado.ai.deterministic import DeterministicFallbackProvider
from prado.core.downloader import DeadlineItem, ForumPost
from prado.exceptions import PradoError


class ExternalAIProvider(AIProvider):
    """External API client for OpenAI, DeepSeek, Gemini, and compatible endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._fallback = DeterministicFallbackProvider()

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, IndexError) as e:
            raise PradoError(f"External AI generation failed: {e}") from e

    def summarize_forum_post(self, post: ForumPost) -> ForumSummary:
        if not self.is_available():
            return self._fallback.summarize_forum_post(post)

        sys_prompt = "You are an academic assistant. Summarize this forum notice in 2 concise sentences."
        try:
            summary = self.generate(post.content, system_prompt=sys_prompt, max_tokens=250)
            res = self._fallback.summarize_forum_post(post)
            res.executive_summary = summary
            res.is_ai_generated = True
            return res
        except Exception:
            return self._fallback.summarize_forum_post(post)

    def generate_study_plan(
        self,
        deadlines: List[DeadlineItem],
        horizon_days: int = 7,
        start_date: Optional[datetime.date] = None,
    ) -> StudyPlan:
        plan = self._fallback.generate_study_plan(deadlines, horizon_days, start_date)
        if not self.is_available():
            return plan
        try:
            tip = self.generate(
                f"Provide a 1-sentence productivity tip for {len(deadlines)} academic deadlines.",
                max_tokens=100,
            )
            plan.notes = tip
            plan.is_ai_generated = True
        except Exception:
            pass
        return plan
