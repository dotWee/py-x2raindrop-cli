"""Tests for Raindrop client.

This module tests the Raindrop.io API client wrapper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from py_x_bookmarks_to_raindrop_sync.models import RaindropCreateRequest
from py_x_bookmarks_to_raindrop_sync.raindrop.client import (
    MockRaindropClient,
    RaindropCollection,
)

if TYPE_CHECKING:
    pass


class TestRaindropCollection:
    """Tests for RaindropCollection dataclass."""

    def test_create_collection(self) -> None:
        """Test creating a collection."""
        collection = RaindropCollection(
            id=123,
            title="My Collection",
            count=50,
            parent_id=None,
        )

        assert collection.id == 123
        assert collection.title == "My Collection"
        assert collection.count == 50
        assert collection.parent_id is None

    def test_create_nested_collection(self) -> None:
        """Test creating a nested collection."""
        collection = RaindropCollection(
            id=456,
            title="Sub Collection",
            count=10,
            parent_id=123,
        )

        assert collection.parent_id == 123


class TestMockRaindropClient:
    """Tests for MockRaindropClient."""

    def test_list_collections_returns_configured(self) -> None:
        """Test list_collections returns configured collections."""
        collections = [
            RaindropCollection(id=1, title="Collection 1", count=10),
            RaindropCollection(id=2, title="Collection 2", count=20),
        ]
        client = MockRaindropClient(collections=collections)

        result = client.list_collections()

        assert len(result) == 2
        assert result[0].title == "Collection 1"
        assert result[1].title == "Collection 2"

    def test_list_collections_default(self) -> None:
        """Test list_collections with default collections."""
        client = MockRaindropClient()

        result = client.list_collections()

        assert len(result) >= 1  # Has default collections

    def test_get_collection_by_title_found(self) -> None:
        """Test finding collection by title."""
        collections = [
            RaindropCollection(id=1, title="My Collection", count=10),
        ]
        client = MockRaindropClient(collections=collections)

        result = client.get_collection_by_title("My Collection")

        assert result is not None
        assert result.id == 1

    def test_get_collection_by_title_case_insensitive(self) -> None:
        """Test finding collection by title is case insensitive."""
        collections = [
            RaindropCollection(id=1, title="My Collection", count=10),
        ]
        client = MockRaindropClient(collections=collections)

        result = client.get_collection_by_title("my collection")

        assert result is not None
        assert result.id == 1

    def test_get_collection_by_title_not_found(self) -> None:
        """Test finding collection by title when not found."""
        client = MockRaindropClient(collections=[])

        result = client.get_collection_by_title("Nonexistent")

        assert result is None

    def test_create_raindrop_tracks_request(self) -> None:
        """Test create_raindrop tracks the request."""
        client = MockRaindropClient()

        request = RaindropCreateRequest(
            link="https://example.com",
            title="Example",
            excerpt="An example link",
            tags=["test"],
            collection_id=100,
            note="Note",
            source_tweet_id="12345",
        )

        result = client.create_raindrop(request)

        assert result.link == "https://example.com"
        assert len(client.created_raindrops) == 1
        assert client.created_raindrops[0].link == "https://example.com"

    def test_create_raindrop_returns_incrementing_ids(self) -> None:
        """Test create_raindrop returns incrementing IDs."""
        client = MockRaindropClient()

        request1 = RaindropCreateRequest(
            link="https://example1.com",
            collection_id=100,
            source_tweet_id="1",
        )
        request2 = RaindropCreateRequest(
            link="https://example2.com",
            collection_id=100,
            source_tweet_id="2",
        )

        result1 = client.create_raindrop(request1)
        result2 = client.create_raindrop(request2)

        assert result1.id == 1
        assert result2.id == 2

    def test_check_link_exists_after_create(self) -> None:
        """Test check_link_exists after creating a raindrop."""
        client = MockRaindropClient()

        request = RaindropCreateRequest(
            link="https://example.com",
            collection_id=100,
            source_tweet_id="1",
        )
        client.create_raindrop(request)

        assert client.check_link_exists("https://example.com") is True
        assert client.check_link_exists("https://other.com") is False

    def test_check_link_exists_empty(self) -> None:
        """Test check_link_exists when no raindrops created."""
        client = MockRaindropClient()

        assert client.check_link_exists("https://example.com") is False


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
            note="A note",
            source_tweet_id="12345",
        )

        assert request.link == "https://example.com"
        assert request.title == "Example Title"
        assert request.excerpt == "Example excerpt"
        assert request.tags == ["tag1", "tag2"]
        assert request.collection_id == 100
        assert request.note == "A note"
        assert request.source_tweet_id == "12345"

    def test_create_minimal(self) -> None:
        """Test creating request with minimal fields."""
        request = RaindropCreateRequest(
            link="https://example.com",
            collection_id=100,
            source_tweet_id="12345",
        )

        assert request.link == "https://example.com"
        assert request.title is None
        assert request.excerpt is None
        assert request.tags == []
        assert request.note is None
