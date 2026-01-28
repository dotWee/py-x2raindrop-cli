"""Tests for domain models.

This module tests the Pydantic models used throughout the application.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from x2raindrop_cli.models import (
    BookmarkItem,
    BothBehavior,
    LinkMode,
    RaindropCreateRequest,
    SyncedBookmark,
    SyncResult,
)

if TYPE_CHECKING:
    pass


class TestLinkMode:
    """Tests for LinkMode enum."""

    def test_permalink_value(self) -> None:
        """Test PERMALINK enum value."""
        assert LinkMode.PERMALINK.value == "permalink"

    def test_first_external_url_value(self) -> None:
        """Test FIRST_EXTERNAL_URL enum value."""
        assert LinkMode.FIRST_EXTERNAL_URL.value == "first_external_url"

    def test_both_value(self) -> None:
        """Test BOTH enum value."""
        assert LinkMode.BOTH.value == "both"

    def test_from_string(self) -> None:
        """Test creating LinkMode from string."""
        assert LinkMode("permalink") == LinkMode.PERMALINK
        assert LinkMode("first_external_url") == LinkMode.FIRST_EXTERNAL_URL
        assert LinkMode("both") == LinkMode.BOTH


class TestBothBehavior:
    """Tests for BothBehavior enum."""

    def test_one_external_plus_note_value(self) -> None:
        """Test ONE_EXTERNAL_PLUS_NOTE enum value."""
        assert BothBehavior.ONE_EXTERNAL_PLUS_NOTE.value == "one_external_plus_note"

    def test_two_raindrops_value(self) -> None:
        """Test TWO_RAINDROPS enum value."""
        assert BothBehavior.TWO_RAINDROPS.value == "two_raindrops"


class TestBookmarkItem:
    """Tests for BookmarkItem model."""

    def test_create_with_all_fields(self) -> None:
        """Test creating BookmarkItem with all fields."""
        bookmark = BookmarkItem(
            tweet_id="12345",
            text="Test tweet text",
            author_username="testuser",
            author_name="Test User",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            permalink="https://x.com/testuser/status/12345",
            external_urls=["https://example.com"],
        )

        assert bookmark.tweet_id == "12345"
        assert bookmark.text == "Test tweet text"
        assert bookmark.author_username == "testuser"
        assert bookmark.author_name == "Test User"
        assert bookmark.permalink == "https://x.com/testuser/status/12345"
        assert bookmark.external_urls == ["https://example.com"]

    def test_create_minimal(self) -> None:
        """Test creating BookmarkItem with minimal fields."""
        bookmark = BookmarkItem(
            tweet_id="12345",
            text="Test",
            permalink="https://x.com/i/status/12345",
        )

        assert bookmark.tweet_id == "12345"
        assert bookmark.author_username is None
        assert bookmark.author_name is None
        assert bookmark.created_at is None
        assert bookmark.external_urls == []

    def test_get_title_with_author(self, sample_bookmark: BookmarkItem) -> None:
        """Test get_title with author info."""
        title = sample_bookmark.get_title()
        assert "@testuser" in title
        assert "Test User" in title

    def test_get_title_without_author(self) -> None:
        """Test get_title without author info."""
        bookmark = BookmarkItem(
            tweet_id="12345",
            text="Just some tweet text",
            permalink="https://x.com/i/status/12345",
        )
        title = bookmark.get_title()
        assert title == "Just some tweet text"

    def test_get_title_truncates_long_text(self) -> None:
        """Test that get_title truncates very long text."""
        long_text = "x" * 200
        bookmark = BookmarkItem(
            tweet_id="12345",
            text=long_text,
            permalink="https://x.com/i/status/12345",
        )
        title = bookmark.get_title()
        assert len(title) <= 150

    def test_immutable(self, sample_bookmark: BookmarkItem) -> None:
        """Test that BookmarkItem is immutable (frozen)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            sample_bookmark.tweet_id = "new_id"  # type: ignore


class TestRaindropCreateRequest:
    """Tests for RaindropCreateRequest model."""

    def test_create_with_all_fields(self) -> None:
        """Test creating request with all fields."""
        request = RaindropCreateRequest(
            link="https://example.com",
            title="Example Title",
            excerpt="Example excerpt",
            tags=["tag1", "tag2"],
            collection_id=100,
            note="Additional note",
            source_tweet_id="12345",
        )

        assert request.link == "https://example.com"
        assert request.title == "Example Title"
        assert request.tags == ["tag1", "tag2"]
        assert request.collection_id == 100
        assert request.note == "Additional note"
        assert request.source_tweet_id == "12345"

    def test_create_minimal(self) -> None:
        """Test creating request with minimal fields."""
        request = RaindropCreateRequest(
            link="https://example.com",
            collection_id=100,
            source_tweet_id="12345",
        )

        assert request.title is None
        assert request.excerpt is None
        assert request.tags == []
        assert request.note is None


class TestSyncedBookmark:
    """Tests for SyncedBookmark model."""

    def test_create(self) -> None:
        """Test creating SyncedBookmark."""
        synced = SyncedBookmark(
            tweet_id="12345",
            raindrop_links=["https://raindrop.io/item/1"],
            deleted_from_x=True,
        )

        assert synced.tweet_id == "12345"
        assert synced.raindrop_links == ["https://raindrop.io/item/1"]
        assert synced.deleted_from_x is True
        assert synced.synced_at is not None

    def test_default_values(self) -> None:
        """Test default values."""
        synced = SyncedBookmark(tweet_id="12345")

        assert synced.raindrop_links == []
        assert synced.deleted_from_x is False


class TestSyncResult:
    """Tests for SyncResult model."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = SyncResult()

        assert result.total_bookmarks == 0
        assert result.already_synced == 0
        assert result.newly_synced == 0
        assert result.failed == 0
        assert result.deleted_from_x == 0
        assert result.errors == []

    def test_add_error(self) -> None:
        """Test adding errors."""
        result = SyncResult()
        result.add_error("Error 1")
        result.add_error("Error 2")

        assert len(result.errors) == 2
        assert "Error 1" in result.errors
        assert "Error 2" in result.errors

    def test_modify_counts(self) -> None:
        """Test modifying result counts."""
        result = SyncResult()
        result.total_bookmarks = 10
        result.newly_synced = 5
        result.already_synced = 3
        result.failed = 2

        assert result.total_bookmarks == 10
        assert result.newly_synced == 5
        assert result.already_synced == 3
        assert result.failed == 2
