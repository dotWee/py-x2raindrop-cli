"""Tests for sync state management.

This module tests the local state store for tracking synced bookmarks.
"""

from __future__ import annotations

from pathlib import Path

from x2raindrop_cli.state import InMemoryState, SyncState


class TestSyncState:
    """Tests for SyncState class."""

    def test_load_nonexistent_file(self, temp_dir: Path) -> None:
        """Test loading state from non-existent file."""
        state = SyncState(temp_dir / "state.json")
        state.load()  # Should not raise

        assert state.get_synced_count() == 0

    def test_mark_synced(self, temp_dir: Path) -> None:
        """Test marking a bookmark as synced."""
        state = SyncState(temp_dir / "state.json")

        state.mark_synced(
            tweet_id="12345",
            raindrop_links=["https://example.com"],
            deleted_from_x=False,
        )

        assert state.is_synced("12345")
        assert not state.is_synced("other")

    def test_get_synced(self, temp_dir: Path) -> None:
        """Test getting synced record."""
        state = SyncState(temp_dir / "state.json")
        state.mark_synced("12345", ["https://example.com"], False)

        record = state.get_synced("12345")

        assert record is not None
        assert record.tweet_id == "12345"
        assert record.raindrop_links == ["https://example.com"]
        assert record.deleted_from_x is False

    def test_get_synced_nonexistent(self, temp_dir: Path) -> None:
        """Test getting non-existent record returns None."""
        state = SyncState(temp_dir / "state.json")

        record = state.get_synced("nonexistent")

        assert record is None

    def test_mark_deleted(self, temp_dir: Path) -> None:
        """Test marking a synced bookmark as deleted from X."""
        state = SyncState(temp_dir / "state.json")
        state.mark_synced("12345", ["https://example.com"], False)

        state.mark_deleted("12345")

        record = state.get_synced("12345")
        assert record is not None
        assert record.deleted_from_x is True

    def test_mark_deleted_nonexistent_does_nothing(self, temp_dir: Path) -> None:
        """Test marking non-existent record as deleted does nothing."""
        state = SyncState(temp_dir / "state.json")

        state.mark_deleted("nonexistent")  # Should not raise

        assert state.get_synced("nonexistent") is None

    def test_save_and_load(self, temp_dir: Path) -> None:
        """Test saving and loading state."""
        from x2raindrop_cli.models import PostSource

        state_path = temp_dir / "state.json"
        state = SyncState(state_path)

        state.mark_synced("tweet1", ["https://link1.com"], False, source=PostSource.BOOKMARKS)
        state.mark_synced("tweet2", ["https://link2.com"], True, source=PostSource.LIKES)
        state.save()

        state2 = SyncState(state_path)
        state2.load()

        assert state2.is_synced("tweet1", source=PostSource.BOOKMARKS)
        assert state2.is_synced("tweet2", source=PostSource.LIKES)

        record1 = state2.get_synced("tweet1", source=PostSource.BOOKMARKS)
        assert record1 is not None
        assert record1.raindrop_links == ["https://link1.com"]
        assert record1.deleted_from_x is False

        record2 = state2.get_synced("tweet2", source=PostSource.LIKES)
        assert record2 is not None
        assert record2.deleted_from_x is True

    def test_load_legacy_v1_state(self, temp_dir: Path) -> None:
        """Test loading legacy v1 state migrates bookmarks."""
        state_path = temp_dir / "state.json"
        state_path.write_text(
            """{
  "version": 1,
  "synced": {
    "12345": {
      "tweet_id": "12345",
      "raindrop_links": ["https://example.com"],
      "synced_at": "2024-01-01T00:00:00",
      "deleted_from_x": false
    }
  }
}"""
        )

        state = SyncState(state_path)
        state.load()

        assert state.is_synced("12345")
        record = state.get_synced("12345")
        assert record is not None
        assert record.raindrop_links == ["https://example.com"]

        # Legacy load marks dirty so the next save upgrades to v2 layout.
        state.save()
        reloaded = SyncState(state_path)
        reloaded.load()
        assert reloaded.is_synced("12345")
        saved = state_path.read_text()
        assert '"version": 2' in saved
        assert '"bookmarks"' in saved
        assert '"synced"' not in saved

    def test_save_creates_parent_dirs(self, temp_dir: Path) -> None:
        """Test that save creates parent directories."""
        state_path = temp_dir / "nested" / "deep" / "state.json"
        state = SyncState(state_path)

        state.mark_synced("12345", [], False)
        state.save()

        assert state_path.exists()

    def test_get_all_synced(self, temp_dir: Path) -> None:
        """Test getting all synced records."""
        state = SyncState(temp_dir / "state.json")
        state.mark_synced("tweet1", [], False)
        state.mark_synced("tweet2", [], False)
        state.mark_synced("tweet3", [], False)

        all_synced = state.get_all_synced()

        assert len(all_synced) == 3
        tweet_ids = {r.tweet_id for r in all_synced}
        assert tweet_ids == {"tweet1", "tweet2", "tweet3"}

    def test_get_synced_count(self, temp_dir: Path) -> None:
        """Test getting synced count."""
        state = SyncState(temp_dir / "state.json")

        assert state.get_synced_count() == 0

        state.mark_synced("tweet1", [], False)
        assert state.get_synced_count() == 1

        state.mark_synced("tweet2", [], False)
        assert state.get_synced_count() == 2

    def test_clear(self, temp_dir: Path) -> None:
        """Test clearing all state."""
        state = SyncState(temp_dir / "state.json")
        state.mark_synced("tweet1", [], False)
        state.mark_synced("tweet2", [], False)

        state.clear()

        assert state.get_synced_count() == 0
        assert not state.is_synced("tweet1")
        assert not state.is_synced("tweet2")

    def test_load_corrupted_json_starts_fresh(self, temp_dir: Path) -> None:
        """Test that corrupted JSON file results in fresh state."""
        state_path = temp_dir / "state.json"
        state_path.write_text("not valid json {{{")

        state = SyncState(state_path)
        state.load()

        assert state.get_synced_count() == 0

    def test_load_invalid_data_starts_fresh(self, temp_dir: Path) -> None:
        """Test that invalid data structure results in fresh state."""
        state_path = temp_dir / "state.json"
        state_path.write_text('{"synced": {"tweet1": {"bad": "data"}}}')

        state = SyncState(state_path)
        state.load()

        # Should start fresh due to invalid data structure
        assert state.get_synced_count() == 0


class TestInMemoryState:
    """Tests for InMemoryState class."""

    def test_load_does_nothing(self) -> None:
        """Test that load is a no-op for in-memory state."""
        state = InMemoryState()
        state.load()  # Should not raise

    def test_save_does_nothing(self) -> None:
        """Test that save is a no-op for in-memory state."""
        state = InMemoryState()
        state.mark_synced("12345", [], False)
        state.save()  # Should not raise

    def test_functions_like_sync_state(self) -> None:
        """Test that in-memory state functions like regular state."""
        state = InMemoryState()

        state.mark_synced("tweet1", ["https://link1.com"], False)
        state.mark_synced("tweet2", ["https://link2.com"], True)

        assert state.is_synced("tweet1")
        assert state.is_synced("tweet2")
        assert not state.is_synced("tweet3")

        record = state.get_synced("tweet1")
        assert record is not None
        assert record.raindrop_links == ["https://link1.com"]
