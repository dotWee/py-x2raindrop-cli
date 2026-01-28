"""Shared pytest fixtures for the test suite.

This module provides common fixtures used across multiple test files.
"""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from x2raindrop_cli.config import SyncSettings
from x2raindrop_cli.models import BookmarkItem, BothBehavior, LinkMode
from x2raindrop_cli.raindrop.client import MockRaindropClient, RaindropCollection
from x2raindrop_cli.state import InMemoryState
from x2raindrop_cli.x.auth_pkce import OAuth2Token
from x2raindrop_cli.x.client import MockXClient

if TYPE_CHECKING:
    pass


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files.

    Yields:
        Path to the temporary directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_bookmark() -> BookmarkItem:
    """Create a sample bookmark for testing.

    Returns:
        A sample BookmarkItem instance.
    """
    return BookmarkItem(
        tweet_id="1234567890",
        text="Check out this awesome article! https://example.com/article",
        author_username="testuser",
        author_name="Test User",
        created_at=datetime(2024, 1, 15, 12, 0, 0),
        permalink="https://x.com/testuser/status/1234567890",
        external_urls=["https://example.com/article"],
    )


@pytest.fixture
def sample_bookmark_no_urls() -> BookmarkItem:
    """Create a sample bookmark without external URLs.

    Returns:
        A BookmarkItem with no external URLs.
    """
    return BookmarkItem(
        tweet_id="9876543210",
        text="Just a regular tweet without any external links.",
        author_username="anotheruser",
        author_name="Another User",
        created_at=datetime(2024, 1, 16, 14, 30, 0),
        permalink="https://x.com/anotheruser/status/9876543210",
        external_urls=[],
    )


@pytest.fixture
def sample_bookmarks() -> list[BookmarkItem]:
    """Create a list of sample bookmarks.

    Returns:
        List of BookmarkItem instances.
    """
    return [
        BookmarkItem(
            tweet_id="1111111111",
            text="First bookmark with link https://first.example.com",
            author_username="user1",
            author_name="User One",
            created_at=datetime(2024, 1, 1, 10, 0, 0),
            permalink="https://x.com/user1/status/1111111111",
            external_urls=["https://first.example.com"],
        ),
        BookmarkItem(
            tweet_id="2222222222",
            text="Second bookmark without external links",
            author_username="user2",
            author_name="User Two",
            created_at=datetime(2024, 1, 2, 11, 0, 0),
            permalink="https://x.com/user2/status/2222222222",
            external_urls=[],
        ),
        BookmarkItem(
            tweet_id="3333333333",
            text="Third bookmark https://third.example.com and https://another.example.com",
            author_username="user3",
            author_name="User Three",
            created_at=datetime(2024, 1, 3, 12, 0, 0),
            permalink="https://x.com/user3/status/3333333333",
            external_urls=["https://third.example.com", "https://another.example.com"],
        ),
    ]


@pytest.fixture
def sample_oauth_token() -> OAuth2Token:
    """Create a sample OAuth2 token.

    Returns:
        An OAuth2Token instance.
    """
    return OAuth2Token(
        access_token="test_access_token_12345",
        refresh_token="test_refresh_token_67890",
        token_type="bearer",
        expires_at=datetime.now() + timedelta(hours=2),
        scope="bookmark.read bookmark.write tweet.read users.read offline.access",
    )


@pytest.fixture
def expired_oauth_token() -> OAuth2Token:
    """Create an expired OAuth2 token.

    Returns:
        An expired OAuth2Token instance.
    """
    return OAuth2Token(
        access_token="expired_access_token",
        refresh_token="test_refresh_token",
        token_type="bearer",
        expires_at=datetime.now() - timedelta(hours=1),
        scope="bookmark.read bookmark.write tweet.read users.read offline.access",
    )


@pytest.fixture
def mock_x_client(sample_bookmarks: list[BookmarkItem]) -> MockXClient:
    """Create a mock X client with sample bookmarks.

    Args:
        sample_bookmarks: List of sample bookmarks.

    Returns:
        MockXClient instance.
    """
    return MockXClient(bookmarks=sample_bookmarks, user_id="test_user_123")


@pytest.fixture
def mock_raindrop_client() -> MockRaindropClient:
    """Create a mock Raindrop client.

    Returns:
        MockRaindropClient instance.
    """
    return MockRaindropClient(
        collections=[
            RaindropCollection(id=100, title="My Collection", count=50),
            RaindropCollection(id=200, title="Another Collection", count=25),
            RaindropCollection(id=-1, title="Unsorted", count=10),
        ]
    )


@pytest.fixture
def in_memory_state() -> InMemoryState:
    """Create an in-memory state for testing.

    Returns:
        InMemoryState instance.
    """
    return InMemoryState()


@pytest.fixture
def sync_settings() -> SyncSettings:
    """Create default sync settings for testing.

    Returns:
        SyncSettings instance.
    """
    return SyncSettings(
        collection_id=100,
        collection_title="My Collection",
        tags=["test", "automated"],
        remove_from_x=False,
        link_mode=LinkMode.PERMALINK,
        both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        dry_run=False,
    )


@pytest.fixture
def sync_settings_with_remove() -> SyncSettings:
    """Create sync settings with remove_from_x enabled.

    Returns:
        SyncSettings instance with remove enabled.
    """
    return SyncSettings(
        collection_id=100,
        tags=["test"],
        remove_from_x=True,
        link_mode=LinkMode.PERMALINK,
        both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        dry_run=False,
    )


@pytest.fixture
def sync_settings_first_external() -> SyncSettings:
    """Create sync settings with first_external_url mode.

    Returns:
        SyncSettings with link_mode=FIRST_EXTERNAL_URL.
    """
    return SyncSettings(
        collection_id=100,
        tags=["test"],
        remove_from_x=False,
        link_mode=LinkMode.FIRST_EXTERNAL_URL,
        both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        dry_run=False,
    )


@pytest.fixture
def sync_settings_both() -> SyncSettings:
    """Create sync settings with both link mode.

    Returns:
        SyncSettings with link_mode=BOTH.
    """
    return SyncSettings(
        collection_id=100,
        tags=["test"],
        remove_from_x=False,
        link_mode=LinkMode.BOTH,
        both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        dry_run=False,
    )


@pytest.fixture
def sync_settings_both_two_raindrops() -> SyncSettings:
    """Create sync settings with both mode and two raindrops behavior.

    Returns:
        SyncSettings with link_mode=BOTH and both_behavior=TWO_RAINDROPS.
    """
    return SyncSettings(
        collection_id=100,
        tags=["test"],
        remove_from_x=False,
        link_mode=LinkMode.BOTH,
        both_behavior=BothBehavior.TWO_RAINDROPS,
        dry_run=False,
    )


@pytest.fixture
def sync_settings_dry_run() -> SyncSettings:
    """Create sync settings with dry_run enabled.

    Returns:
        SyncSettings with dry_run=True.
    """
    return SyncSettings(
        collection_id=100,
        tags=["test"],
        remove_from_x=False,
        link_mode=LinkMode.PERMALINK,
        both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        dry_run=True,
    )
