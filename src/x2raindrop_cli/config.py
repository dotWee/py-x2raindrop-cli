"""Configuration management using Pydantic Settings.

This module provides settings management that reads from environment
variables and an optional TOML config file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomli_w
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from x2raindrop_cli.models import BothBehavior, LinkMode

if TYPE_CHECKING:
    pass


def get_default_config_dir() -> Path:
    """Get the default configuration directory.

    Returns:
        Path to the data directory (.x2raindrop/ in the current working directory).
    """
    return Path.cwd() / ".x2raindrop"


def get_default_config_path() -> Path:
    """Get the default configuration file path.

    Returns:
        Path to the config file (config.toml in the current working directory).
    """
    return Path.cwd() / "config.toml"


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

    Supports two authentication methods:
    1. OAuth 2.0 PKCE flow (interactive browser login)
    2. Direct access token (for automation or pre-existing tokens)

    Attributes:
        client_id: OAuth2 client ID from X Developer Portal (required for PKCE flow).
        client_secret: Optional OAuth2 client secret (for confidential apps).
        redirect_uri: OAuth2 redirect URI for PKCE flow.
        token_path: Path to store the OAuth2 tokens.
        scopes: OAuth2 scopes to request.
        access_token: Direct access token (alternative to PKCE flow).
        refresh_token: Refresh token for direct access token refresh (optional).
        bearer_token: App-only bearer token (limited functionality, read-only).
    """

    model_config = SettingsConfigDict(
        env_prefix="X_",
        env_file=".env",
        extra="ignore",
    )

    # OAuth 2.0 PKCE settings (for interactive login)
    client_id: str | None = Field(None, description="X OAuth2 Client ID")
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
        default=[
            "bookmark.read",
            "bookmark.write",
            "like.read",
            "like.write",
            "tweet.read",
            "users.read",
            "offline.access",
        ],
        description="OAuth2 scopes to request",
    )

    # Direct token authentication (alternative to PKCE)
    access_token: str | None = Field(
        None,
        description="Direct OAuth2 access token (skips browser login)",
    )
    refresh_token: str | None = Field(
        None,
        description="Direct OAuth2 refresh token (enables automatic access token refresh)",
    )
    bearer_token: str | None = Field(
        None,
        description="App-only bearer token (limited functionality)",
    )

    def has_direct_token(self) -> bool:
        """Check if a direct token is configured.

        Returns:
            True if access_token or bearer_token is set.
        """
        return bool(self.access_token or self.bearer_token)

    def get_direct_token(self) -> str | None:
        """Get the direct token if configured.

        Prefers access_token over bearer_token.

        Returns:
            The token string or None.
        """
        return self.access_token or self.bearer_token

    def can_use_pkce_flow(self) -> bool:
        """Check if PKCE flow can be used.

        Returns:
            True if client_id is configured.
        """
        return bool(self.client_id)


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


_LEGACY_SYNC_SOURCE_FIELDS = (
    "collection_id",
    "collection_title",
    "tags",
    "remove_from_x",
    "skip_existing_links",
    "link_mode",
    "both_behavior",
)


def _default_bookmarks_settings() -> SourceSyncSettings:
    """Default settings for bookmark sync."""
    return SourceSyncSettings(
        enabled=True,
        tags=["x-bookmark", "auto-synced"],
    )


def _default_likes_settings() -> SourceSyncSettings:
    """Default settings for liked-post sync."""
    return SourceSyncSettings(
        enabled=False,
        tags=["x-like", "auto-synced"],
    )


class SourceSyncSettings(BaseModel):
    """Per-source sync behavior settings for bookmarks or likes.

    Attributes:
        enabled: Whether this source is synced.
        collection_id: Target Raindrop collection ID.
        collection_title: Optional collection title (for lookup).
        tags: Tags to apply to created Raindrops.
        remove_from_x: Whether to remove from X after syncing (unbookmark/unlike).
        skip_existing_links: Whether to skip links that already exist in Raindrop.
        link_mode: How to determine the Raindrop link.
        both_behavior: Behavior when link_mode is 'both'.
    """

    enabled: bool = Field(True, description="Whether this source is synced")
    collection_id: int | None = Field(None, description="Target Raindrop collection ID")
    collection_title: str | None = Field(None, description="Collection title for lookup")
    tags: list[str] = Field(default_factory=list, description="Tags to apply")
    remove_from_x: bool = Field(False, description="Remove from X after sync")
    skip_existing_links: bool = Field(
        True,
        description="Skip links that already exist in target Raindrop collection",
    )
    link_mode: LinkMode = Field(LinkMode.PERMALINK, description="Link resolution mode")
    both_behavior: BothBehavior = Field(
        BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        description="Behavior when link_mode is 'both'",
    )

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
            return [tag.strip() for tag in v.split(",") if tag.strip()]
        return v if v else []


class SyncSettings(BaseSettings):
    """Sync behavior settings for bookmarks and likes.

    Attributes:
        bookmarks: Settings for syncing X bookmarks.
        likes: Settings for syncing X liked posts.
        state_path: Path to the sync state file.
        dry_run: If True, don't make any changes.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYNC_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    bookmarks: SourceSyncSettings = Field(default_factory=_default_bookmarks_settings)
    likes: SourceSyncSettings = Field(default_factory=_default_likes_settings)
    state_path: Path = Field(
        default_factory=get_default_state_path,
        description="Path to sync state file",
    )
    dry_run: bool = Field(False, description="Dry run mode")

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_flat_config(cls, data: Any) -> Any:
        """Migrate legacy flat sync settings into the bookmarks section."""
        if not isinstance(data, dict):
            return data

        if "bookmarks" not in data:
            legacy_bookmarks: dict[str, Any] = {}
            for field in _LEGACY_SYNC_SOURCE_FIELDS:
                if field in data:
                    legacy_bookmarks[field] = data.pop(field)
            if legacy_bookmarks:
                data["bookmarks"] = legacy_bookmarks

        return data

    def any_enabled(self) -> bool:
        """Return True if at least one sync source is enabled."""
        return self.bookmarks.enabled or self.likes.enabled

    def validate_enabled_sources(self) -> None:
        """Validate that each enabled source has a usable collection ID.

        Collection ID ``0`` is Raindrop's system "All" collection and cannot be
        used as a create target, so it is treated as unset.

        Raises:
            ValueError: If an enabled source is missing collection_id.
        """
        if self.bookmarks.enabled and not self.bookmarks.collection_id:
            raise ValueError(
                "bookmarks.collection_id must be set to a real collection "
                "(not 0/All) when bookmark sync is enabled"
            )
        if self.likes.enabled and not self.likes.collection_id:
            raise ValueError(
                "likes.collection_id must be set to a real collection "
                "(not 0/All) when like sync is enabled"
            )
        if not self.any_enabled():
            raise ValueError("At least one sync source (bookmarks or likes) must be enabled")


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
            # Option 1: Direct access token (simplest, no browser login needed)
            # Get this from X Developer Portal or existing OAuth flow
            "access_token": "",
            # Optional: provide refresh token to auto-refresh access token
            "refresh_token": "",
            # Option 2: OAuth PKCE flow (interactive browser login)
            # Set client_id to enable `x2raindrop x login`
            "client_id": "",
            "client_secret": "",
            "redirect_uri": "http://127.0.0.1:8765/callback",
            "scopes": [
                "bookmark.read",
                "bookmark.write",
                "like.read",
                "like.write",
                "tweet.read",
                "users.read",
                "offline.access",
            ],
        },
        "raindrop": {
            "token": "YOUR_RAINDROP_TOKEN",
        },
        "sync": {
            "dry_run": False,
            "bookmarks": {
                "enabled": True,
                # Set collection_id to a real Raindrop collection ID (not 0/All).
                # Use -1 for Unsorted. Example: collection_id = 12345
                "collection_title": "",
                "tags": ["x-bookmark", "auto-synced"],
                "remove_from_x": False,
                "skip_existing_links": True,
                "link_mode": "permalink",
                "both_behavior": "one_external_plus_note",
            },
            "likes": {
                "enabled": False,
                # Set collection_id when enabling likes sync.
                "collection_title": "",
                "tags": ["x-like", "auto-synced"],
                "remove_from_x": False,
                "skip_existing_links": True,
                "link_mode": "permalink",
                "both_behavior": "one_external_plus_note",
            },
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
