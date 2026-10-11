"""OAuth 2.0 authentication for Google Photos API."""

import logging
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

# Google Photos API scopes
# photoslibrary.readonly: Read photos and albums (includes search)
# Note: photoslibrary.sharing was deprecated by Google and removed
SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.readonly",
]


class GooglePhotosAuth:
    """Handles OAuth 2.0 authentication for Google Photos API.

    Supports two credential sources (in priority order):
    1. Environment variables: GOOGLE_PHOTOS__CLIENT_ID, GOOGLE_PHOTOS__CLIENT_SECRET
    2. File-based: credentials.json file

    Environment variables are preferred for production deployments.
    """

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
        config: Optional["GooglePhotosConfig"] = None,  # noqa: F821
    ):
        """
        Initialize authentication handler.

        Args:
            credentials_path: Path to OAuth client credentials file (fallback)
            token_path: Path to store/load OAuth tokens
            config: Optional GooglePhotosConfig instance for env var credentials
        """
        # Import here to avoid circular import
        if config is None:
            from gps_journey.config import config as app_config

            config = app_config.google_photos

        self._config = config
        self.credentials_path = credentials_path or config.credentials_path
        self.token_path = token_path or config.token_path
        self._creds: Credentials | None = None

    def _get_credentials_source(self) -> tuple[str, dict | Path]:
        """Determine the credentials source.

        Returns:
            Tuple of (source_type, source_data) where source_type is 'env' or 'file'
        """
        # Priority 1: Environment variables via config
        if self._config.has_env_credentials:
            logger.info("Using OAuth credentials from environment variables")
            return ("env", self._config.get_credentials_dict())

        # Priority 2: Credentials file
        if self.credentials_path.exists():
            logger.info("Using OAuth credentials from file: %s", self.credentials_path)
            return ("file", self.credentials_path)

        # No credentials available
        raise FileNotFoundError(
            "OAuth credentials not found. Configure one of:\n"
            "1. Environment variables: GOOGLE_PHOTOS__CLIENT_ID, GOOGLE_PHOTOS__CLIENT_SECRET\n"
            "2. Credentials file: credentials.json\n\n"
            "Get credentials from Google Cloud Console: "
            "https://console.cloud.google.com/apis/credentials"
        )

    def authenticate(self) -> Credentials:
        """
        Authenticate with Google Photos API.

        Returns OAuth credentials, either from cached token or by
        running the OAuth flow.

        Returns:
            OAuth2 credentials object

        Raises:
            FileNotFoundError: If no credentials source is available
            ValueError: If authentication fails
        """
        source_type, source_data = self._get_credentials_source()

        # Try to load existing token
        if self.token_path.exists():
            logger.info("Loading cached OAuth token from %s", self.token_path)
            self._creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        # Refresh token if expired, or run OAuth flow
        if not self._creds or not self._creds.valid:
            if self._creds and self._creds.expired and self._creds.refresh_token:
                logger.info("Refreshing expired OAuth token")
                self._creds.refresh(Request())
            else:
                logger.info("Starting OAuth 2.0 flow")
                if source_type == "env":
                    # Create flow from dict (env vars)
                    flow = InstalledAppFlow.from_client_config(source_data, SCOPES)
                else:
                    # Create flow from file
                    flow = InstalledAppFlow.from_client_secrets_file(str(source_data), SCOPES)
                self._creds = flow.run_local_server(port=0)

            # Save token for next time
            with open(self.token_path, "w") as token_file:
                token_file.write(self._creds.to_json())
            # Secure the token file (owner read/write only)
            os.chmod(self.token_path, 0o600)
            logger.info("OAuth token saved to %s", self.token_path)

        return self._creds

    def revoke(self) -> None:
        """Revoke current credentials and delete token file."""
        if self.token_path.exists():
            self.token_path.unlink()
            logger.info("OAuth token revoked and deleted")
        self._creds = None

    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated with valid credentials."""
        return self._creds is not None and self._creds.valid
