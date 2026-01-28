"""Tests for configuration management.

This module tests configuration loading from env vars and config files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from py_x_bookmarks_to_raindrop_sync.config import (
    SyncSettings,
    XSettings,
    create_default_config,
    get_default_config_dir,
    get_default_config_path,
)
from py_x_bookmarks_to_raindrop_sync.models import BothBehavior, LinkMode

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


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

    def test_config_contains_placeholder_values(self, temp_dir: Path) -> None:
        """Test that config contains placeholder values."""
        config_path = temp_dir / "config.toml"
        create_default_config(config_path)

        content = config_path.read_text()

        # X section has empty placeholders for both auth methods
        assert "access_token" in content
        assert "client_id" in content
        # Raindrop still has placeholder
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
        assert "tweet.read" in settings.scopes
        assert "users.read" in settings.scopes


class TestSyncSettings:
    """Tests for sync settings."""

    def test_default_values(self) -> None:
        """Test default values for sync settings."""
        settings = SyncSettings()

        assert settings.collection_id is None
        assert settings.tags == []
        assert settings.remove_from_x is False
        assert settings.link_mode == LinkMode.PERMALINK
        assert settings.both_behavior == BothBehavior.ONE_EXTERNAL_PLUS_NOTE
        assert settings.dry_run is False

    def test_parse_tags_from_string(self) -> None:
        """Test parsing tags from comma-separated string."""
        settings = SyncSettings(tags="tag1, tag2, tag3")

        assert settings.tags == ["tag1", "tag2", "tag3"]

    def test_parse_tags_from_list(self) -> None:
        """Test parsing tags from list."""
        settings = SyncSettings(tags=["tag1", "tag2"])

        assert settings.tags == ["tag1", "tag2"]

    def test_parse_empty_tags(self) -> None:
        """Test parsing empty tags."""
        settings = SyncSettings(tags="")
        assert settings.tags == []

        settings2 = SyncSettings(tags=None)
        assert settings2.tags == []

    def test_loads_from_env(self, monkeypatch: MonkeyPatch) -> None:
        """Test loading sync settings from environment."""
        monkeypatch.setenv("SYNC_COLLECTION_ID", "12345")
        monkeypatch.setenv("SYNC_TAGS", '["auto", "synced"]')  # JSON format for list
        monkeypatch.setenv("SYNC_REMOVE_FROM_X", "true")
        monkeypatch.setenv("SYNC_LINK_MODE", "first_external_url")

        settings = SyncSettings()

        assert settings.collection_id == 12345
        assert settings.tags == ["auto", "synced"]
        assert settings.remove_from_x is True
        assert settings.link_mode == LinkMode.FIRST_EXTERNAL_URL

    def test_link_mode_enum_values(self) -> None:
        """Test setting link_mode with enum values."""
        settings1 = SyncSettings(link_mode=LinkMode.PERMALINK)
        assert settings1.link_mode == LinkMode.PERMALINK

        settings2 = SyncSettings(link_mode=LinkMode.FIRST_EXTERNAL_URL)
        assert settings2.link_mode == LinkMode.FIRST_EXTERNAL_URL

        settings3 = SyncSettings(link_mode=LinkMode.BOTH)
        assert settings3.link_mode == LinkMode.BOTH

    def test_both_behavior_enum_values(self) -> None:
        """Test setting both_behavior with enum values."""
        settings1 = SyncSettings(both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE)
        assert settings1.both_behavior == BothBehavior.ONE_EXTERNAL_PLUS_NOTE

        settings2 = SyncSettings(both_behavior=BothBehavior.TWO_RAINDROPS)
        assert settings2.both_behavior == BothBehavior.TWO_RAINDROPS
