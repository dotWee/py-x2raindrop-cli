"""Tests for OAuth 2.0 PKCE authentication.

This module tests the PKCE authentication helpers and token management.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from py_x_bookmarks_to_raindrop_sync.x.auth_pkce import (
    OAuth2Token,
    PKCECodes,
    build_authorization_url,
    generate_pkce_codes,
    generate_state,
    load_token,
    save_token,
)

if TYPE_CHECKING:
    pass


class TestGeneratePkceCodes:
    """Tests for PKCE code generation."""

    def test_generates_verifier_and_challenge(self) -> None:
        """Test that both verifier and challenge are generated."""
        codes = generate_pkce_codes()

        assert isinstance(codes, PKCECodes)
        assert codes.verifier is not None
        assert codes.challenge is not None
        assert len(codes.verifier) > 0
        assert len(codes.challenge) > 0

    def test_verifier_length(self) -> None:
        """Test that verifier has appropriate length."""
        codes = generate_pkce_codes()
        # Base64 encoding of 32 bytes = 43 characters (without padding)
        assert len(codes.verifier) >= 43

    def test_challenge_is_different_from_verifier(self) -> None:
        """Test that challenge is derived but different from verifier."""
        codes = generate_pkce_codes()
        assert codes.challenge != codes.verifier

    def test_generates_unique_codes(self) -> None:
        """Test that each call generates unique codes."""
        codes1 = generate_pkce_codes()
        codes2 = generate_pkce_codes()

        assert codes1.verifier != codes2.verifier
        assert codes1.challenge != codes2.challenge

    def test_codes_are_url_safe(self) -> None:
        """Test that generated codes are URL-safe (no special chars)."""
        codes = generate_pkce_codes()

        # URL-safe base64 uses only alphanumeric, -, _
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in allowed_chars for c in codes.verifier)
        assert all(c in allowed_chars for c in codes.challenge)


class TestGenerateState:
    """Tests for state parameter generation."""

    def test_generates_non_empty_state(self) -> None:
        """Test that state is generated and non-empty."""
        state = generate_state()
        assert state is not None
        assert len(state) > 0

    def test_generates_unique_states(self) -> None:
        """Test that each call generates a unique state."""
        state1 = generate_state()
        state2 = generate_state()
        assert state1 != state2

    def test_state_is_url_safe(self) -> None:
        """Test that state is URL-safe."""
        state = generate_state()
        # URL-safe base64 uses only alphanumeric, -, _
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in allowed_chars for c in state)


class TestBuildAuthorizationUrl:
    """Tests for authorization URL building."""

    def test_builds_valid_url(self) -> None:
        """Test that a valid authorization URL is built."""
        codes = generate_pkce_codes()
        state = generate_state()

        url = build_authorization_url(
            client_id="test_client_id",
            redirect_uri="http://localhost:8765/callback",
            scopes=["bookmark.read", "tweet.read"],
            code_challenge=codes.challenge,
            state=state,
        )

        assert url.startswith("https://x.com/i/oauth2/authorize")
        assert "client_id=test_client_id" in url
        assert "redirect_uri=" in url
        assert "scope=bookmark.read" in url
        assert "code_challenge=" in url
        assert f"state={state}" in url
        assert "code_challenge_method=S256" in url

    def test_includes_all_scopes(self) -> None:
        """Test that all scopes are included."""
        codes = generate_pkce_codes()

        url = build_authorization_url(
            client_id="test_client_id",
            redirect_uri="http://localhost:8765/callback",
            scopes=["scope1", "scope2", "scope3"],
            code_challenge=codes.challenge,
            state="test_state",
        )

        # Scopes should be space-separated (URL encoded as +)
        assert "scope1" in url
        assert "scope2" in url
        assert "scope3" in url


class TestOAuth2Token:
    """Tests for OAuth2Token model."""

    def test_create_token(self) -> None:
        """Test creating a token."""
        token = OAuth2Token(
            access_token="test_access",
            refresh_token="test_refresh",
            token_type="bearer",
            expires_at=datetime(2024, 1, 1, 12, 0, 0),
            scope="bookmark.read tweet.read",
        )

        assert token.access_token == "test_access"
        assert token.refresh_token == "test_refresh"
        assert token.token_type == "bearer"
        assert token.scope == "bookmark.read tweet.read"

    def test_is_expired_returns_false_for_valid_token(
        self, sample_oauth_token: OAuth2Token
    ) -> None:
        """Test is_expired returns False for valid token."""
        assert sample_oauth_token.is_expired() is False

    def test_is_expired_returns_true_for_expired_token(
        self, expired_oauth_token: OAuth2Token
    ) -> None:
        """Test is_expired returns True for expired token."""
        assert expired_oauth_token.is_expired() is True

    def test_is_expired_considers_buffer(self) -> None:
        """Test that is_expired considers 60 second buffer."""
        # Token that expires in 30 seconds should be considered expired
        token = OAuth2Token(
            access_token="test",
            refresh_token=None,
            token_type="bearer",
            expires_at=datetime.now() + timedelta(seconds=30),
            scope="",
        )
        assert token.is_expired() is True

        # Token that expires in 120 seconds should not be expired
        token2 = OAuth2Token(
            access_token="test",
            refresh_token=None,
            token_type="bearer",
            expires_at=datetime.now() + timedelta(seconds=120),
            scope="",
        )
        assert token2.is_expired() is False

    def test_to_dict(self, sample_oauth_token: OAuth2Token) -> None:
        """Test converting token to dict."""
        data = sample_oauth_token.to_dict()

        assert data["access_token"] == sample_oauth_token.access_token
        assert data["refresh_token"] == sample_oauth_token.refresh_token
        assert data["token_type"] == sample_oauth_token.token_type
        assert data["scope"] == sample_oauth_token.scope
        assert "expires_at" in data

    def test_from_dict(self, sample_oauth_token: OAuth2Token) -> None:
        """Test creating token from dict."""
        data = sample_oauth_token.to_dict()
        restored = OAuth2Token.from_dict(data)

        assert restored.access_token == sample_oauth_token.access_token
        assert restored.refresh_token == sample_oauth_token.refresh_token
        assert restored.token_type == sample_oauth_token.token_type
        assert restored.scope == sample_oauth_token.scope

    def test_roundtrip_serialization(self, sample_oauth_token: OAuth2Token) -> None:
        """Test that token survives serialization roundtrip."""
        data = sample_oauth_token.to_dict()
        json_str = json.dumps(data)
        loaded_data = json.loads(json_str)
        restored = OAuth2Token.from_dict(loaded_data)

        assert restored.access_token == sample_oauth_token.access_token
        assert restored.refresh_token == sample_oauth_token.refresh_token


class TestSaveLoadToken:
    """Tests for token persistence."""

    def test_save_and_load_token(self, temp_dir: Path, sample_oauth_token: OAuth2Token) -> None:
        """Test saving and loading a token."""
        token_path = temp_dir / "token.json"

        save_token(sample_oauth_token, token_path)
        loaded = load_token(token_path)

        assert loaded is not None
        assert loaded.access_token == sample_oauth_token.access_token
        assert loaded.refresh_token == sample_oauth_token.refresh_token

    def test_load_nonexistent_token_returns_none(self, temp_dir: Path) -> None:
        """Test loading non-existent token returns None."""
        token_path = temp_dir / "nonexistent.json"
        loaded = load_token(token_path)
        assert loaded is None

    def test_load_invalid_json_returns_none(self, temp_dir: Path) -> None:
        """Test loading invalid JSON returns None."""
        token_path = temp_dir / "invalid.json"
        token_path.write_text("not valid json")

        loaded = load_token(token_path)
        assert loaded is None

    def test_load_incomplete_token_returns_none(self, temp_dir: Path) -> None:
        """Test loading incomplete token data returns None."""
        token_path = temp_dir / "incomplete.json"
        token_path.write_text('{"access_token": "test"}')  # Missing required fields

        loaded = load_token(token_path)
        assert loaded is None

    def test_save_creates_parent_directories(
        self, temp_dir: Path, sample_oauth_token: OAuth2Token
    ) -> None:
        """Test that save_token creates parent directories."""
        token_path = temp_dir / "nested" / "deep" / "token.json"

        save_token(sample_oauth_token, token_path)

        assert token_path.exists()
