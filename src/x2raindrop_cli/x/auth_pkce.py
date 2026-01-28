"""OAuth 2.0 PKCE authentication flow for X API.

This module implements the OAuth 2.0 Authorization Code Flow with PKCE
for authenticating with the X API in user context.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# X OAuth2 endpoints
X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"


@dataclass
class PKCECodes:
    """PKCE code verifier and challenge pair.

    Attributes:
        verifier: The code verifier (random string).
        challenge: The code challenge (SHA256 hash of verifier, base64url encoded).
    """

    verifier: str
    challenge: str


@dataclass
class OAuth2Token:
    """OAuth2 token data.

    Attributes:
        access_token: The access token for API requests.
        refresh_token: The refresh token for getting new access tokens.
        token_type: Token type (usually "bearer").
        expires_at: When the access token expires.
        scope: Space-separated list of granted scopes.
    """

    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime
    scope: str

    def is_expired(self) -> bool:
        """Check if the token is expired or about to expire.

        Returns:
            True if the token expires within 60 seconds.
        """
        return datetime.now() >= (self.expires_at - timedelta(seconds=60))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the token.
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at.isoformat(),
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OAuth2Token:
        """Create from dictionary.

        Args:
            data: Dictionary with token data.

        Returns:
            OAuth2Token instance.
        """
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data["token_type"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            scope=data["scope"],
        )

    @classmethod
    def from_access_token(
        cls,
        access_token: str,
        token_type: str = "bearer",
        expires_in_days: int = 365,
    ) -> OAuth2Token:
        """Create from a direct access token.

        Use this when you have an access token from another source
        (e.g., X Developer Portal, automation scripts).

        NOTE: Direct tokens typically cannot be refreshed and may have
        different expiration behavior than PKCE-obtained tokens.

        Args:
            access_token: The access token string.
            token_type: Token type (default: "bearer").
            expires_in_days: Assumed expiration in days (default: 365).

        Returns:
            OAuth2Token instance.
        """
        return cls(
            access_token=access_token,
            refresh_token=None,  # Direct tokens typically don't have refresh tokens
            token_type=token_type,
            expires_at=datetime.now() + timedelta(days=expires_in_days),
            scope="",  # Unknown scope for direct tokens
        )


def generate_pkce_codes() -> PKCECodes:
    """Generate PKCE code verifier and challenge.

    The verifier is a cryptographically random string of 43-128 characters.
    The challenge is the SHA256 hash of the verifier, base64url encoded.

    Returns:
        PKCECodes with verifier and challenge.
    """
    # Generate a random 32-byte (256-bit) verifier
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")

    # Create challenge as SHA256 hash of verifier, base64url encoded
    challenge_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(challenge_hash).decode("ascii").rstrip("=")

    return PKCECodes(verifier=verifier, challenge=challenge)


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection.

    Returns:
        Random state string.
    """
    return secrets.token_urlsafe(32)


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    code_challenge: str,
    state: str,
) -> str:
    """Build the authorization URL for the OAuth2 flow.

    Args:
        client_id: X OAuth2 client ID.
        redirect_uri: Redirect URI for the callback.
        scopes: List of OAuth2 scopes to request.
        code_challenge: PKCE code challenge.
        state: State parameter for CSRF protection.

    Returns:
        Full authorization URL to redirect the user to.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{X_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(
    code: str,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    code_verifier: str,
) -> OAuth2Token:
    """Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from the callback.
        client_id: X OAuth2 client ID.
        client_secret: Optional client secret for confidential apps.
        redirect_uri: Redirect URI used in the authorization request.
        code_verifier: PKCE code verifier.

    Returns:
        OAuth2Token with access and refresh tokens.

    Raises:
        httpx.HTTPStatusError: If the token exchange fails.
    """
    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth = None

    if client_secret:
        # Use Basic auth for confidential clients
        auth = httpx.BasicAuth(client_id, client_secret)

    with httpx.Client() as client:
        response = client.post(X_TOKEN_URL, data=data, headers=headers, auth=auth)
        response.raise_for_status()
        token_data = response.json()

    expires_in = token_data.get("expires_in", 7200)
    expires_at = datetime.now() + timedelta(seconds=expires_in)

    return OAuth2Token(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_type=token_data.get("token_type", "bearer"),
        expires_at=expires_at,
        scope=token_data.get("scope", ""),
    )


def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str | None,
) -> OAuth2Token:
    """Refresh an expired access token.

    Args:
        refresh_token: The refresh token.
        client_id: X OAuth2 client ID.
        client_secret: Optional client secret for confidential apps.

    Returns:
        New OAuth2Token with fresh access token.

    Raises:
        httpx.HTTPStatusError: If the refresh fails.
    """
    data = {
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "client_id": client_id,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth = None

    if client_secret:
        auth = httpx.BasicAuth(client_id, client_secret)

    with httpx.Client() as client:
        response = client.post(X_TOKEN_URL, data=data, headers=headers, auth=auth)
        response.raise_for_status()
        token_data = response.json()

    expires_in = token_data.get("expires_in", 7200)
    expires_at = datetime.now() + timedelta(seconds=expires_in)

    return OAuth2Token(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", refresh_token),
        token_type=token_data.get("token_type", "bearer"),
        expires_at=expires_at,
        scope=token_data.get("scope", ""),
    )


def save_token(token: OAuth2Token, path: Path) -> None:
    """Save a token to disk.

    Args:
        token: The token to save.
        path: Path to save the token to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(token.to_dict(), f, indent=2)
    logger.debug("Token saved", path=str(path))


def load_token(path: Path) -> OAuth2Token | None:
    """Load a token from disk.

    Args:
        path: Path to load the token from.

    Returns:
        OAuth2Token if found and valid, None otherwise.
    """
    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)
        return OAuth2Token.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to load token", path=str(path), error=str(e))
        return None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for OAuth2 callback."""

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        """Handle GET request (OAuth2 callback)."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            CallbackHandler.error = params["error"][0]
            self._send_response("Authorization failed. You can close this window.")
        elif "code" in params:
            CallbackHandler.auth_code = params["code"][0]
            CallbackHandler.state = params.get("state", [None])[0]
            self._send_response("Authorization successful! You can close this window.")
        else:
            self._send_response("Invalid callback request.")

    def _send_response(self, message: str) -> None:
        """Send an HTML response."""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>X Authorization</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>{message}</h1>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP server logging."""
        pass


class PKCEAuthFlow:
    """Manages the OAuth 2.0 PKCE authentication flow.

    This class handles the complete flow including:
    - Starting a local server for the callback
    - Opening the browser for authorization
    - Exchanging the code for tokens
    - Persisting and refreshing tokens
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str | None,
        redirect_uri: str,
        scopes: list[str],
        token_path: Path,
    ) -> None:
        """Initialize the auth flow.

        Args:
            client_id: X OAuth2 client ID.
            client_secret: Optional client secret.
            redirect_uri: Redirect URI for callback.
            scopes: OAuth2 scopes to request.
            token_path: Path to store tokens.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.token_path = token_path
        self._token: OAuth2Token | None = None

    def get_token(self) -> OAuth2Token | None:
        """Get a valid access token, refreshing if necessary.

        Returns:
            Valid OAuth2Token or None if not authenticated.
        """
        if self._token is None:
            self._token = load_token(self.token_path)

        if self._token is None:
            return None

        if self._token.is_expired():
            if self._token.refresh_token:
                try:
                    self._token = refresh_access_token(
                        self._token.refresh_token,
                        self.client_id,
                        self.client_secret,
                    )
                    save_token(self._token, self.token_path)
                    logger.info("Token refreshed successfully")
                except httpx.HTTPStatusError as e:
                    logger.error("Token refresh failed", error=str(e))
                    return None
            else:
                logger.warning("Token expired and no refresh token available")
                return None

        return self._token

    def login(self, timeout: int = 120) -> OAuth2Token:
        """Perform interactive login flow.

        Opens a browser for the user to authorize, then exchanges
        the code for tokens.

        Args:
            timeout: How long to wait for the callback (seconds).

        Returns:
            OAuth2Token after successful authentication.

        Raises:
            TimeoutError: If the callback is not received in time.
            RuntimeError: If authorization fails.
        """
        # Reset callback handler state
        CallbackHandler.auth_code = None
        CallbackHandler.state = None
        CallbackHandler.error = None

        # Generate PKCE codes and state
        pkce = generate_pkce_codes()
        state = generate_state()

        # Parse port from redirect URI
        parsed = urllib.parse.urlparse(self.redirect_uri)
        port = parsed.port or 8765

        # Start local server in background thread
        server = socketserver.TCPServer(("127.0.0.1", port), CallbackHandler)
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        # Build and open authorization URL
        auth_url = build_authorization_url(
            self.client_id,
            self.redirect_uri,
            self.scopes,
            pkce.challenge,
            state,
        )

        logger.info("Opening browser for authorization...")
        webbrowser.open(auth_url)

        # Wait for callback
        start_time = time.time()
        while server_thread.is_alive():
            if time.time() - start_time > timeout:
                server.shutdown()
                raise TimeoutError("Authorization timed out")
            time.sleep(0.1)

        server.server_close()

        # Check for errors
        if CallbackHandler.error:
            raise RuntimeError(f"Authorization failed: {CallbackHandler.error}")

        if not CallbackHandler.auth_code:
            raise RuntimeError("No authorization code received")

        # Verify state
        if CallbackHandler.state != state:
            raise RuntimeError("State mismatch - possible CSRF attack")

        # Exchange code for tokens
        logger.info("Exchanging authorization code for tokens...")
        token = exchange_code_for_token(
            CallbackHandler.auth_code,
            self.client_id,
            self.client_secret,
            self.redirect_uri,
            pkce.verifier,
        )

        # Save token
        save_token(token, self.token_path)
        self._token = token

        logger.info("Login successful!")
        return token

    def is_authenticated(self) -> bool:
        """Check if we have a valid token.

        Returns:
            True if authenticated with a valid token.
        """
        return self.get_token() is not None

    def logout(self) -> None:
        """Clear saved tokens."""
        self._token = None
        if self.token_path.exists():
            self.token_path.unlink()
            logger.info("Token cleared")
