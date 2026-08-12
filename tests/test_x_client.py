"""Tests for X client.

This module tests the X API client and URL extraction logic.
"""

from __future__ import annotations

from datetime import datetime

from tests.fakes import MockXClient
from x2raindrop_cli.models import BookmarkItem


class TestMockXClient:
    """Tests for MockXClient."""

    def test_get_bookmarks_returns_configured(self, sample_bookmarks: list[BookmarkItem]) -> None:
        """Test that get_bookmarks returns configured bookmarks."""
        client = MockXClient(bookmarks=sample_bookmarks)

        bookmarks = list(client.get_bookmarks())

        assert len(bookmarks) == 3
        assert bookmarks[0].tweet_id == "1111111111"
        assert bookmarks[1].tweet_id == "2222222222"
        assert bookmarks[2].tweet_id == "3333333333"

    def test_get_bookmarks_empty(self) -> None:
        """Test get_bookmarks with no bookmarks."""
        client = MockXClient(bookmarks=[])

        bookmarks = list(client.get_bookmarks())

        assert len(bookmarks) == 0

    def test_get_bookmarks_max_results(self, sample_bookmarks: list[BookmarkItem]) -> None:
        """Test get_bookmarks respects max_results."""
        client = MockXClient(bookmarks=sample_bookmarks)

        bookmarks = list(client.get_bookmarks(max_results=2))

        assert len(bookmarks) == 2

    def test_get_authenticated_user_id(self) -> None:
        """Test get_authenticated_user_id returns configured ID."""
        client = MockXClient(user_id="custom_user_123")

        user_id = client.get_authenticated_user_id()

        assert user_id == "custom_user_123"

    def test_delete_bookmark_tracks_deletion(self) -> None:
        """Test delete_bookmark tracks the deletion."""
        client = MockXClient()

        result = client.delete_bookmark("tweet_123")

        assert result is True
        assert "tweet_123" in client.deleted_tweet_ids

    def test_delete_bookmark_multiple(self) -> None:
        """Test multiple delete_bookmark calls."""
        client = MockXClient()

        client.delete_bookmark("tweet_1")
        client.delete_bookmark("tweet_2")
        client.delete_bookmark("tweet_3")

        assert len(client.deleted_tweet_ids) == 3
        assert "tweet_1" in client.deleted_tweet_ids
        assert "tweet_2" in client.deleted_tweet_ids
        assert "tweet_3" in client.deleted_tweet_ids

    def test_unlike_post_tracks_unlike(self) -> None:
        """Test unlike_post tracks the unlike."""
        client = MockXClient()

        result = client.unlike_post("tweet_123")

        assert result is True
        assert "tweet_123" in client.unliked_tweet_ids

    def test_get_liked_posts_returns_configured(self, sample_bookmarks: list[BookmarkItem]) -> None:
        """Test that get_liked_posts returns configured liked posts."""
        client = MockXClient(liked_posts=sample_bookmarks)

        liked = list(client.get_liked_posts())

        assert len(liked) == 3
        assert liked[0].tweet_id == "1111111111"


class TestXClientParsing:
    """Tests for XClient tweet parsing helpers."""

    def test_parse_tweet_coerces_int_author_id(self) -> None:
        """Test author lookup works when API returns integer IDs."""
        from datetime import datetime, timedelta

        from x2raindrop_cli.x.auth_pkce import OAuth2Token
        from x2raindrop_cli.x.client import XClient

        token = OAuth2Token(
            access_token="test",
            refresh_token=None,
            token_type="bearer",
            expires_at=datetime.now() + timedelta(hours=1),
            scope="tweet.read",
        )
        client = XClient(token)
        try:
            bookmark = client._parse_tweet(
                {
                    "id": 12345,
                    "text": "Hello world",
                    "author_id": 99,
                    "created_at": "2024-01-01T00:00:00.000Z",
                },
                {"99": {"username": "alice", "name": "Alice"}},
            )
        finally:
            client.close()

        assert bookmark.tweet_id == "12345"
        assert bookmark.author_username == "alice"
        assert bookmark.permalink == "https://x.com/alice/status/12345"

    def test_extract_external_urls_handles_null_entities(self) -> None:
        """Test entities=None from XDK model_dump does not crash."""
        from datetime import datetime, timedelta

        from x2raindrop_cli.x.auth_pkce import OAuth2Token
        from x2raindrop_cli.x.client import XClient

        token = OAuth2Token(
            access_token="test",
            refresh_token=None,
            token_type="bearer",
            expires_at=datetime.now() + timedelta(hours=1),
            scope="tweet.read",
        )
        client = XClient(token)
        try:
            urls = client._extract_external_urls(
                {
                    "id": "1",
                    "text": "No links here",
                    "entities": None,
                }
            )
            assert urls == []

            urls_from_text = client._extract_external_urls(
                {
                    "id": "2",
                    "text": "See https://example.com/page",
                    "entities": None,
                }
            )
            assert urls_from_text == ["https://example.com/page"]

            urls_null_list = client._extract_external_urls(
                {
                    "id": "3",
                    "text": "See https://example.org/page",
                    "entities": {"urls": None},
                }
            )
            assert urls_null_list == ["https://example.org/page"]
        finally:
            client.close()


class TestBookmarkItemParsing:
    """Tests for BookmarkItem creation and parsing logic."""

    def test_bookmark_with_external_urls(self) -> None:
        """Test bookmark with external URLs."""
        bookmark = BookmarkItem(
            tweet_id="123",
            text="Check this out: https://example.com/article",
            author_username="user",
            author_name="User Name",
            created_at=datetime(2024, 1, 1),
            permalink="https://x.com/user/status/123",
            external_urls=["https://example.com/article"],
        )

        assert len(bookmark.external_urls) == 1
        assert "example.com" in bookmark.external_urls[0]

    def test_bookmark_with_multiple_external_urls(self) -> None:
        """Test bookmark with multiple external URLs."""
        bookmark = BookmarkItem(
            tweet_id="123",
            text="Links: https://first.com https://second.com",
            author_username="user",
            author_name=None,
            created_at=None,
            permalink="https://x.com/user/status/123",
            external_urls=["https://first.com", "https://second.com"],
        )

        assert len(bookmark.external_urls) == 2

    def test_bookmark_without_author(self) -> None:
        """Test bookmark without author info uses fallback permalink."""
        bookmark = BookmarkItem(
            tweet_id="123",
            text="Some tweet",
            author_username=None,
            author_name=None,
            created_at=None,
            permalink="https://x.com/i/status/123",
            external_urls=[],
        )

        assert "/i/status/" in bookmark.permalink

    def test_bookmark_get_title_formats_correctly(self) -> None:
        """Test get_title formats with author info."""
        bookmark = BookmarkItem(
            tweet_id="123",
            text="This is the tweet content",
            author_username="testuser",
            author_name="Test User",
            created_at=None,
            permalink="https://x.com/testuser/status/123",
            external_urls=[],
        )

        title = bookmark.get_title()

        assert "Test User" in title
        assert "@testuser" in title
        assert "This is the tweet content" in title

    def test_bookmark_get_title_without_author(self) -> None:
        """Test get_title without author info."""
        bookmark = BookmarkItem(
            tweet_id="123",
            text="This is the tweet content",
            author_username=None,
            author_name=None,
            created_at=None,
            permalink="https://x.com/i/status/123",
            external_urls=[],
        )

        title = bookmark.get_title()

        assert title == "This is the tweet content"
