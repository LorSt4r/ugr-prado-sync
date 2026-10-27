"""
Adversarial test suite for PradoOS Milestone M1.
Focus:
- Strict Isolation (CWD and Course Directory)
- POSIX Permission Enforcement (0700 / 0600 under hostile umask & pre-existing lax modes)
- Session Expiration & Device Trust Token Preservation across Restarts
- Concurrency & Race Conditions (Multi-process and Multi-threaded)
"""

import concurrent.futures
import json
import os
import stat
import time
from pathlib import Path
import pytest
import requests

from prado.config import (
    PradoConfig,
    SyncConfig,
    ensure_secure_dir,
    get_config_dir,
    get_config_file,
    get_credentials_vault_file,
    get_session_file,
    get_state_db_path,
    load_config,
    save_config,
    write_secure_file,
)
from prado.auth.credentials import CredentialStore
from prado.auth.session import MoodleSessionManager


# =============================================================================
# 1. Strict Isolation from CWD and Courses Root
# =============================================================================

def test_adversarial_cwd_and_course_isolation(tmp_path, monkeypatch):
    """
    Adversarial test: Run config, session, and credential operations from inside
    a course directory as the current working directory (CWD).
    Guarantees that NO files or dotfiles are created in the course directory or CWD.
    """
    config_dir = tmp_path / "secure_config"
    courses_root = tmp_path / "student_courses"
    course_subdir = courses_root / "ED_C" / "Practicas"
    course_subdir.mkdir(parents=True)

    monkeypatch.setenv("PRADO_CONFIG_DIR", str(config_dir))
    monkeypatch.chdir(course_subdir)

    # 1. Config operations
    cfg = PradoConfig(
        username="adversarial_student@ugr.es",
        courses_root=courses_root,
        sync=SyncConfig(preset="smart"),
    )
    save_config(cfg)
    loaded_cfg = load_config()
    assert loaded_cfg.username == "adversarial_student@ugr.es"

    # 2. Session operations
    session_mgr = MoodleSessionManager()
    session_mgr.session.cookies.set("MoodleSession", "sess_adv_123", domain="pradogrado2627.ugr.es")
    session_mgr.session.cookies.set("MFA_TOKEN_test", "mfa_val_456", domain="pradogrado2627.ugr.es")
    session_mgr.save_session()

    # 3. Credential vault operations
    cred_store = CredentialStore(use_env=False, preferred_backend="vault")
    cred_store.set_sso_credentials("adversarial_student@ugr.es", "secret_pass_999")
    u, p = cred_store.get_sso_credentials("adversarial_student@ugr.es")
    assert u == "adversarial_student@ugr.es"
    assert p == "secret_pass_999"

    # 4. Verify courses directory is 100% pristine: zero files or subdirs were created inside
    course_files = list(courses_root.rglob("*"))
    # Only the directory itself and child directory that we created should exist
    assert all(p.is_dir() for p in course_files)
    assert len([p for p in course_files if p.is_file()]) == 0

    # 5. Verify config directory has all artifacts
    assert (config_dir / "config.yaml").exists()
    assert (config_dir / "session.json").exists()
    assert (config_dir / "credentials.vault").exists()
    assert (config_dir / ".machine_salt").exists()


# =============================================================================
# 2. POSIX Permissions Enforcement (0700 & 0600)
# =============================================================================

@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions tests")
def test_adversarial_directory_mode_enforcement(tmp_path, monkeypatch):
    """
    Test that config directory permissions are enforced to 0700:
    a) Fresh creation
    b) When pre-existing directory has lax permissions (e.g. 0777 or 0755)
    c) Under hostile umask (0000)
    """
    old_umask = os.umask(0)
    try:
        config_dir = tmp_path / "hostile_config_dir"
        # Pre-create with 0777
        config_dir.mkdir(mode=0o777)
        os.chmod(config_dir, 0o777)
        assert stat.S_IMODE(config_dir.stat().st_mode) == 0o777

        monkeypatch.setenv("PRADO_CONFIG_DIR", str(config_dir))

        # Call get_config_dir()
        resolved = get_config_dir()
        assert resolved == config_dir

        # Must have been tightened to 0700
        current_mode = stat.S_IMODE(config_dir.stat().st_mode)
        assert current_mode == 0o700, f"Expected 0700, got {oct(current_mode)}"
    finally:
        os.umask(old_umask)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions tests")
def test_adversarial_file_mode_enforcement_under_hostile_umask(tmp_path, monkeypatch):
    """
    Verify that write_secure_file, save_config, save_session, and vault write
    enforce mode 0600 even when process umask is 0000 (which normally creates 0666).
    Also verify when target file previously existed with mode 0666.
    """
    old_umask = os.umask(0)
    try:
        config_dir = tmp_path / "umask_test_dir"
        monkeypatch.setenv("PRADO_CONFIG_DIR", str(config_dir))

        # 1. Test write_secure_file
        test_file = config_dir / "test_umask.txt"
        write_secure_file(test_file, "secret", mode=0o600)
        mode = stat.S_IMODE(test_file.stat().st_mode)
        assert mode == 0o600, f"Expected 0600, got {oct(mode)}"

        # 2. Test pre-existing 0666 file overwritten by write_secure_file
        test_file_lax = config_dir / "lax.txt"
        test_file_lax.write_text("old", encoding="utf-8")
        os.chmod(test_file_lax, 0o666)
        assert stat.S_IMODE(test_file_lax.stat().st_mode) == 0o666

        write_secure_file(test_file_lax, "new_secret", mode=0o600)
        mode_after = stat.S_IMODE(test_file_lax.stat().st_mode)
        assert mode_after == 0o600, f"Expected 0600 after replace, got {oct(mode_after)}"

        # 3. Test save_config with hostile umask
        cfg_file = config_dir / "config.yaml"
        save_config(PradoConfig())
        assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600

        # 4. Test save_session with hostile umask
        sess_mgr = MoodleSessionManager(session_path=config_dir / "session.json")
        sess_mgr.session.cookies.set("test", "val")
        sess_mgr.save_session()
        assert stat.S_IMODE((config_dir / "session.json").stat().st_mode) == 0o600

        # 5. Test vault and salt with hostile umask
        cred_store = CredentialStore(use_env=False, preferred_backend="vault", vault_path=config_dir / "credentials.vault")
        cred_store.set_sso_credentials("user", "pass")
        assert stat.S_IMODE((config_dir / "credentials.vault").stat().st_mode) == 0o600
        assert stat.S_IMODE((config_dir / ".machine_salt").stat().st_mode) == 0o600
    finally:
        os.umask(old_umask)


# =============================================================================
# 3. Session Expiration & Device Trust Token Preservation across Restarts
# =============================================================================

def test_session_lifecycle_and_device_trust_preservation(tmp_path):
    """
    Simulates:
    1. Initial session created with mixed cookies (valid session, expired cookie,
       near-expiry cookie, device trust token valid for 30 days, moodleid).
    2. Serialization to session.json.
    3. Simulated process exit and restart.
    4. Session load after time passes: verify expired cookies are discarded,
       active session and 30-day device trust token are preserved.
    5. Injection of preserved tokens into a brand new HTTP session.
    """
    sess_file = tmp_path / "session.json"
    now = time.time()

    # Create manager 1 (simulating process 1)
    mgr1 = MoodleSessionManager(session_path=sess_file)

    # 1. Cookie that expired 10 minutes ago
    mgr1.session.cookies.set(
        "ExpiredCookie", "dead",
        domain="pradogrado2627.ugr.es", path="/", expires=now - 600,
    )
    # 2. Short-lived cookie expiring in 5 seconds
    mgr1.session.cookies.set(
        "ShortLived", "soon_dead",
        domain="pradogrado2627.ugr.es", path="/", expires=now + 5,
    )
    # 3. Standard session cookie valid for 4 hours
    mgr1.session.cookies.set(
        "MoodleSession", "sess_valid_active_777",
        domain="pradogrado2627.ugr.es", path="/", expires=now + 14400,
    )
    # 4. Session cookie with no expiry (session lifetime)
    mgr1.session.cookies.set(
        "SessionOnly", "persists_until_logout",
        domain="pradogrado2627.ugr.es", path="/", expires=None,
    )
    # 5. Device trust token valid for 30 days
    mgr1.session.cookies.set(
        "MFA_TOKEN_device_trust_hash", "30_day_token_xyz999",
        domain="pradogrado2627.ugr.es", path="/", expires=now + (30 * 86400),
    )
    # 6. MOODLEID cookie valid for 30 days
    mgr1.session.cookies.set(
        "MOODLEID1_", "user_moodle_identifier",
        domain="pradogrado2627.ugr.es", path="/", expires=now + (30 * 86400),
    )

    # Save to disk
    mgr1.save_session()
    assert sess_file.exists()

    # Advance time: simulate 10 seconds passing (so ShortLived is now expired)
    # Re-open in fresh manager 2 (simulating process restart)
    mgr2 = MoodleSessionManager(session_path=sess_file)

    # We patch time.time() during load_session to simulate +10 seconds
    future_now = now + 10
    orig_time = time.time
    try:
        time.time = lambda: future_now

        loaded = mgr2.load_session()
        assert loaded is True

        cookie_dict = mgr2.session.cookies.get_dict()

        # Expired cookies MUST NOT be loaded
        assert "ExpiredCookie" not in cookie_dict
        assert "ShortLived" not in cookie_dict

        # Valid cookies MUST be loaded
        assert cookie_dict["MoodleSession"] == "sess_valid_active_777"
        assert cookie_dict["SessionOnly"] == "persists_until_logout"
        assert cookie_dict["MFA_TOKEN_device_trust_hash"] == "30_day_token_xyz999"
        assert cookie_dict["MOODLEID1_"] == "user_moodle_identifier"

        # Verify extract_mfa_tokens
        mfa_tokens = mgr2.extract_mfa_tokens()
        token_map = {t["name"]: t["value"] for t in mfa_tokens}
        assert "MFA_TOKEN_device_trust_hash" in token_map
        assert token_map["MFA_TOKEN_device_trust_hash"] == "30_day_token_xyz999"
        assert "MOODLEID1_" in token_map
        assert token_map["MOODLEID1_"] == "user_moodle_identifier"
        assert "MoodleSession" not in token_map

        # Verify inject_preserved_tokens into brand new session
        fresh_session = requests.Session()
        mgr2.inject_preserved_tokens(fresh_session)
        assert fresh_session.cookies.get("MFA_TOKEN_device_trust_hash") == "30_day_token_xyz999"
        assert fresh_session.cookies.get("MOODLEID1_") == "user_moodle_identifier"
        assert fresh_session.cookies.get("MoodleSession") is None

    finally:
        time.time = orig_time


def test_expired_device_trust_tokens_are_not_extracted(tmp_path):
    """
    Verify that if a 30-day device trust token has actually expired,
    extract_mfa_tokens ignores it and does not inject it.
    """
    sess_file = tmp_path / "session_expired_tokens.json"
    now = time.time()

    # Store expired MFA token
    data = [
        {
            "name": "MFA_TOKEN_old",
            "value": "expired_hash",
            "domain": "pradogrado2627.ugr.es",
            "path": "/",
            "secure": True,
            "expires": now - 100,  # Expired in past
        }
    ]
    sess_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = MoodleSessionManager(session_path=sess_file)
    tokens = mgr.extract_mfa_tokens()
    assert len(tokens) == 0

    fresh_session = requests.Session()
    mgr.inject_preserved_tokens(fresh_session)
    assert len(fresh_session.cookies) == 0


# =============================================================================
# 4. Concurrency & Stress Testing
# =============================================================================

def _concurrent_config_worker(args):
    """Worker function for multi-process concurrency testing."""
    config_dir_str, worker_id = args
    os.environ["PRADO_CONFIG_DIR"] = config_dir_str
    config_path = Path(config_dir_str) / "config.yaml"

    errors = []
    for iteration in range(25):
        try:
            # Alternate between reading and writing
            if iteration % 2 == 0:
                cfg = PradoConfig(username=f"worker_{worker_id}_iter_{iteration}@ugr.es")
                save_config(cfg, config_path)
            else:
                loaded = load_config(config_path)
                # Validated loaded config is a valid PradoConfig
                if not isinstance(loaded, PradoConfig):
                    errors.append(f"Invalid loaded config: {loaded}")
        except Exception as e:
            errors.append(f"Worker {worker_id} iter {iteration} failed: {e}")

    return errors


def test_multi_process_concurrency(tmp_path):
    """
    Multi-process stress test:
    Launch 6 separate OS processes concurrently loading and saving config.yaml.
    Guarantees no race condition crashes or corrupted partial YAML writes.
    """
    config_dir = tmp_path / "mp_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    initial_cfg = PradoConfig(username="initial@ugr.es")
    save_config(initial_cfg, config_dir / "config.yaml")

    tasks = [(str(config_dir), i) for i in range(6)]

    with concurrent.futures.ProcessPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_concurrent_config_worker, tasks))

    all_errors = [err for worker_errors in results for err in worker_errors]
    assert len(all_errors) == 0, f"Concurrency errors occurred: {all_errors}"

    # Final file must be valid YAML
    final_cfg = load_config(config_dir / "config.yaml")
    assert isinstance(final_cfg, PradoConfig)
    assert final_cfg.username.startswith("worker_")


def test_multi_thread_concurrency_stress(tmp_path, monkeypatch):
    """
    Multi-thread stress test:
    Multiple threads within the SAME process calling write_secure_file / save_config.
    Because threads share os.getpid(), verifies whether tmp_path causes thread collisions.
    """
    config_dir = tmp_path / "mt_config"
    monkeypatch.setenv("PRADO_CONFIG_DIR", str(config_dir))
    config_file = config_dir / "config.yaml"

    errors = []

    def thread_worker(thread_id: int):
        for i in range(20):
            try:
                cfg = PradoConfig(username=f"thread_{thread_id}_cycle_{i}")
                save_config(cfg, config_file)
                loaded = load_config(config_file)
                if not isinstance(loaded, PradoConfig):
                    errors.append(f"Thread {thread_id} read invalid object")
            except Exception as e:
                errors.append(f"Thread {thread_id} error on cycle {i}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(thread_worker, t_id) for t_id in range(8)]
        concurrent.futures.wait(futures)

    # Let's inspect the results
    if errors:
        pytest.fail(f"Multi-thread concurrency failed with {len(errors)} errors: {errors[:5]}")
