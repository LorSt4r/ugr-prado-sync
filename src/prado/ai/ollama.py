"""
Local Ollama Integration for PradoOS AI Layer.

Connects to local Ollama daemon (default: http://localhost:11434/api/generate)
with automatic fallback to deterministic provider when daemon is offline.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

import requests

from prado.ai.base import AIProvider, ForumSummary, StudyPlan
from prado.ai.deterministic import DeterministicFallbackProvider
from prado.core.downloader import DeadlineItem, ForumPost
from prado.exceptions import PradoError


class OllamaProvider(AIProvider):
    """Local Ollama client connecting to /api/generate."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout_seconds: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._fallback = DeterministicFallbackProvider()

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or "",
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except requests.RequestException as e:
            raise PradoError(f"Ollama generation failed: {e}") from e

    def summarize_forum_post(self, post: ForumPost) -> ForumSummary:
        if not self.is_available():
            return self._fallback.summarize_forum_post(post)

        sys_prompt = (
            "You are an academic assistant. Summarize this Moodle forum post in 2 concise sentences, "
            "extract key dates and action items."
        )
        user_prompt = f"Subject: {post.subject}\nAuthor: {post.author}\nContent: {post.content}"
        try:
            summary_text = self.generate(user_prompt, system_prompt=sys_prompt, max_tokens=300)
            fallback_res = self._fallback.summarize_forum_post(post)
            fallback_res.executive_summary = summary_text
            fallback_res.is_ai_generated = True
            return fallback_res
        except Exception:
            return self._fallback.summarize_forum_post(post)

    def generate_study_plan(
        self,
        deadlines: List[DeadlineItem],
        horizon_days: int = 7,
        start_date: Optional[datetime.date] = None,
    ) -> StudyPlan:
        base_plan = self._fallback.generate_study_plan(deadlines, horizon_days, start_date)
        if not self.is_available():
            return base_plan

        prompt = (
            f"Given these {len(deadlines)} upcoming academic deadlines: "
            f"{[d.title + ' due ' + d.due_date.isoformat() for d in deadlines]}, "
            f"write a 2-sentence encouraging motivational coaching tip."
        )
        try:
            tip = self.generate(prompt, max_tokens=150)
            base_plan.notes = tip
            base_plan.is_ai_generated = True
        except Exception:
            pass
        return base_plan
