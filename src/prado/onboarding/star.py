"""
GitHub Star Loop (`prado star`) and one-time post-sync star prompt for PradoOS.

Supports starring the repository directly via GitHub CLI (`gh api --method PUT /user/starred/...`)
or opening the repository page in the user's default browser, while tracking `.star_prompted`
in the isolated OS configuration directory so students are never nagged twice.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable, Dict, Optional
import webbrowser

from prado.config import ensure_secure_dir, get_config_dir, write_secure_file

DEFAULT_GITHUB_REPO = "LorSt4r/ugr-prado-sync"
DEFAULT_GITHUB_URL = f"https://github.com/{DEFAULT_GITHUB_REPO}"
STAR_MARKER_FILENAME = ".star_prompted"


def get_star_marker_path(config_dir: Optional[Path] = None) -> Path:
    """Returns the path to the `.star_prompted` state marker inside the config directory."""
    base_dir = Path(config_dir) if config_dir is not None else get_config_dir()
    ensure_secure_dir(base_dir)
    return base_dir / STAR_MARKER_FILENAME


def has_been_prompted(config_dir: Optional[Path] = None) -> bool:
    """Returns True if the user has already seen the one-time star prompt."""
    return get_star_marker_path(config_dir).exists()


def mark_prompted(config_dir: Optional[Path] = None, status: str = "prompted") -> Path:
    """Creates or updates the `.star_prompted` marker file with mode 0600."""
    marker = get_star_marker_path(config_dir)
    write_secure_file(marker, f"{status}\n", mode=0o600)
    return marker


def star_via_gh_cli(repo: str = DEFAULT_GITHUB_REPO, timeout: int = 10) -> bool:
    """
    Attempts to star the repository using the authenticated GitHub CLI (`gh`).
    Returns True if `gh api` succeeded with exit code 0, False otherwise.
    """
    gh_bin = shutil.which("gh")
    if not gh_bin:
        return False

    try:
        proc = subprocess.run(
            [gh_bin, "api", "--method", "PUT", f"/user/starred/{repo}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def open_repo_in_browser(repo: str = DEFAULT_GITHUB_REPO) -> bool:
    """Opens the GitHub repository URL in the system default web browser."""
    url = f"https://github.com/{repo}"
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def execute_star(
    repo: str = DEFAULT_GITHUB_REPO,
    use_browser_fallback: bool = True,
    config_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Executes the star action:
    1. Tries `gh api --method PUT /user/starred/{repo}` first.
    2. Falls back to opening the GitHub repository URL in the browser if requested.
    3. Marks `.star_prompted` in the config directory.
    """
    url = f"https://github.com/{repo}"
    if star_via_gh_cli(repo=repo):
        mark_prompted(config_dir=config_dir, status="starred_via_gh")
        return {
            "status": "starred",
            "method": "gh_cli",
            "repo": repo,
            "url": url,
            "message": f"Starred {repo} on GitHub via GitHub CLI! Thank you for supporting PradoOS.",
        }

    if use_browser_fallback:
        opened = open_repo_in_browser(repo=repo)
        mark_prompted(config_dir=config_dir, status="opened_browser")
        return {
            "status": "opened_browser" if opened else "manual_url",
            "method": "browser" if opened else "url",
            "repo": repo,
            "url": url,
            "message": f"Star PradoOS on GitHub: {url}",
        }

    mark_prompted(config_dir=config_dir, status="manual_url")
    return {
        "status": "manual_url",
        "method": "url",
        "repo": repo,
        "url": url,
        "message": f"Star PradoOS on GitHub: {url}",
    }


def maybe_prompt_star_after_sync(
    interactive: bool = True,
    json_mode: bool = False,
    config_dir: Optional[Path] = None,
    repo: str = DEFAULT_GITHUB_REPO,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """
    One-time post-sync GitHub star prompt.
    If `.star_prompted` already exists, does nothing and returns `{"prompted": False}`.
    Otherwise records `.star_prompted` immediately so the user is never asked twice.
    """
    if has_been_prompted(config_dir):
        return {
            "prompted": False,
            "reason": "already_prompted",
            "repo": repo,
            "url": f"https://github.com/{repo}",
        }

    # Record marker immediately so we never nag on future syncs
    mark_prompted(config_dir=config_dir, status="prompted")
    url = f"https://github.com/{repo}"

    is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    if json_mode or not interactive or not is_tty:
        return {
            "prompted": True,
            "starred": False,
            "repo": repo,
            "url": url,
            "message": (
                f"First sync complete! If PradoOS saved you time, give us a star on GitHub: "
                f"`prado star` or {url}"
            ),
        }

    print_fn(
        f"\n⭐ Enjoying PradoOS? Help other students discover it by starring {repo} on GitHub!"
    )
    try:
        answer = input_fn("   Would you like to star the repo now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer in ("", "y", "yes", "s", "si", "sí"):
        res = execute_star(repo=repo, use_browser_fallback=True, config_dir=config_dir)
        print_fn(f"   {res['message']}")
        return {
            "prompted": True,
            "starred": res["status"] == "starred",
            "method": res["method"],
            "repo": repo,
            "url": url,
        }

    print_fn(f"   No problem! You can run `prado star` anytime or visit {url}")
    return {
        "prompted": True,
        "starred": False,
        "method": "declined",
        "repo": repo,
        "url": url,
    }
