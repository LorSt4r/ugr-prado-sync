"""
Google Calendar Direct REST API Exporter for PradoOS.

Synchronizes PRADO UGR deadlines and exam milestones directly to Google Calendar
using pure standard library HTTP (no heavy external dependencies required).
Supports token auto-discovery, zero-config refresh via OAuth2, and tiered popup reminders:
- Exams: 3 days (4320m), 1 day (1440m), 2 hours (120m)
- Assignments/Deliveries: 2 days (2880m), 1 day (1440m), 3 hours (180m)
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from prado.core.downloader import DeadlineItem
from prado.exporters.dashboard import classify_deadline_type


DEFAULT_TOKEN_SEARCH_PATHS = [
    Path.home() / ".config" / "prado" / "gcalendar_token.json",
    Path.home() / ".gemini" / "antigravity" / "plugin_data" / "gcalendar" / "token.json",
]


class GoogleCalendarSync:
    """Synchronizes deadlines and milestones with Google Calendar via v3 REST API."""

    def __init__(self, token_file: Optional[Path | str] = None, calendar_id: str = "auto"):
        self.token_file = self.resolve_token_file(token_file)
        self.calendar_id = calendar_id

    @staticmethod
    def resolve_token_file(custom_path: Optional[Path | str] = None) -> Optional[Path]:
        if custom_path:
            p = Path(custom_path).expanduser()
            return p if p.exists() else None
        for p in DEFAULT_TOKEN_SEARCH_PATHS:
            if p.exists():
                return p
        return None

    def get_access_token(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Loads and refreshes OAuth2 token using standard library urllib.
        Returns (access_token, error_message).
        """
        if not self.token_file or not self.token_file.exists():
            return None, (
                f"Google Calendar token not found. Place your token JSON in "
                f"~/.config/prado/gcalendar_token.json or pass --token-file."
            )

        try:
            with open(self.token_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return None, f"Failed to read token file {self.token_file}: {e}"

        token_info = data.get("token", {}) if "token" in data else data
        access_token = token_info.get("access_token")
        expiry_str = token_info.get("expiry")
        refresh_token = token_info.get("refresh_token") or data.get("refresh_token")
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")

        now = datetime.datetime.now(datetime.timezone.utc)
        is_expired = False

        if expiry_str:
            try:
                clean_str = expiry_str.replace("Z", "+00:00")
                exp = datetime.datetime.fromisoformat(clean_str)
                if now >= exp - datetime.timedelta(seconds=90):
                    is_expired = True
            except Exception:
                is_expired = True
        elif not access_token:
            is_expired = True

        if is_expired and refresh_token and client_id:
            try:
                body = urllib.parse.urlencode({
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token"
                }).encode("utf-8")
                req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    new_token_resp = json.loads(resp.read().decode("utf-8"))
                    access_token = new_token_resp.get("access_token")
                    token_info["access_token"] = access_token
                    expires_in = new_token_resp.get("expires_in", 3600)
                    new_exp = now + datetime.timedelta(seconds=expires_in)
                    token_info["expiry"] = new_exp.isoformat()
                    if "token" in data:
                        data["token"] = token_info
                    else:
                        data.update(token_info)

                    # Update token file safely if writable
                    try:
                        with open(self.token_file, "w", encoding="utf-8") as out_f:
                            json.dump(data, out_f, indent=2)
                    except OSError:
                        pass
            except Exception as e:
                return None, f"Failed to refresh OAuth2 token: {e}"

        if not access_token:
            return None, "No valid access_token found in token file."

        return access_token, None

    def api_request(
        self,
        access_token: str,
        path: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        target_cal_id: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        cal_id = target_cal_id or self.calendar_id
        if cal_id == "auto":
            cal_id = "primary"
        url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(cal_id)}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "PradoOS-Sync/1.0"
        }
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8")
                return (json.loads(content) if content else {}), None
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            return None, f"HTTP {e.code}: {err_msg}"
        except Exception as e:
            return None, str(e)

    def resolve_target_calendar_id(self, access_token: str) -> str:
        """Finds university calendar if set to auto, or returns configured id."""
        if self.calendar_id and self.calendar_id != "auto":
            return self.calendar_id

        # Query user calendars
        url = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                # 1. Search for ETSIIT or PRADO
                for cal in items:
                    summary = (cal.get("summary") or "").lower()
                    if any(k in summary for k in ("etsiit", "prado", "ugr", "universidad")):
                        return cal.get("id", "primary")
        except Exception:
            pass
        return "primary"

    def sync_deadlines(
        self,
        deadlines: List[DeadlineItem],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Synchronizes deadline items into Google Calendar."""
        access_token, err = self.get_access_token()
        if not access_token:
            return {"status": "error", "error": err, "created": 0, "skipped": 0, "total": len(deadlines)}

        target_cal_id = self.resolve_target_calendar_id(access_token)

        # 1. Fetch existing calendar events
        existing_events = []
        page_token = None
        for _ in range(5):
            path = "events?maxResults=250"
            if page_token:
                path += f"&pageToken={page_token}"
            data, req_err = self.api_request(access_token, path, target_cal_id=target_cal_id)
            if req_err or not data:
                break
            existing_events.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        # Index existing events by summary & date
        existing_keys = set()
        for ev in existing_events:
            summary = ev.get("summary", "")
            start_date = ev.get("start", {}).get("dateTime", "")[:10]
            existing_keys.add((summary, start_date))

        created_count = 0
        skipped_count = 0
        created_items = []

        for item in deadlines:
            is_exam = str(classify_deadline_type(item.title)).lower() in ("exam", "examen")
            tag = "🚨 [EXAMEN PRADO]" if is_exam else "💻 [ENTREGA PRADO]"
            summary = f"{tag} {item.course}: {item.title}"
            start_str = item.due_date.isoformat()
            date_key = start_str[:10]

            if (summary, date_key) in existing_keys:
                skipped_count += 1
                continue

            end_dt = item.due_date + datetime.timedelta(minutes=30)
            end_str = end_dt.isoformat()

            # Tiered reminder overrides
            if is_exam:
                reminders_overrides = [
                    {"method": "popup", "minutes": 4320},  # 3 days
                    {"method": "popup", "minutes": 1440},  # 1 day
                    {"method": "popup", "minutes": 120},   # 2 hours
                ]
            else:
                reminders_overrides = [
                    {"method": "popup", "minutes": 2880},  # 2 days
                    {"method": "popup", "minutes": 1440},  # 1 day
                    {"method": "popup", "minutes": 180},   # 3 hours
                ]

            event_body = {
                "summary": summary,
                "description": (
                    f"Asignatura: {item.course}\n"
                    f"Actividad: {item.title}\n"
                    f"Plataforma: PRADO UGR\n"
                    f"Enlace directo: {item.url or 'https://pradogrado.ugr.es'}\n\n"
                    f"Sincronizado automáticamente mediante PradoOS (ugr-prado-sync)."
                ),
                "start": {"dateTime": start_str},
                "end": {"dateTime": end_str},
                "reminders": {
                    "useDefault": False,
                    "overrides": reminders_overrides
                },
                "extendedProperties": {
                    "private": {
                        "prado_sync": "true",
                        "item_id": str(item.id),
                        "course": str(item.course)
                    }
                }
            }

            if dry_run:
                created_count += 1
                created_items.append({"summary": summary, "start": start_str, "dry_run": True})
                continue

            res, post_err = self.api_request(
                access_token=access_token,
                path="events",
                method="POST",
                data=event_body,
                target_cal_id=target_cal_id
            )
            if res and not post_err:
                created_count += 1
                existing_keys.add((summary, date_key))
                created_items.append({"summary": summary, "id": res.get("id"), "start": start_str})
            else:
                # Log error or continue
                pass

        return {
            "status": "success",
            "calendar_id": target_cal_id,
            "created": created_count,
            "skipped": skipped_count,
            "total_deadlines": len(deadlines),
            "events": created_items
        }


def load_deadlines_from_ics(ics_path: Path) -> List[DeadlineItem]:
    """Parses events from deadlines.ics into a list of DeadlineItem."""
    if not ics_path.exists():
        return []
    items: List[DeadlineItem] = []
    content = ics_path.read_text(encoding="utf-8", errors="replace")
    # RFC 5545 unfold: replace CRLF followed by space or tab
    unfolded = re.sub(r"\r?\n[ \t]", "", content)
    events = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.DOTALL)
    for ev in events:
        summary_m = re.search(r"SUMMARY:(.*)", ev)
        dtstart_m = re.search(r"DTSTART(?:;[^:]+)?:(\d{8}T\d{6}Z?)", ev)
        url_m = re.search(r"DESCRIPTION:.*?(https?://\S+)", ev)
        uid_m = re.search(r"UID:(.*)", ev)

        if summary_m and dtstart_m:
            raw_summary = summary_m.group(1).strip()
            summary = raw_summary.replace(r"\,", ",").replace(r"\;", ";").replace(r"\\", "\\")
            raw_dt = dtstart_m.group(1).strip()
            try:
                if raw_dt.endswith("Z"):
                    dt = datetime.datetime.strptime(raw_dt, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
                else:
                    dt = datetime.datetime.strptime(raw_dt, "%Y%m%dT%H%M%S")
            except ValueError:
                continue

            course = "PRADO"
            title = summary
            if summary.startswith("[") and "]" in summary:
                course = summary[1:summary.index("]")].strip()
                title = summary[summary.index("]") + 1:].strip()

            items.append(
                DeadlineItem(
                    id=uid_m.group(1).strip() if uid_m else summary,
                    title=title,
                    course=course,
                    due_date=dt,
                    url=url_m.group(1).strip() if url_m else "",
                )
            )
    return items

