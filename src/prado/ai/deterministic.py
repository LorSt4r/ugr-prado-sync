"""
Deterministic Rule-Based Fallback Provider for PradoOS AI Layer.

Operates 100% offline, free, and deterministically without external models or API tokens.
Extracts dates, urgency tags, and synthesizes deadline-driven study schedules using pure logic.
"""

from __future__ import annotations

import datetime
import re
from typing import List, Optional

from prado.ai.base import (
    AIProvider,
    DailyStudyPlan,
    ForumSummary,
    StudyBlock,
    StudyPlan,
)
from prado.core.downloader import DeadlineItem, ForumPost


class DeterministicFallbackProvider(AIProvider):
    """
    100% Free, deterministic, offline academic intelligence layer.
    Requires ZERO API keys, tokens, or network connectivity.
    """

    URGENT_KEYWORDS = {
        "urgente",
        "examen",
        "prueba",
        "evaluación",
        "parcial",
        "plazo",
        "entrega",
        "práctica",
        "obligatorio",
        "deadline",
        "urgent",
        "submission",
    }

    DATE_REGEX = re.compile(
        r"\b(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{1,2}\s+de\s+[a-zA-Z]+(?:\s+de\s+\d{4})?)\b",
        re.IGNORECASE,
    )

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> str:
        clean = " ".join(prompt.split())
        return clean[:max_tokens] if len(clean) > max_tokens else clean

    def summarize_forum_post(self, post: ForumPost) -> ForumSummary:
        combined_text = f"{post.subject} {post.content}".lower()

        # Urgency keyword detection
        urgency = "normal"
        if any(kw in combined_text for kw in self.URGENT_KEYWORDS):
            urgency = "urgent"

        # Regex key dates detection
        dates = self.DATE_REGEX.findall(post.content)

        # Action items extraction
        action_items: List[str] = []
        for line in post.content.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith(("-", "*", "•")) or any(
                kw in line_str.lower() for kw in self.URGENT_KEYWORDS
            ):
                action_items.append(line_str.lstrip("-*• "))

        # Executive summary: take first 2 non-empty sentences
        # Strip HTML tags first
        text_without_html = re.sub(r"<[^>]+>", " ", post.content)
        cleaned_content = " ".join(text_without_html.split())
        sentences = re.split(r"(?<=[.!?])\s+", cleaned_content)
        summary_sentences = [s.strip() for s in sentences if s.strip()][:2]
        exec_summary = " ".join(summary_sentences) or post.subject

        return ForumSummary(
            forum_id=post.forum_id,
            subject=post.subject,
            author=post.author,
            executive_summary=exec_summary,
            key_dates=list(dict.fromkeys(dates)),
            action_items=action_items[:5],
            urgency=urgency,
            is_ai_generated=False,
        )

    def generate_study_plan(
        self,
        deadlines: List[DeadlineItem],
        horizon_days: int = 7,
        start_date: Optional[datetime.date] = None,
    ) -> StudyPlan:
        start = start_date or datetime.date.today()
        sorted_deadlines = sorted(deadlines, key=lambda d: d.due_date)

        days_list: List[DailyStudyPlan] = []
        for day_offset in range(horizon_days):
            current_day = start + datetime.timedelta(days=day_offset)
            blocks: List[StudyBlock] = []

            for d in sorted_deadlines:
                due_day = d.due_date.date()
                delta_days = (due_day - current_day).days

                if delta_days < 0:
                    continue  # Already passed

                if delta_days <= 3:
                    blocks.append(
                        StudyBlock(
                            course=d.course,
                            task=f"Intensive Sprint: {d.title}",
                            priority="high",
                            estimated_hours=2.5,
                            deadline_countdown_days=delta_days,
                            rationale=f"Due in {delta_days} day(s) on {due_day.strftime('%d/%m')}",
                        )
                    )
                elif delta_days <= 7:
                    blocks.append(
                        StudyBlock(
                            course=d.course,
                            task=f"Core Work: {d.title}",
                            priority="medium",
                            estimated_hours=1.5,
                            deadline_countdown_days=delta_days,
                            rationale=f"Approaching deadline in {delta_days} days",
                        )
                    )
                elif delta_days <= 14 and day_offset in (0, 3, 6):
                    blocks.append(
                        StudyBlock(
                            course=d.course,
                            task=f"Preparation: {d.title}",
                            priority="low",
                            estimated_hours=1.0,
                            deadline_countdown_days=delta_days,
                            rationale="Long-term preparation",
                        )
                    )

            total_h = sum(b.estimated_hours for b in blocks)
            days_list.append(DailyStudyPlan(date=current_day, blocks=blocks, total_hours=total_h))

        return StudyPlan(
            generated_at=datetime.datetime.now(),
            horizon_days=horizon_days,
            days=days_list,
            is_ai_generated=False,
            notes="Algorithmic deadline-driven study plan (deterministic, zero token cost).",
        )
