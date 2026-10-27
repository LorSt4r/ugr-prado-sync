"""
PradoOS Onboarding & GitHub Star Loop Module.
"""

from prado.onboarding.star import (
    DEFAULT_GITHUB_REPO,
    DEFAULT_GITHUB_URL,
    STAR_MARKER_FILENAME,
    execute_star,
    get_star_marker_path,
    has_been_prompted,
    mark_prompted,
    maybe_prompt_star_after_sync,
    open_repo_in_browser,
    star_via_gh_cli,
)
from prado.onboarding.wizard import (
    OnboardingWizard,
    resolve_platform_url,
    reveal_folder_in_file_manager,
)

__all__ = [
    "DEFAULT_GITHUB_REPO",
    "DEFAULT_GITHUB_URL",
    "STAR_MARKER_FILENAME",
    "OnboardingWizard",
    "execute_star",
    "get_star_marker_path",
    "has_been_prompted",
    "mark_prompted",
    "maybe_prompt_star_after_sync",
    "open_repo_in_browser",
    "resolve_platform_url",
    "reveal_folder_in_file_manager",
    "star_via_gh_cli",
]
