"""Local state management for sync idempotency.

This module provides a JSON-based state store to track which bookmarks
and liked posts have already been synced, enabling idempotent sync operations.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from x2raindrop_cli.models import PostSource, SyncedBookmark

logger = structlog.get_logger(__name__)

_STATE_VERSION = 2


class SyncState:
    """Manages sync state for idempotency.

    Tracks which X bookmarks and liked posts have been synced to Raindrop.io,
    allowing the sync to skip already-processed items per source.
    """

    def __init__(self, path: Path) -> None:
        """Initialize state manager.

        Args:
            path: Path to the state file.
        """
        self.path = path
        self._synced: dict[PostSource, dict[str, SyncedBookmark]] = {
            PostSource.BOOKMARKS: {},
            PostSource.LIKES: {},
        }
        self._dirty = False

    def load(self) -> None:
        """Load state from disk."""
        if not self.path.exists():
            logger.debug("State file not found, starting fresh", path=str(self.path))
            return

        try:
            with open(self.path) as f:
                data = json.load(f)

            version = data.get("version", 1)
            if version < _STATE_VERSION or "synced" in data:
                # Migrate legacy flat tweet-id map into bookmarks source.
                self._load_legacy_v1(data.get("synced", {}))
                # Persist v2 layout on next save even if no new syncs occur.
                self._dirty = True
            else:
                self._load_source_records(PostSource.BOOKMARKS, data.get("bookmarks", {}))
                self._load_source_records(PostSource.LIKES, data.get("likes", {}))

            logger.debug(
                "Loaded state",
                path=str(self.path),
                bookmark_count=len(self._synced[PostSource.BOOKMARKS]),
                like_count=len(self._synced[PostSource.LIKES]),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(
                "Failed to load state, starting fresh",
                path=str(self.path),
                error=str(e),
            )
            self._synced = {
                PostSource.BOOKMARKS: {},
                PostSource.LIKES: {},
            }

    def _load_legacy_v1(self, synced: dict[str, Any]) -> None:
        """Load version 1 state keyed only by tweet ID (bookmarks)."""
        self._load_source_records(PostSource.BOOKMARKS, synced)

    def _load_source_records(self, source: PostSource, records: dict[str, Any]) -> None:
        """Load synced records for one source."""
        for tweet_id, record in records.items():
            self._synced[source][tweet_id] = SyncedBookmark(
                tweet_id=record["tweet_id"],
                raindrop_links=record.get("raindrop_links", []),
                synced_at=datetime.fromisoformat(record["synced_at"]),
                deleted_from_x=record.get("deleted_from_x", False),
            )

    def save(self) -> None:
        """Save state to disk."""
        if not self._dirty:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": _STATE_VERSION,
            "last_updated": datetime.now(UTC).isoformat(),
            "bookmarks": self._serialize_source(PostSource.BOOKMARKS),
            "likes": self._serialize_source(PostSource.LIKES),
        }

        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

        self._dirty = False
        logger.debug(
            "Saved state",
            path=str(self.path),
            bookmark_count=len(self._synced[PostSource.BOOKMARKS]),
            like_count=len(self._synced[PostSource.LIKES]),
        )

    def _serialize_source(self, source: PostSource) -> dict[str, Any]:
        """Serialize synced records for one source."""
        return {
            tweet_id: {
                "tweet_id": record.tweet_id,
                "raindrop_links": record.raindrop_links,
                "synced_at": record.synced_at.isoformat(),
                "deleted_from_x": record.deleted_from_x,
            }
            for tweet_id, record in self._synced[source].items()
        }

    def is_synced(self, tweet_id: str, source: PostSource = PostSource.BOOKMARKS) -> bool:
        """Check if a tweet has been synced for a source.

        Args:
            tweet_id: X tweet ID to check.
            source: Bookmark or like source.

        Returns:
            True if already synced.
        """
        return tweet_id in self._synced[source]

    def get_synced(
        self,
        tweet_id: str,
        source: PostSource = PostSource.BOOKMARKS,
    ) -> SyncedBookmark | None:
        """Get sync record for a tweet and source.

        Args:
            tweet_id: X tweet ID.
            source: Bookmark or like source.

        Returns:
            SyncedBookmark if found, None otherwise.
        """
        return self._synced[source].get(tweet_id)

    def mark_synced(
        self,
        tweet_id: str,
        raindrop_links: list[str],
        deleted_from_x: bool = False,
        source: PostSource = PostSource.BOOKMARKS,
    ) -> None:
        """Mark a tweet as synced for a source.

        Args:
            tweet_id: X tweet ID.
            raindrop_links: URLs of created Raindrop items.
            deleted_from_x: Whether it was deleted from X.
            source: Bookmark or like source.
        """
        self._synced[source][tweet_id] = SyncedBookmark(
            tweet_id=tweet_id,
            raindrop_links=raindrop_links,
            synced_at=datetime.now(UTC),
            deleted_from_x=deleted_from_x,
        )
        self._dirty = True
        logger.debug(
            "Marked as synced",
            tweet_id=tweet_id,
            source=source.value,
            raindrop_links=raindrop_links,
            deleted_from_x=deleted_from_x,
        )

    def mark_deleted(
        self,
        tweet_id: str,
        source: PostSource = PostSource.BOOKMARKS,
    ) -> None:
        """Mark a synced tweet as deleted from X.

        Args:
            tweet_id: X tweet ID.
            source: Bookmark or like source.
        """
        if tweet_id in self._synced[source]:
            old_record = self._synced[source][tweet_id]
            self._synced[source][tweet_id] = SyncedBookmark(
                tweet_id=old_record.tweet_id,
                raindrop_links=old_record.raindrop_links,
                synced_at=old_record.synced_at,
                deleted_from_x=True,
            )
            self._dirty = True

    def get_all_synced(self, source: PostSource | None = None) -> list[SyncedBookmark]:
        """Get all synced records, optionally filtered by source.

        Args:
            source: Optional source filter.

        Returns:
            List of synced records.
        """
        if source is not None:
            return list(self._synced[source].values())
        return [record for records in self._synced.values() for record in records.values()]

    def get_synced_count(self, source: PostSource | None = None) -> int:
        """Get count of synced items, optionally filtered by source.

        Args:
            source: Optional source filter.

        Returns:
            Number of synced items.
        """
        if source is not None:
            return len(self._synced[source])
        return sum(len(records) for records in self._synced.values())

    def clear(self) -> None:
        """Clear all state (for testing or reset)."""
        self._synced = {
            PostSource.BOOKMARKS: {},
            PostSource.LIKES: {},
        }
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
