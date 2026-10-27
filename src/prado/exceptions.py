"""
Custom exception hierarchy for PradoOS.
"""


class PradoError(Exception):
    """Base exception for all PradoOS errors."""

    pass


class ConfigError(PradoError):
    """Raised when configuration is invalid, corrupted, or cannot be loaded."""

    pass


class AuthError(PradoError):
    """Base exception for all authentication and security errors."""

    pass


class InvalidCredentialsError(AuthError):
    """Raised when username or password is rejected by the Identity Provider."""

    pass


class AccountLockedError(AuthError):
    """Raised when the user account is locked or disabled on the IdP."""

    pass


class PasswordExpiredError(AuthError):
    """Raised when the user password has expired and must be updated."""

    pass


class AuthenticationRequiredError(AuthError):
    """Raised when an operation requires an active authenticated session but none exists."""

    pass


class MfaRequiredError(AuthError):
    """
    Raised in non-interactive / agent mode when a 2FA verification code is required.
    Used by CLI to exit with code 2 and emit structured JSON.
    """

    def __init__(
        self,
        prompt: str = "Two-factor verification code required",
        factor: str = "email",
        tier: int = 3,
    ) -> None:
        super().__init__(prompt)
        self.prompt = prompt
        self.factor = factor
        self.tier = tier


class MfaChallengeRequiredError(MfaRequiredError):
    """Alias for MfaRequiredError for contract compatibility."""

    pass


class MfaVerificationFailedError(AuthError):
    """Raised when the submitted 6-digit MFA code is invalid, rejected, or expired."""

    pass


class SessionExpiredError(AuthError):
    """Raised when an authenticated session expires or is terminated mid-operation."""

    pass


class KeyringStorageError(AuthError):
    """Raised when secure credential storage or retrieval encounters an unrecoverable error."""

    pass


class NetworkError(PradoError):
    """Raised when HTTP network communication or connection fails."""

    pass
