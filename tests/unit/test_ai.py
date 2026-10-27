"""
Unit tests for PradoOS Pluggable BYO-AI Layer.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock
import pytest
import requests

from prado.ai import (
    AIConfig,
    DeterministicFallbackProvider,
    ExternalAIProvider,
    OllamaProvider,
    get_ai_provider,
)
from prado.core.downloader import DeadlineItem, ForumPost


def test_deterministic_availability():
    provider = DeterministicFallbackProvider()
    assert provider.is_available() is True
    # Test text truncation/cleaning
    res = provider.generate("   Multiple   spaces   in   prompt   ", max_tokens=10)
    assert res == "Multiple s"


def test_deterministic_forum_summary():
    provider = DeterministicFallbackProvider()
    post = ForumPost(
        forum_id="MC",
        subject="Aviso de Evaluación",
        author="Profesor",
        content="Atención alumnos: examen parcial el día 30/10 en el aula 0.12. Entrega obligatoria de fichas antes de las 14:00.",
    )
    summary = provider.summarize_forum_post(post)

    assert summary.forum_id == "MC"
    assert summary.urgency == "urgent"
    assert "30/10" in summary.key_dates
    assert summary.is_ai_generated is False
    assert len(summary.executive_summary) > 0


def test_deterministic_study_plan():
    provider = DeterministicFallbackProvider()
    base_date = datetime.date(2026, 10, 27)
    deadlines = [
        DeadlineItem(
            id="1",
            title="Práctica 1",
            course="SO",
            due_date=datetime.datetime(2026, 10, 29, 23, 59),  # 2 days away
            url="",
        ),
        DeadlineItem(
            id="2",
            title="Práctica 2",
            course="ED",
            due_date=datetime.datetime(2026, 11, 1, 23, 59),  # 5 days away
            url="",
        ),
        DeadlineItem(
            id="3",
            title="Examen Final",
            course="MC",
            due_date=datetime.datetime(2026, 11, 8, 9, 30),  # 12 days away
            url="",
        ),
    ]

    plan = provider.generate_study_plan(deadlines, horizon_days=7, start_date=base_date)

    assert plan.horizon_days == 7
    assert plan.is_ai_generated is False
    assert len(plan.days) == 7

    day0 = plan.days[0]
    assert day0.date == base_date
    assert day0.to_dict()["date"] == "2026-10-27"
    # Day 0 should contain High priority (SO in 2 days) and Medium priority (ED in 5 days)
    priorities = [b.priority for b in day0.blocks]
    assert "high" in priorities
    assert "medium" in priorities
    assert day0.total_hours > 0.0


def test_ollama_provider_success(monkeypatch):
    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.2")

    def mock_get(url, timeout):
        resp = MagicMock()
        resp.status_code = 200
        return resp

    def mock_post(url, json, timeout):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"response": "AI generated concise summary of the notice."}
        return resp

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr(requests, "post", mock_post)

    assert provider.is_available() is True
    post = ForumPost(forum_id="TIC", subject="Lab 3", author="Prof", content="Long content here.")
    summary = provider.summarize_forum_post(post)

    assert summary.is_ai_generated is True
    assert summary.executive_summary == "AI generated concise summary of the notice."


def test_ollama_offline_fallback(monkeypatch):
    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.2")

    def mock_get_fail(url, timeout):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr(requests, "get", mock_get_fail)

    assert provider.is_available() is False
    post = ForumPost(forum_id="TIC", subject="Lab 3", author="Prof", content="Notice content.")
    summary = provider.summarize_forum_post(post)

    assert summary.is_ai_generated is False
    assert "Notice content." in summary.executive_summary


def test_external_provider_openai(monkeypatch):
    provider = ExternalAIProvider(
        api_key="sk-testkey123456",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    assert provider.is_available() is True

    captured_headers = {}

    def mock_post(url, headers, json, timeout):
        captured_headers.update(headers)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": "External AI study recommendation"}}]
        }
        return resp

    monkeypatch.setattr(requests, "post", mock_post)

    res = provider.generate("Give me advice")
    assert res == "External AI study recommendation"
    assert captured_headers["Authorization"] == "Bearer sk-testkey123456"


def test_ai_factory_default():
    # When None or enabled=False, returns DeterministicFallbackProvider
    p1 = get_ai_provider(None)
    assert isinstance(p1, DeterministicFallbackProvider)

    p2 = get_ai_provider(AIConfig(enabled=False))
    assert isinstance(p2, DeterministicFallbackProvider)

    # When Ollama is offline, returns fallback
    p3 = get_ai_provider(AIConfig(enabled=True, provider="ollama", base_url="http://nonexistent:9999"))
    assert isinstance(p3, DeterministicFallbackProvider)

    # When OpenAI without API key, returns fallback
    p4 = get_ai_provider(AIConfig(enabled=True, provider="openai", api_key=None))
    assert isinstance(p4, DeterministicFallbackProvider)

    # When OpenAI with API key, returns ExternalAIProvider
    p5 = get_ai_provider(AIConfig(enabled=True, provider="openai", api_key="sk-test"))
    assert isinstance(p5, ExternalAIProvider)
