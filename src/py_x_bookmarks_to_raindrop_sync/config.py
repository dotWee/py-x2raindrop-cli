"""Configuration management using Pydantic Settings.

This module provides settings management that reads from environment
variables and an optional TOML config file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomli_w
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from py_x_bookmarks_to_raindrop_sync.models import BothBehavior, LinkMode

if TYPE_CHECKING:
    pass


def get_default_config_dir() -> Path:
    """Get the default configuration directory.

    Returns:
        Path to the config directory (~/.config/py-x-bookmarks-to-raindrop-sync/).
    """
    return Path.home() / ".config" / "py-x-bookmarks-to-raindrop-sync"


def get_default_config_path() -> Path:
    """Get the default configuration file path.

    Returns:
        Path to the config file.
    """
    return get_default_config_dir() / "config.toml"


def get_default_state_path() -> Path:
    """Get the default state file path.

    Returns:
        Path to the state file.
    """
    return get_default_config_dir() / "state.json"


def get_default_token_path() -> Path:
    """Get the default X token storage path.

    Returns:
        Path to the token file.
    """
    return get_default_config_dir() / "x_token.json"


class XSettings(BaseSettings):
    """X (Twitter) API settings.

    Attributes:
        client_id: OAuth2 client ID from X Developer Portal.
        client_secret: Optional OAuth2 client secret (for confidential apps).
        redirect_uri: OAuth2 redirect URI for PKCE flow.
        token_path: Path to store the OAuth2 tokens.
        scopes: OAuth2 scopes to request.
    """

    model_config = SettingsConfigDict(
        env_prefix="X_",
        env_file=".env",
        extra="ignore",
    )

    client_id: str = Field(..., description="X OAuth2 Client ID")
    client_secret: str | None = Field(None, description="X OAuth2 Client Secret (optional)")
    redirect_uri: str = Field(
        "http://127.0.0.1:8765/callback",
        description="OAuth2 redirect URI",
    )
    token_path: Path = Field(
        default_factory=get_default_token_path,
        description="Path to store X OAuth2 tokens",
    )
    scopes: list[str] = Field(
        default=["bookmark.read", "bookmark.write", "tweet.read", "users.read", "offline.access"],
        description="OAuth2 scopes to request",
    )


class RaindropSettings(BaseSettings):
    """Raindrop.io API settings.

    Attributes:
        token: Raindrop.io API test token.
    """

    model_config = SettingsConfigDict(
        env_prefix="RAINDROP_",
        env_file=".env",
        extra="ignore",
    )

    token: str = Field(..., description="Raindrop.io API token")


class SyncSettings(BaseSettings):
    """Sync behavior settings.

    Attributes:
        collection_id: Target Raindrop collection ID.
        collection_title: Optional collection title (for lookup).
        tags: Tags to apply to created Raindrops.
        remove_from_x: Whether to remove from X after syncing.
        link_mode: How to determine the Raindrop link.
        both_behavior: Behavior when link_mode is 'both'.
        state_path: Path to the sync state file.
        dry_run: If True, don't make any changes.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYNC_",
        env_file=".env",
        extra="ignore",
    )

    collection_id: int | None = Field(None, description="Target Raindrop collection ID")
    collection_title: str | None = Field(None, description="Collection title for lookup")
    tags: list[str] = Field(default_factory=list, description="Tags to apply")
    remove_from_x: bool = Field(False, description="Remove from X after sync")
    link_mode: LinkMode = Field(LinkMode.PERMALINK, description="Link resolution mode")
    both_behavior: BothBehavior = Field(
        BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        description="Behavior when link_mode is 'both'",
    )
    state_path: Path = Field(
        default_factory=get_default_state_path,
        description="Path to sync state file",
    )
    dry_run: bool = Field(False, description="Dry run mode")

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v: Any) -> list[str]:
        """Parse tags from string or list.

        Args:
            v: Input value (string or list).

        Returns:
            List of tag strings.
        """
        if isinstance(v, str):
            # Handle comma-separated string
            return [tag.strip() for tag in v.split(",") if tag.strip()]
        return v if v else []


class Settings(BaseSettings):
    """Main application settings combining all sub-settings.

    Attributes:
        x: X (Twitter) API settings.
        raindrop: Raindrop.io API settings.
        sync: Sync behavior settings.
        config_path: Path to the config file.
        log_level: Logging level.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    x: XSettings = Field(default_factory=XSettings)
    raindrop: RaindropSettings = Field(default_factory=RaindropSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    config_path: Path = Field(
        default_factory=get_default_config_path,
        description="Path to config file",
    )
    log_level: str = Field("INFO", description="Logging level")

    @model_validator(mode="before")
    @classmethod
    def load_config_file(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Load settings from config file if it exists.

        Args:
            data: Input data dict.

        Returns:
            Merged data dict with config file values.
        """
        config_path = data.get("config_path") or get_default_config_path()
        if isinstance(config_path, str):
            config_path = Path(config_path)

        if config_path.exists():
            with open(config_path, "rb") as f:
                file_config = tomllib.load(f)

            # Merge file config with provided data (data takes precedence)
            merged = _deep_merge(file_config, data)
            return merged

        return data

    @classmethod
    def from_file(cls, config_path: Path | None = None) -> Settings:
        """Load settings from a config file.

        Args:
            config_path: Path to the config file. Uses default if None.

        Returns:
            Settings instance.
        """
        if config_path is None:
            config_path = get_default_config_path()

        return cls(config_path=config_path)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries.

    Args:
        base: Base dictionary.
        override: Override dictionary (values take precedence).

    Returns:
        Merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif value is not None:
            result[key] = value
    return result


def create_default_config(path: Path | None = None) -> Path:
    """Create a default config file template.

    Args:
        path: Path to create the config file. Uses default if None.

    Returns:
        Path to the created config file.
    """
    if path is None:
        path = get_default_config_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    default_config = {
        "log_level": "INFO",
        "x": {
            "client_id": "YOUR_X_CLIENT_ID",
            "client_secret": "",
            "redirect_uri": "http://127.0.0.1:8765/callback",
            "scopes": [
                "bookmark.read",
                "bookmark.write",
                "tweet.read",
                "users.read",
                "offline.access",
            ],
        },
        "raindrop": {
            "token": "YOUR_RAINDROP_TOKEN",
        },
        "sync": {
            "collection_id": 0,
            "collection_title": "",
            "tags": ["x-bookmark", "auto-synced"],
            "remove_from_x": False,
            "link_mode": "permalink",
            "both_behavior": "one_external_plus_note",
            "dry_run": False,
        },
    }

    with open(path, "wb") as f:
        tomli_w.dump(default_config, f)

    return path


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from environment and config file.

    This is the main entry point for loading configuration.

    Args:
        config_path: Optional path to config file.

    Returns:
        Configured Settings instance.
    """
    init_data: dict[str, Any] = {}
    if config_path:
        init_data["config_path"] = config_path

    return Settings(**init_data)
