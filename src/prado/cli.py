"""
Unified Command-Line Interface (`prado`) for PradoOS.

Provides subcommands:
  - prado onboard   : 2-Phase progressive disclosure setup wizard
  - prado auth      : SAML SSO login, logout, and session status
  - prado discover  : Auto-discover enrolled Moodle / PRADO courses
  - prado courses   : List, enable, disable courses, or change routing preset
  - prado sync      : Synchronize course materials, deadlines, and exporters
  - prado doctor    : 9-probe health diagnostic and self-repair engine
  - prado daemon    : Cross-platform background scheduler (launchd/systemd/schtasks)
  - prado star      : Star PradoOS on GitHub via `gh` CLI or browser

Every command supports `--help` and `--json` with deterministic exit codes:
  - 0 : Success
  - 1 : General Error
  - 2 : MFA Verification Code Required (Tier 3 non-interactive / agent protocol)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence

import requests

from prado import __version__
from prado.auth.credentials import CredentialStore, prompt_gui_input
from prado.auth.mfa import MfaResolver
from prado.auth.saml import UgrSamlDriver
from prado.auth.session import MoodleSessionManager
from prado.config import (
    PradoConfig,
    ensure_secure_dir,
    get_config_dir,
    get_config_file,
    get_session_file,
    get_state_db_path,
    load_config,
    save_config,
)
from prado.core.adoption import AdoptionScanner
from prado.core.discovery import Course, CourseDiscovery, CourseFilter
from prado.core.downloader import (
    AdoptedFile,
    ConflictFile,
    DeadlineItem,
    DownloadedFile,
    DownloadStatus,
    ForumPost,
    SafeDownloader,
    SyncSummary,
)
from prado.core.overwrite import CollisionQuadrant, OverwriteGuard
from prado.core.parser import CourseActivity, CourseHtmlParser, FileAttachment
from prado.core.router import CourseRouter
from prado.exceptions import (
    AuthenticationRequiredError,
    ConfigError,
    InvalidCredentialsError,
    MfaRequiredError,
    PradoError,
)
from prado.exporters.calendar import export_calendar
from prado.exporters.changelog import export_changelog
from prado.exporters.dashboard import export_dashboard
from prado.onboarding.star import execute_star, maybe_prompt_star_after_sync
from prado.onboarding.wizard import OnboardingWizard
from prado.scheduler.daemon import DaemonManager
from prado.scheduler.doctor import DoctorEngine, ProbeStatus
from prado.state import CourseRecord, FileRecord, StateDatabase


def _emit_json(payload: Dict[str, Any]) -> None:
    """Prints formatted JSON payload to stdout."""
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def normalize_ugr_username(username: Optional[str], moodle_url: str = "") -> Optional[str]:
    """
    Normalizes UGR institutional usernames: if a student enters only the local part
    (e.g. 'lorenzovasile') for a '*.ugr.es' Moodle instance, automatically appends '@correo.ugr.es'.
    """
    if not username:
        return username
    clean = username.strip()
    if not clean:
        return None
    if "@" not in clean and ".ugr.es" in (moodle_url or "").lower():
        return f"{clean}@correo.ugr.es"
    return clean


def _obtain_authenticated_session(
    cfg: PradoConfig,
    mfa_code: Optional[str] = None,
    interactive: bool = True,
    json_mode: bool = False,
) -> requests.Session:
    """
    Returns an authenticated requests.Session using saved cookies if valid,
    or performs headless SAML login if credentials are stored in CredentialStore.
    """
    sess_mgr = MoodleSessionManager(base_url=cfg.moodle_url)
    if sess_mgr.load_session() and sess_mgr.is_session_valid(sess_mgr.session, cfg.moodle_url):
        return sess_mgr.session

    cred_store = CredentialStore()
    try:
        creds = cred_store.get_sso_credentials(cfg.username)
    except InvalidCredentialsError as e:
        raise AuthenticationRequiredError(
            "No valid session or stored credentials found. Run 'prado onboard' or 'prado auth login'."
        ) from e

    username, password = creds
    mfa_resolver = MfaResolver(
        mfa_config=cfg.mfa,
        interactive=interactive and not json_mode,
        json_mode=json_mode,
        agent_code=mfa_code,
    )
    driver = UgrSamlDriver(
        base_url=cfg.moodle_url,
        session_manager=sess_mgr,
        mfa_resolver=mfa_resolver,
        credential_store=cred_store,
    )
    return driver.login(username=username, password=password)


def _handle_onboard(args: argparse.Namespace, json_mode: bool) -> int:
    wizard = OnboardingWizard()
    subgroups: Optional[Dict[str, str]] = None
    if args.subgroups:
        subgroups = {}
        for pair in args.subgroups.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip() and v.strip():
                    subgroups[k.strip()] = v.strip()

    interactive = not args.no_interactive and not json_mode
    result = wizard.run_full_onboarding(
        username=args.username,
        password=args.password,
        moodle_url=args.url,
        courses_root=args.courses_root,
        preset=args.preset,
        semester=args.semester,
        subgroups=subgroups,
        imap_enabled=True if args.imap_enabled else None,
        imap_host=args.imap_host,
        imap_username=args.imap_username,
        imap_password=args.imap_password,
        install_daemon=args.install_daemon,
        interactive=interactive,
        json_mode=json_mode,
        prompt_star=not args.no_star,
    )

    if json_mode:
        _emit_json(result)
    else:
        print(f"\n✓ Onboarding complete! Configuration saved to {result['config_file']}")
        print(f"  Courses root : {result['courses_root']}")
        print(f"  Preset       : {result['preset']}")
    return 0


def _handle_auth(args: argparse.Namespace, json_mode: bool) -> int:
    cfg = load_config()
    base_url = args.url or cfg.moodle_url
    sess_mgr = MoodleSessionManager(base_url=base_url)
    cred_store = CredentialStore()

    action = args.auth_action or ("login" if (args.username or args.mfa_code) else "status")

    if action == "logout":
        sess_mgr.clear_session()
        if json_mode:
            _emit_json({"status": "success", "action": "logout", "message": "Session cleared."})
        else:
            print("✓ Logged out and cleared local session cookies.")
        return 0

    if action == "status":
        loaded = sess_mgr.load_session()
        tokens = sess_mgr.extract_mfa_tokens()
        try:
            creds = cred_store.get_sso_credentials(cfg.username)
        except InvalidCredentialsError:
            creds = None
        is_valid = False
        if loaded and not args.offline:
            is_valid = sess_mgr.is_session_valid(sess_mgr.session, base_url)

        payload = {
            "status": "success",
            "authenticated": is_valid,
            "session_cookies_present": loaded,
            "mfa_device_trust_tokens": len(tokens),
            "credentials_stored": creds is not None,
            "username": cfg.username,
            "moodle_url": base_url,
        }
        if json_mode:
            _emit_json(payload)
        else:
            state_str = "Authenticated" if is_valid else ("Cookies saved (unverified/expired)" if loaded else "Not logged in")
            print(f"Auth Status      : {state_str}")
            print(f"Moodle URL       : {base_url}")
            print(f"Username         : {cfg.username or '(not configured)'}")
            print(f"Credentials Saved: {'Yes' if creds else 'No'}")
            print(f"30d Trust Tokens : {len(tokens)}")
        return 0

    # action == "login"
    gui_mode = bool(getattr(args, "gui", False))
    username = args.username
    password = args.password

    # Only reuse stored credentials without prompting if NOT explicitly launching interactive --gui login
    # (or if --mfa-code is provided to complete a pending Tier 3 MFA challenge)
    if not gui_mode or args.mfa_code:
        username = username or cfg.username
        if not password and username:
            try:
                stored = cred_store.get_sso_credentials(username)
                username, password = stored
            except InvalidCredentialsError:
                pass

    if not username:
        if gui_mode:
            default_email = normalize_ugr_username(cfg.username, base_url) or ""
            username = prompt_gui_input(
                prompt="Enter your institutional UGR email (@correo.ugr.es):",
                title="PradoOS — UGR SSO Login",
                hidden=False,
                default=default_email,
            )
        elif not json_mode and not args.no_interactive and sys.stdin.isatty():
            username = input("Institutional Username / Email: ").strip()
        if not username:
            raise InvalidCredentialsError("Username is required for 'prado auth login'.")

    username = normalize_ugr_username(username, base_url) or username

    if not password:
        if gui_mode:
            password = prompt_gui_input(
                prompt=f"Enter password for {username} (saved securely in native OS Keychain):",
                title="PradoOS — UGR SSO Login",
                hidden=True,
            )
        elif not json_mode and not args.no_interactive and sys.stdin.isatty():
            import getpass
            password = getpass.getpass("Institutional Password: ")
        if not password:
            raise InvalidCredentialsError("Password is required for 'prado auth login'.")

    cred_store.set_sso_credentials(username, password)
    if cfg.username != username or (args.url and cfg.moodle_url != base_url):
        cfg.username = username
        cfg.moodle_url = base_url
        save_config(cfg)

    mfa_resolver = MfaResolver(
        mfa_config=cfg.mfa,
        interactive=not args.no_interactive and not json_mode,
        json_mode=json_mode,
        agent_code=args.mfa_code,
        gui_mode=gui_mode,
    )
    driver = UgrSamlDriver(
        base_url=base_url,
        session_manager=sess_mgr,
        mfa_resolver=mfa_resolver,
        credential_store=cred_store,
    )
    try:
        driver.login(username=username, password=password)
    except InvalidCredentialsError:
        # Purge invalid credentials from Keychain/Vault so subsequent attempts re-prompt cleanly
        cred_store.delete_sso_credentials(username)
        raise
    tokens = sess_mgr.extract_mfa_tokens()

    if json_mode:
        _emit_json({
            "status": "success",
            "action": "login",
            "authenticated": True,
            "username": username,
            "moodle_url": base_url,
            "mfa_device_trust_tokens": len(tokens),
        })
    else:
        print(f"✓ Successfully authenticated as {username} at {base_url}")
    return 0


def _handle_discover(args: argparse.Namespace, json_mode: bool) -> int:
    cfg = load_config()
    base_url = args.url or cfg.moodle_url
    session = _obtain_authenticated_session(
        cfg=cfg,
        interactive=not args.no_interactive,
        json_mode=json_mode,
    )

    discovery = CourseDiscovery(session=session, base_url=base_url)
    semester_filter = args.semester if args.semester is not None else cfg.sync.semester
    c_filter = CourseFilter(
        semester=None if args.all else semester_filter,
        active_only=not args.all,
        include_hidden=args.include_hidden or args.all,
        subgroup_map=cfg.sync.subgroups,
    )
    courses = discovery.discover_courses(course_filter=c_filter)

    state_db = StateDatabase()
    for c in courses:
        state_db.upsert_course(
            CourseRecord(
                course_id=c.id,
                fullname=c.fullname,
                shortname=c.shortname,
                idnumber=c.idnumber,
                category=c.coursecategory,
                is_active=1 if c.is_active else 0,
            )
        )

    if json_mode:
        _emit_json({
            "status": "success",
            "courses_count": len(courses),
            "courses": [c.to_dict() for c in courses],
        })
    else:
        print(f"Discovered {len(courses)} enrolled course(s) on {base_url}:")
        for c in courses:
            sem_label = f"S{c.semester}" if c.semester in (1, 2) else ("Annual" if c.semester == 0 else "-")
            sub_label = f" [Subgroup: {c.subgroup}]" if c.subgroup else ""
            print(f"  • [{c.id}] {c.slug:<10} ({sem_label}) — {c.fullname}{sub_label}")
    return 0


def _handle_courses(args: argparse.Namespace, json_mode: bool) -> int:
    cfg = load_config()
    state_db = StateDatabase()
    action = args.courses_action or "list"

    if action == "set-preset":
        preset = (args.target or "smart").lower()
        if preset not in ("smart", "mirror"):
            raise ConfigError("Preset must be either 'smart' or 'mirror'.")
        cfg.sync.preset = preset
        save_config(cfg)
        if json_mode:
            _emit_json({"status": "success", "preset": preset})
        else:
            print(f"✓ Folder routing preset updated to '{preset}'.")
        return 0

    if action in ("enable", "disable"):
        if not args.target:
            raise ConfigError(f"Course ID is required for 'prado courses {action}'.")
        try:
            cid = int(args.target)
        except ValueError as e:
            raise ConfigError(f"Course ID must be an integer, got '{args.target}'.") from e

        active_flag = action == "enable"
        existing = state_db.get_course(cid)
        if not existing:
            state_db.upsert_course(CourseRecord(course_id=cid, fullname=f"Course {cid}", is_active=1 if active_flag else 0))
        else:
            state_db.set_course_active(cid, active_flag)

        if json_mode:
            _emit_json({"status": "success", "course_id": cid, "is_active": active_flag})
        else:
            print(f"✓ Course {cid} {'enabled' if active_flag else 'disabled'}.")
        return 0

    # action == "list"
    records = state_db.list_all_courses()
    if json_mode:
        _emit_json({
            "status": "success",
            "preset": cfg.sync.preset,
            "courses_count": len(records),
            "courses": [
                {
                    "course_id": r.course_id,
                    "fullname": r.fullname,
                    "shortname": r.shortname,
                    "is_active": bool(r.is_active),
                    "last_synced_at": r.last_synced_at,
                }
                for r in records
            ],
        })
    else:
        print(f"Configured Courses (Routing Preset: {cfg.sync.preset}):")
        if not records:
            print("  No courses cached yet. Run 'prado discover' to scan your enrolled courses.")
        for r in records:
            mark = "✓" if r.is_active else "○"
            print(f"  [{mark}] {r.course_id}: {r.fullname}")
    return 0


def _sync_single_course(
    course: Course,
    session: requests.Session,
    cfg: PradoConfig,
    state_db: StateDatabase,
    router: CourseRouter,
    downloader: SafeDownloader,
    adoption_scanner: AdoptionScanner,
    overwrite_guard: OverwriteGuard,
    summary: SyncSummary,
    dry_run: bool = False,
    force: bool = False,
    planned_actions: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Fetches, parses, routes, and downloads/adopts materials for a single course."""
    base_url = cfg.moodle_url.rstrip("/")
    course_url = course.viewurl or f"{base_url}/course/view.php?id={course.id}"
    resp = session.get(course_url, timeout=20)
    if resp.status_code != 200:
        return

    parsed = CourseHtmlParser.parse_course_page(
        html_content=resp.text,
        course_id=str(course.id),
        base_url=base_url,
    )

    for activity in parsed.activities:
        # Enrich assignments, folders, and forums
        if activity.mod_type == "assign" and activity.url:
            try:
                a_resp = session.get(activity.url, timeout=15)
                if a_resp.status_code == 200:
                    CourseHtmlParser.parse_assignment_page(a_resp.text, activity, base_url=base_url)
            except requests.RequestException:
                pass
            if activity.due_date:
                summary.deadlines.append(
                    DeadlineItem(
                        id=activity.id,
                        title=activity.title,
                        course=course.slug or course.fullname,
                        due_date=activity.due_date,
                        url=activity.url,
                    )
                )

        elif activity.mod_type == "folder" and activity.url:
            try:
                f_resp = session.get(activity.url, timeout=15)
                if f_resp.status_code == 200:
                    CourseHtmlParser.parse_folder_page(f_resp.text, activity, base_url=base_url)
            except requests.RequestException:
                pass

        elif activity.mod_type == "forum" and activity.url:
            try:
                fo_resp = session.get(activity.url, timeout=15)
                if fo_resp.status_code == 200:
                    posts = CourseHtmlParser.parse_forum_announcements(
                        fo_resp.text, activity, base_url=base_url
                    )
                    for p in posts:
                        summary.forum_announcements.append(
                            ForumPost(
                                forum_id=str(p.get("forum_id", activity.id)),
                                subject=str(p.get("subject", "Announcement")),
                                author=str(p.get("author", "")),
                                content=str(p.get("content", "")),
                                url=p.get("url") or activity.url,
                            )
                        )
            except requests.RequestException:
                pass

        # Collect downloadable targets (either explicit attachments or a direct resource activity)
        targets: List[Optional[FileAttachment]] = []
        if activity.attachments:
            targets.extend(activity.attachments)
        elif activity.mod_type == "resource" and activity.url:
            targets.append(None)

        for attachment in targets:
            decision = router.route_activity(
                activity=activity,
                file=attachment,
                course_slug=course.slug,
            )
            if decision.action == "skip":
                continue

            rel_path_obj = Path(course.slug) / decision.target_rel_path
            rel_path_str = rel_path_obj.as_posix()
            dest_abs = cfg.courses_root / rel_path_obj
            download_url = (
                (attachment.download_url or attachment.url)
                if attachment is not None
                else activity.url
            )

            if dry_run:
                if planned_actions is not None:
                    planned_actions.append({
                        "course": course.slug,
                        "activity": activity.title,
                        "mod_type": activity.mod_type,
                        "relative_path": rel_path_str,
                        "action": decision.action,
                        "url": download_url,
                    })
                continue

            # If local file already exists and is tracked with no force flag, check if we can skip or adopt
            existing_rec = state_db.get_file(rel_path_str)
            if dest_abs.exists() and dest_abs.is_file() and not force:
                local_bytes = dest_abs.read_bytes()
                local_hash = hashlib.sha256(local_bytes).hexdigest()
                if existing_rec is None:
                    adopted_info = adoption_scanner.match_and_adopt(
                        rel_path=rel_path_str,
                        server_hash=local_hash,
                        course_id=course.id,
                        remote_url=download_url,
                    )
                    if adopted_info is not None:
                        summary.adopted_files.append(
                            AdoptedFile(
                                path=dest_abs,
                                sha256=adopted_info.sha256,
                                size_bytes=adopted_info.size,
                            )
                        )
                        continue
                else:
                    # Already tracked in state_db; preserve student edits
                    if local_hash != existing_rec.original_hash:
                        state_db.mark_modified(rel_path_str, True)
                        continue
                    continue

            # Download to temporary location or directly via SafeDownloader
            dl_res = downloader.download_file(url=download_url, dest_path=dest_abs)
            if dl_res.status == DownloadStatus.DOWNLOADED:
                state_db.upsert_file(
                    FileRecord(
                        path=rel_path_str,
                        course_id=course.id,
                        remote_url=download_url,
                        original_hash=dl_res.sha256,
                        current_hash=dl_res.sha256,
                        file_size=dl_res.size_bytes,
                        local_mtime=dl_res.dest_path.stat().st_mtime if dl_res.dest_path.exists() else None,
                        last_synced_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    )
                )
                summary.downloaded_files.append(
                    DownloadedFile(
                        path=dl_res.dest_path,
                        url=download_url,
                        sha256=dl_res.sha256,
                        size_bytes=dl_res.size_bytes,
                        course_id=str(course.id),
                    )
                )


def _handle_sync(args: argparse.Namespace, json_mode: bool) -> int:
    cfg = load_config()
    if args.preset:
        cfg.sync.preset = args.preset.lower()
    dry_run = bool(args.dry_run or cfg.sync.dry_run)

    state_db = StateDatabase()
    if not dry_run:
        cfg.courses_root.mkdir(parents=True, exist_ok=True)

    adoption_scanner = AdoptionScanner(cfg.courses_root, state_db)
    if args.adopt or not dry_run:
        adoption_scanner.scan_local_files()

    session = _obtain_authenticated_session(
        cfg=cfg,
        interactive=not args.no_interactive,
        json_mode=json_mode,
    )

    discovery = CourseDiscovery(session=session, base_url=cfg.moodle_url)
    c_filter = CourseFilter(
        semester=cfg.sync.semester,
        active_only=True,
        subgroup_map=cfg.sync.subgroups,
    )
    courses = discovery.discover_courses(course_filter=c_filter)

    if args.course:
        target_str = str(args.course).strip().lower()
        courses = [
            c
            for c in courses
            if str(c.id) == target_str or c.slug.lower() == target_str
        ]

    router = CourseRouter(cfg.sync)
    downloader = SafeDownloader(session=session)
    overwrite_guard = OverwriteGuard(state_db)
    summary = SyncSummary()
    planned_actions: List[Dict[str, Any]] = []

    for c in courses:
        state_db.upsert_course(
            CourseRecord(
                course_id=c.id,
                fullname=c.fullname,
                shortname=c.shortname,
                idnumber=c.idnumber,
                category=c.coursecategory,
                is_active=1 if c.is_active else 0,
                last_synced_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
        )
        _sync_single_course(
            course=c,
            session=session,
            cfg=cfg,
            state_db=state_db,
            router=router,
            downloader=downloader,
            adoption_scanner=adoption_scanner,
            overwrite_guard=overwrite_guard,
            summary=summary,
            dry_run=dry_run,
            force=args.force,
            planned_actions=planned_actions,
        )

    if not dry_run:
        export_dashboard(courses_root=cfg.courses_root, summary=summary, state_db=state_db)
        export_changelog(courses_root=cfg.courses_root, summary=summary)
        export_calendar(courses_root=cfg.courses_root, deadlines=summary.deadlines)

    star_info = None
    if not dry_run:
        star_info = maybe_prompt_star_after_sync(
            interactive=not args.no_interactive,
            json_mode=json_mode,
        )

    payload = {
        "status": "success",
        "dry_run": dry_run,
        "courses_synced": len(courses),
        "downloaded": len(summary.downloaded_files),
        "updated": len(summary.updated_files),
        "adopted": len(summary.adopted_files),
        "conflicts": len(summary.conflict_files),
        "deadlines": len(summary.deadlines),
        "forum_announcements": len(summary.forum_announcements),
        "planned_actions": planned_actions if dry_run else [],
        "star": star_info,
    }

    if json_mode:
        _emit_json(payload)
    else:
        mode_tag = " (DRY-RUN PREVIEW)" if dry_run else ""
        print(f"✓ Sync complete{mode_tag} across {len(courses)} course(s).")
        if dry_run:
            print(f"  Planned items: {len(planned_actions)}")
            for item in planned_actions[:25]:
                print(f"    • [{item['action']}] {item['relative_path']} ({item['activity']})")
        else:
            print(
                f"  Downloaded: {len(summary.downloaded_files)} | "
                f"Adopted: {len(summary.adopted_files)} | "
                f"Conflicts Protected: {len(summary.conflict_files)} | "
                f"Deadlines: {len(summary.deadlines)}"
            )
    return 0


def _handle_doctor(args: argparse.Namespace, json_mode: bool) -> int:
    if args.fix:
        cfg_dir = get_config_dir()
        ensure_secure_dir(cfg_dir)
        for p in (get_config_file(), get_session_file(), get_state_db_path()):
            if p.exists() and os.name != "nt":
                try:
                    os.chmod(p, 0o600)
                except OSError:
                    pass
        try:
            cfg = load_config()
            cfg.courses_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    engine = DoctorEngine()
    report = engine.run_all()
    if json_mode:
        data = report.to_dict()
        data["status"] = "success" if report.overall_status != ProbeStatus.FAIL else "error"
        data["verdict"] = (
            "SYSTEM_OPERATIONAL" if report.overall_status != ProbeStatus.FAIL else "ISSUES_DETECTED"
        )
        _emit_json(data)
    else:
        print(report.format_terminal(use_color=sys.stdout.isatty()))
    return 0 if report.overall_status != ProbeStatus.FAIL else 1


def _handle_daemon(args: argparse.Namespace, json_mode: bool) -> int:
    mgr = DaemonManager()
    action = args.daemon_action or "status"

    if action == "install":
        ok = mgr.install(interval_seconds=args.interval)
        st = mgr.status()
        if json_mode:
            _emit_json({"status": "success" if ok else "error", "installed": ok, "daemon": st.to_dict()})
        else:
            print(f"✓ Daemon installed ({st.backend}, interval={args.interval}s)." if ok else "✗ Failed to install daemon.")
        return 0 if ok else 1

    if action == "uninstall":
        ok = mgr.uninstall()
        if json_mode:
            _emit_json({"status": "success" if ok else "error", "uninstalled": ok})
        else:
            print("✓ Daemon uninstalled." if ok else "✗ Failed to uninstall daemon.")
        return 0 if ok else 1

    if action == "start":
        ok = mgr.start()
        if json_mode:
            _emit_json({"status": "success" if ok else "error", "started": ok})
        else:
            print("✓ Daemon started." if ok else "✗ Failed to start daemon.")
        return 0 if ok else 1

    if action == "stop":
        ok = mgr.stop()
        if json_mode:
            _emit_json({"status": "success" if ok else "error", "stopped": ok})
        else:
            print("✓ Daemon stopped." if ok else "✗ Failed to stop daemon.")
        return 0 if ok else 1

    # status
    st = mgr.status()
    if json_mode:
        _emit_json({"status": "success", "daemon": st.to_dict()})
    else:
        print(st.format_terminal())
    return 0


def _handle_star(args: argparse.Namespace, json_mode: bool) -> int:
    res = execute_star(use_browser_fallback=not args.no_browser)
    if json_mode:
        _emit_json(res)
    else:
        print(f"⭐ {res['message']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Constructs the top-level CLI ArgumentParser and all subcommand parsers."""
    parser = argparse.ArgumentParser(
        prog="prado",
        description="PradoOS — Open-Source Academic Workflow Engine for Moodle & PRADO UGR.",
    )
    parser.add_argument("--version", action="version", version=f"prado {__version__}")
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit deterministic machine-readable JSON output to stdout.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # 1. onboard
    p_onboard = subparsers.add_parser("onboard", help="Interactive 2-phase setup wizard.")
    p_onboard.add_argument("--username", help="Institutional email or username.")
    p_onboard.add_argument("--password", help="Institutional password.")
    p_onboard.add_argument("--url", help="Moodle / PRADO base URL or platform preset (grado/posgrado/ceprud).")
    p_onboard.add_argument("--courses-root", help="Destination folder for synced courses.")
    p_onboard.add_argument("--preset", choices=["smart", "mirror"], help="Folder routing preset.")
    p_onboard.add_argument("--semester", type=int, choices=[1, 2], help="Active semester filter (1 or 2).")
    p_onboard.add_argument("--subgroups", help="Comma-separated subgroup map (e.g. ED_C=C2,SO_E=E3).")
    p_onboard.add_argument("--imap-enabled", action="store_true", help="Enable IMAP 2FA code auto-fetch.")
    p_onboard.add_argument("--imap-host", help="IMAP hostname (e.g. imap.ugr.es).")
    p_onboard.add_argument("--imap-username", help="IMAP login username.")
    p_onboard.add_argument("--imap-password", help="IMAP login password.")
    p_onboard.add_argument("--install-daemon", action="store_true", help="Install background sync daemon.")
    p_onboard.add_argument("--no-interactive", action="store_true", help="Disable interactive TTY prompts.")
    p_onboard.add_argument("--no-star", action="store_true", help="Skip post-onboarding GitHub star prompt.")
    p_onboard.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 2. auth
    p_auth = subparsers.add_parser("auth", help="Manage SAML authentication and 30-day MFA sessions.")
    p_auth.add_argument("auth_action", nargs="?", choices=["login", "logout", "status"], help="Auth subcommand.")
    p_auth.add_argument("--username", help="Institutional username.")
    p_auth.add_argument("--password", help="Institutional password.")
    p_auth.add_argument("--mfa-code", help="6-digit email verification code for non-interactive Tier 3 auth.")
    p_auth.add_argument("--gui", action="store_true", help="Prompt for credentials/MFA via native OS GUI popup dialog.")
    p_auth.add_argument("--url", help="Override Moodle base URL.")
    p_auth.add_argument("--offline", action="store_true", help="Check local session state without network ping.")
    p_auth.add_argument("--no-interactive", action="store_true", help="Disable interactive prompts.")
    p_auth.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 3. discover
    p_disc = subparsers.add_parser("discover", help="Auto-discover enrolled Moodle courses.")
    p_disc.add_argument("--semester", type=int, choices=[1, 2], help="Filter by semester (1 or 2).")
    p_disc.add_argument("--include-hidden", action="store_true", help="Include hidden courses.")
    p_disc.add_argument("--all", action="store_true", help="Return all courses across all semesters.")
    p_disc.add_argument("--url", help="Override Moodle base URL.")
    p_disc.add_argument("--no-interactive", action="store_true", help="Disable interactive prompts.")
    p_disc.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 4. courses
    p_courses = subparsers.add_parser("courses", help="List, enable, disable courses, or configure routing preset.")
    p_courses.add_argument(
        "courses_action",
        nargs="?",
        choices=["list", "enable", "disable", "set-preset"],
        default="list",
        help="Courses action.",
    )
    p_courses.add_argument("target", nargs="?", help="Course ID or preset name ('smart' or 'mirror').")
    p_courses.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 5. sync
    p_sync = subparsers.add_parser("sync", help="Synchronize course materials, deadlines, and Markdown/ICS exporters.")
    p_sync.add_argument("--course", help="Sync only a specific course ID or slug (e.g. 15819 or ED_C).")
    p_sync.add_argument("--dry-run", action="store_true", help="Preview planned folder tree without writing to disk.")
    p_sync.add_argument("--force", action="store_true", help="Re-download unmodified files.")
    p_sync.add_argument("--adopt", action="store_true", help="Pre-scan and adopt existing local files by SHA-256.")
    p_sync.add_argument("--preset", choices=["smart", "mirror"], help="Override routing preset for this run.")
    p_sync.add_argument("--no-interactive", action="store_true", help="Run non-interactively (daemon/agent mode).")
    p_sync.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 6. doctor
    p_doc = subparsers.add_parser("doctor", help="Run 9 diagnostic health probes across config, auth, network, and disk.")
    p_doc.add_argument("--fix", action="store_true", help="Automatically repair directory/file permissions (0700/0600).")
    p_doc.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 7. daemon
    p_daemon = subparsers.add_parser("daemon", help="Manage background sync scheduler (launchd / systemd / schtasks).")
    p_daemon.add_argument(
        "daemon_action",
        nargs="?",
        choices=["install", "uninstall", "status", "start", "stop"],
        default="status",
        help="Daemon action.",
    )
    p_daemon.add_argument("--interval", type=int, default=14400, help="Sync interval in seconds (default: 14400 = 4h).")
    p_daemon.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    # 8. star
    p_star = subparsers.add_parser("star", help="Star PradoOS on GitHub via `gh` CLI or web browser.")
    p_star.add_argument("--no-browser", action="store_true", help="Do not open browser if `gh` CLI is unavailable.")
    p_star.add_argument("--json", action="store_true", default=False, help="Output structured JSON.")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Main CLI entry point returning POSIX exit codes:
      0 = Success
      1 = General Error
      2 = MFA Verification Code Required
    """
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    global_json = "--json" in raw_args

    parser = build_parser()
    if not raw_args:
        parser.print_help()
        return 0

    args = parser.parse_args(raw_args)
    json_mode = bool(getattr(args, "json", False) or global_json)

    if not args.command:
        parser.print_help()
        return 0

    dispatch = {
        "onboard": _handle_onboard,
        "auth": _handle_auth,
        "discover": _handle_discover,
        "courses": _handle_courses,
        "sync": _handle_sync,
        "doctor": _handle_doctor,
        "daemon": _handle_daemon,
        "star": _handle_star,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args, json_mode=json_mode)
    except MfaRequiredError as mfa_err:
        if json_mode:
            _emit_json({
                "status": "mfa_required",
                "tier": mfa_err.tier,
                "factor": mfa_err.factor,
                "message": str(mfa_err),
                "retry_command": "prado auth login --mfa-code <6-digit-code>",
            })
        else:
            print(f"⚠ MFA Verification Required: {mfa_err}", file=sys.stderr)
            print("  Run: prado auth login --mfa-code <6-digit-code>", file=sys.stderr)
        return 2
    except PradoError as prado_err:
        if json_mode:
            _emit_json({
                "status": "error",
                "error": str(prado_err),
                "code": prado_err.__class__.__name__,
            })
        else:
            print(f"✗ Error ({prado_err.__class__.__name__}): {prado_err}", file=sys.stderr)
        return 1
    except Exception as exc:
        if json_mode:
            _emit_json({
                "status": "error",
                "error": str(exc),
                "code": exc.__class__.__name__,
            })
        else:
            print(f"✗ Unexpected error: {exc}", file=sys.stderr)
        return 1


def cli_entrypoint() -> None:
    """Console script entry point registered in pyproject.toml (`prado = prado.cli:cli_entrypoint`)."""
    sys.exit(main())


if __name__ == "__main__":
    cli_entrypoint()
