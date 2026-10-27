"""
Abstract Base Layer & DTOs for Pluggable BYO-AI in PradoOS.

Supports:
- Abstract contract for LLM generation, forum summarization, and study plan synthesis
- Structured DTOs (ForumSummary, StudyBlock, DailyStudyPlan, StudyPlan)
- AI configuration dataclass
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime
from typing import Any, Dict, List, Optional

from prado.core.downloader import DeadlineItem, ForumPost


@dataclass
class AIConfig:
    """Configuration for pluggable BYO-AI providers."""
    enabled: bool = False
    provider: str = "none"  # "none", "ollama", "openai", "deepseek", "gemini", "custom"
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 1000
    timeout_seconds: float = 30.0


@dataclass
class ForumSummary:
    """Structured extraction of key items from forum announcements."""
    forum_id: str
    subject: str
    author: str
    executive_summary: str
    key_dates: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    urgency: str = "normal"  # "low", "normal", "urgent"
    is_ai_generated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forum_id": self.forum_id,
            "subject": self.subject,
            "author": self.author,
            "executive_summary": self.executive_summary,
            "key_dates": self.key_dates,
            "action_items": self.action_items,
            "urgency": self.urgency,
            "is_ai_generated": self.is_ai_generated,
        }


@dataclass
class StudyBlock:
    """An individual study block assigned to a specific course and task."""
    course: str
    task: str
    priority: str  # "high", "medium", "low"
    estimated_hours: float
    deadline_countdown_days: Optional[int] = None
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "course": self.course,
            "task": self.task,
            "priority": self.priority,
            "estimated_hours": self.estimated_hours,
            "deadline_countdown_days": self.deadline_countdown_days,
            "rationale": self.rationale,
        }


@dataclass
class DailyStudyPlan:
    """Study blocks scheduled for a single calendar day."""
    date: datetime.date
    blocks: List[StudyBlock] = field(default_factory=list)
    total_hours: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "blocks": [b.to_dict() for b in self.blocks],
            "total_hours": self.total_hours,
        }


@dataclass
class StudyPlan:
    """Full multi-day study schedule generated from upcoming deadlines."""
    generated_at: datetime.datetime
    horizon_days: int
    days: List[DailyStudyPlan] = field(default_factory=list)
    is_ai_generated: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "horizon_days": self.horizon_days,
            "days": [d.to_dict() for d in self.days],
            "is_ai_generated": self.is_ai_generated,
            "notes": self.notes,
        }


class AIProvider(ABC):
    """Abstract base class for all pluggable AI providers in PradoOS."""

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if the provider endpoint is reachable and configured."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> str:
        """Generates raw text completion from the provider."""
        pass

    @abstractmethod
    def summarize_forum_post(self, post: ForumPost) -> ForumSummary:
        """Summarizes forum announcements into structured findings."""
        pass

    @abstractmethod
    def generate_study_plan(
        self,
        deadlines: List[DeadlineItem],
        horizon_days: int = 7,
        start_date: Optional[datetime.date] = None,
    ) -> StudyPlan:
        """Generates actionable daily study schedule based on deadlines."""
        pass
