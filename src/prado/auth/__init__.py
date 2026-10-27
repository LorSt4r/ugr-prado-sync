"""
PradoOS Authentication and Security Subsystem.

Provides cross-platform headless Single Sign-On (SSO) for PRADO UGR SimpleSAMLphp,
native OS credential management (keyring with encrypted vault fallback),
3-tier Multi-Factor Authentication (MFA), and secure session cookie persistence.
"""

from prado.auth.credentials import CredentialStore
from prado.auth.mfa import MfaResolver
from prado.auth.saml import UgrSamlDriver
from prado.auth.session import MoodleSessionManager

__all__ = [
    "CredentialStore",
    "MfaResolver",
    "MoodleSessionManager",
    "UgrSamlDriver",
]
