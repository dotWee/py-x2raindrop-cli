"""Local state management for sync idempotency.

This module provides a JSON-based state store to track which bookmarks
have already been synced, enabling idempotent sync operations.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from x2raindrop_cli.models import SyncedBookmark

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class SyncState:
    """Manages sync state for idempotency.

    Tracks which X bookmarks have been synced to Raindrop.io,
    allowing the sync to skip already-processed items.
    """

    def __init__(self, path: Path) -> None:
        """Initialize state manager.

        Args:
            path: Path to the state file.
        """
        self.path = path
        self._synced: dict[str, SyncedBookmark] = {}
        self._dirty = False

    def load(self) -> None:
        """Load state from disk."""
        if not self.path.exists():
            logger.debug("State file not found, starting fresh", path=str(self.path))
            return

        try:
            with open(self.path) as f:
                data = json.load(f)

            for tweet_id, record in data.get("synced", {}).items():
                self._synced[tweet_id] = SyncedBookmark(
                    tweet_id=record["tweet_id"],
                    raindrop_links=record.get("raindrop_links", []),
                    synced_at=datetime.fromisoformat(record["synced_at"]),
                    deleted_from_x=record.get("deleted_from_x", False),
                )

            logger.debug(
                "Loaded state",
                path=str(self.path),
                synced_count=len(self._synced),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(
                "Failed to load state, starting fresh",
                path=str(self.path),
                error=str(e),
            )
            self._synced = {}

    def save(self) -> None:
        """Save state to disk."""
        if not self._dirty:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": 1,
            "last_updated": datetime.now().isoformat(),
            "synced": {
                tweet_id: {
                    "tweet_id": record.tweet_id,
                    "raindrop_links": record.raindrop_links,
                    "synced_at": record.synced_at.isoformat(),
                    "deleted_from_x": record.deleted_from_x,
                }
                for tweet_id, record in self._synced.items()
            },
        }

        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

        self._dirty = False
        logger.debug("Saved state", path=str(self.path), synced_count=len(self._synced))

    def is_synced(self, tweet_id: str) -> bool:
        """Check if a tweet has been synced.

        Args:
            tweet_id: X tweet ID to check.

        Returns:
            True if already synced.
        """
        return tweet_id in self._synced

    def get_synced(self, tweet_id: str) -> SyncedBookmark | None:
        """Get sync record for a tweet.

        Args:
            tweet_id: X tweet ID.

        Returns:
            SyncedBookmark if found, None otherwise.
        """
        return self._synced.get(tweet_id)

    def mark_synced(
        self,
        tweet_id: str,
        raindrop_links: list[str],
        deleted_from_x: bool = False,
    ) -> None:
        """Mark a tweet as synced.

        Args:
            tweet_id: X tweet ID.
            raindrop_links: URLs of created Raindrop items.
            deleted_from_x: Whether it was deleted from X.
        """
        self._synced[tweet_id] = SyncedBookmark(
            tweet_id=tweet_id,
            raindrop_links=raindrop_links,
            synced_at=datetime.now(),
            deleted_from_x=deleted_from_x,
        )
        self._dirty = True
        logger.debug(
            "Marked as synced",
            tweet_id=tweet_id,
            raindrop_links=raindrop_links,
            deleted_from_x=deleted_from_x,
        )

    def mark_deleted(self, tweet_id: str) -> None:
        """Mark a synced tweet as deleted from X.

        Args:
            tweet_id: X tweet ID.
        """
        if tweet_id in self._synced:
            old_record = self._synced[tweet_id]
            self._synced[tweet_id] = SyncedBookmark(
                tweet_id=old_record.tweet_id,
                raindrop_links=old_record.raindrop_links,
                synced_at=old_record.synced_at,
                deleted_from_x=True,
            )
            self._dirty = True

    def get_all_synced(self) -> list[SyncedBookmark]:
        """Get all synced records.

        Returns:
            List of all synced bookmarks.
        """
        return list(self._synced.values())

    def get_synced_count(self) -> int:
        """Get count of synced items.

        Returns:
            Number of synced bookmarks.
        """
        return len(self._synced)

    def clear(self) -> None:
        """Clear all state (for testing or reset)."""
        self._synced = {}
        self._dirty = True


class InMemoryState(SyncState):
    """In-memory state for testing (no file I/O)."""

    def __init__(self) -> None:
        """Initialize in-memory state."""
        super().__init__(Path("/dev/null"))

    def load(self) -> None:
        """No-op for in-memory state."""
        pass

    def save(self) -> None:
        """No-op for in-memory state."""
        pass
