"""Tests for configuration management.

This module tests configuration loading from env vars and config files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from x2raindrop_cli.config import (
    RaindropSettings,
    SourceSyncSettings,
    SyncSettings,
    XSettings,
    create_default_config,
    get_default_config_dir,
    get_default_config_path,
)
from x2raindrop_cli.models import BothBehavior, LinkMode


class TestGetDefaultPaths:
    """Tests for default path functions."""

    def test_get_default_config_dir(self) -> None:
        """Test default config directory (for state/tokens)."""
        config_dir = get_default_config_dir()
        assert config_dir.name == ".x2raindrop"

    def test_get_default_config_path(self) -> None:
        """Test default config file path (in project root)."""
        config_path = get_default_config_path()
        assert config_path.name == "config.toml"


class TestCreateDefaultConfig:
    """Tests for default config file creation."""

    def test_creates_config_file(self, temp_dir: Path) -> None:
        """Test that config file is created."""
        config_path = temp_dir / "config.toml"

        created = create_default_config(config_path)

        assert created == config_path
        assert config_path.exists()

    def test_creates_parent_directories(self, temp_dir: Path) -> None:
        """Test that parent directories are created."""
        config_path = temp_dir / "nested" / "deep" / "config.toml"

        create_default_config(config_path)

        assert config_path.exists()

    def test_config_contains_required_sections(self, temp_dir: Path) -> None:
        """Test that created config contains required sections."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)

        content = config_path.read_text()

        assert "[x]" in content
        assert "[raindrop]" in content
        assert "[sync]" in content
        assert "[sync.bookmarks]" in content
        assert "[sync.likes]" in content

    def test_config_contains_placeholder_values(self, temp_dir: Path) -> None:
        """Test that config contains placeholder values."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)

        content = config_path.read_text()

        assert "access_token" in content
        assert "client_id" in content
        assert "skip_existing_links" in content
        assert "like.read" in content
        assert "YOUR_RAINDROP_TOKEN" in content


class TestXSettings:
    """Tests for X settings."""

    def test_loads_from_env(self, monkeypatch: MonkeyPatch) -> None:
        """Test loading X settings from environment."""
        monkeypatch.setenv("X_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("X_CLIENT_SECRET", "test_secret")

        settings = XSettings()

        assert settings.client_id == "test_client_id"
        assert settings.client_secret == "test_secret"

    def test_direct_access_token(self, monkeypatch: MonkeyPatch) -> None:
        """Test direct access token authentication."""
        monkeypatch.setenv("X_ACCESS_TOKEN", "test_access_token")

        settings = XSettings()

        assert settings.access_token == "test_access_token"
        assert settings.has_direct_token() is True
        assert settings.get_direct_token() == "test_access_token"
        assert settings.can_use_pkce_flow() is False

    def test_direct_access_token_with_refresh_token(self, monkeypatch: MonkeyPatch) -> None:
        """Test direct access token can include refresh token."""
        monkeypatch.setenv("X_ACCESS_TOKEN", "test_access_token")
        monkeypatch.setenv("X_REFRESH_TOKEN", "test_refresh_token")

        settings = XSettings()

        assert settings.access_token == "test_access_token"
        assert settings.refresh_token == "test_refresh_token"
        assert settings.has_direct_token() is True
        assert settings.get_direct_token() == "test_access_token"

    def test_pkce_flow_with_client_id(self, monkeypatch: MonkeyPatch) -> None:
        """Test PKCE flow requires client_id."""
        monkeypatch.setenv("X_CLIENT_ID", "test_id")

        settings = XSettings()

        assert settings.can_use_pkce_flow() is True
        assert settings.has_direct_token() is False

    def test_default_redirect_uri(self) -> None:
        """Test default redirect URI."""
        settings = XSettings()

        assert "127.0.0.1" in settings.redirect_uri
        assert "callback" in settings.redirect_uri

    def test_default_scopes(self) -> None:
        """Test default scopes include required ones."""
        settings = XSettings()

        assert "bookmark.read" in settings.scopes
        assert "bookmark.write" in settings.scopes
        assert "like.read" in settings.scopes
        assert "like.write" in settings.scopes
        assert "tweet.read" in settings.scopes
        assert "users.read" in settings.scopes


class TestSourceSyncSettings:
    """Tests for per-source sync settings."""

    def test_default_values(self) -> None:
        """Test default values for source sync settings."""
        settings = SourceSyncSettings()

        assert settings.enabled is True
        assert settings.collection_id is None
        assert settings.tags == []
        assert settings.remove_from_x is False
        assert settings.skip_existing_links is True
        assert settings.link_mode == LinkMode.PERMALINK
        assert settings.both_behavior == BothBehavior.ONE_EXTERNAL_PLUS_NOTE

    def test_parse_tags_from_string(self) -> None:
        """Test parsing tags from comma-separated string."""
        settings = SourceSyncSettings(tags="tag1, tag2, tag3")

        assert settings.tags == ["tag1", "tag2", "tag3"]


class TestSyncSettings:
    """Tests for sync settings."""

    def test_default_values(self) -> None:
        """Test default values for sync settings."""
        settings = SyncSettings()

        assert settings.bookmarks.enabled is True
        assert settings.likes.enabled is False
        assert settings.bookmarks.collection_id is None
        assert settings.bookmarks.tags == ["x-bookmark", "auto-synced"]
        assert settings.likes.tags == ["x-like", "auto-synced"]
        assert settings.dry_run is False

    def test_migrates_legacy_flat_config(self) -> None:
        """Test legacy flat sync config is migrated to bookmarks."""
        settings = SyncSettings(
            collection_id=12345,
            tags=["legacy"],
            remove_from_x=True,
            link_mode="first_external_url",
        )

        assert settings.bookmarks.collection_id == 12345
        assert settings.bookmarks.tags == ["legacy"]
        assert settings.bookmarks.remove_from_x is True
        assert settings.bookmarks.link_mode == LinkMode.FIRST_EXTERNAL_URL

    def test_loads_nested_env(self, monkeypatch: MonkeyPatch) -> None:
        """Test loading nested sync settings from environment."""
        monkeypatch.setenv("SYNC_BOOKMARKS__COLLECTION_ID", "12345")
        monkeypatch.setenv("SYNC_LIKES__ENABLED", "true")
        monkeypatch.setenv("SYNC_LIKES__COLLECTION_ID", "67890")

        settings = SyncSettings()

        assert settings.bookmarks.collection_id == 12345
        assert settings.likes.enabled is True
        assert settings.likes.collection_id == 67890

    def test_validate_enabled_sources_requires_collection(self) -> None:
        """Test validation fails when enabled source lacks collection ID."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(enabled=True, collection_id=None),
            likes=SourceSyncSettings(enabled=False),
        )

        with pytest.raises(ValueError, match="bookmarks.collection_id"):
            settings.validate_enabled_sources()

    def test_validate_enabled_sources_rejects_system_all_collection(self) -> None:
        """Test validation rejects Raindrop collection 0 (All)."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(enabled=True, collection_id=0),
            likes=SourceSyncSettings(enabled=False),
        )

        with pytest.raises(ValueError, match="bookmarks.collection_id"):
            settings.validate_enabled_sources()

    def test_validate_enabled_sources_allows_unsorted(self) -> None:
        """Test validation allows Raindrop Unsorted collection (-1)."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(enabled=True, collection_id=-1),
            likes=SourceSyncSettings(enabled=False),
        )

        settings.validate_enabled_sources()

    def test_validate_enabled_sources_requires_one_source(self) -> None:
        """Test validation fails when no sources are enabled."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(enabled=False),
            likes=SourceSyncSettings(enabled=False),
        )

        with pytest.raises(ValueError, match="At least one sync source"):
            settings.validate_enabled_sources()

    def test_validate_enabled_sources_allows_collection_title(self) -> None:
        """Test validation accepts collection_title when collection_id is unset."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(
                enabled=True,
                collection_id=None,
                collection_title="My Collection",
            ),
            likes=SourceSyncSettings(enabled=False),
        )

        settings.validate_enabled_sources()


class TestRaindropSettings:
    """Tests for Raindrop settings."""

    def test_token_is_optional(self) -> None:
        """Test Raindrop token can be omitted for X-only commands."""
        settings = RaindropSettings()

        assert settings.token is None
