"""Tests for sync service orchestration.

This module tests the sync service that coordinates X bookmarks
to Raindrop.io synchronization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from x2raindrop_cli.config import SourceSyncSettings, SyncSettings
from x2raindrop_cli.models import BookmarkItem, BothBehavior, LinkMode
from x2raindrop_cli.raindrop.client import MockRaindropClient
from x2raindrop_cli.state import InMemoryState
from x2raindrop_cli.sync.service import (
    SyncService,
    create_raindrop_requests,
    resolve_links,
)
from x2raindrop_cli.x.client import MockXClient

if TYPE_CHECKING:
    pass


class TestResolveLinks:
    """Tests for link resolution logic."""

    def test_permalink_mode(self, sample_bookmark: BookmarkItem) -> None:
        """Test PERMALINK mode returns just the permalink."""
        links = resolve_links(
            sample_bookmark,
            LinkMode.PERMALINK,
            BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        )

        assert len(links) == 1
        assert links[0][0] == sample_bookmark.permalink
        assert links[0][1] is None

    def test_first_external_url_mode_with_urls(self, sample_bookmark: BookmarkItem) -> None:
        """Test FIRST_EXTERNAL_URL mode with external URLs."""
        links = resolve_links(
            sample_bookmark,
            LinkMode.FIRST_EXTERNAL_URL,
            BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        )

        assert len(links) == 1
        assert links[0][0] == sample_bookmark.external_urls[0]
        assert sample_bookmark.permalink in links[0][1]  # Permalink in note

    def test_first_external_url_mode_without_urls(
        self, sample_bookmark_no_urls: BookmarkItem
    ) -> None:
        """Test FIRST_EXTERNAL_URL mode falls back to permalink."""
        links = resolve_links(
            sample_bookmark_no_urls,
            LinkMode.FIRST_EXTERNAL_URL,
            BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        )

        assert len(links) == 1
        assert links[0][0] == sample_bookmark_no_urls.permalink
        assert links[0][1] is None

    def test_both_mode_one_external_plus_note(self, sample_bookmark: BookmarkItem) -> None:
        """Test BOTH mode with ONE_EXTERNAL_PLUS_NOTE behavior."""
        links = resolve_links(
            sample_bookmark,
            LinkMode.BOTH,
            BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        )

        assert len(links) == 1
        assert links[0][0] == sample_bookmark.external_urls[0]
        assert sample_bookmark.permalink in links[0][1]

    def test_both_mode_two_raindrops(self, sample_bookmark: BookmarkItem) -> None:
        """Test BOTH mode with TWO_RAINDROPS behavior."""
        links = resolve_links(
            sample_bookmark,
            LinkMode.BOTH,
            BothBehavior.TWO_RAINDROPS,
        )

        assert len(links) == 2
        assert links[0][0] == sample_bookmark.external_urls[0]
        assert links[1][0] == sample_bookmark.permalink

    def test_both_mode_without_urls_falls_back(self, sample_bookmark_no_urls: BookmarkItem) -> None:
        """Test BOTH mode falls back to permalink when no external URLs."""
        links = resolve_links(
            sample_bookmark_no_urls,
            LinkMode.BOTH,
            BothBehavior.TWO_RAINDROPS,
        )

        assert len(links) == 1
        assert links[0][0] == sample_bookmark_no_urls.permalink


class TestCreateRaindropRequests:
    """Tests for creating Raindrop requests from bookmarks."""

    def test_creates_request_with_tags(
        self, sample_bookmark: BookmarkItem, sync_settings: SyncSettings
    ) -> None:
        """Test request includes configured tags."""
        requests = create_raindrop_requests(sample_bookmark, sync_settings.bookmarks)

        assert len(requests) == 1
        assert requests[0].tags == sync_settings.bookmarks.tags

    def test_creates_request_with_collection_id(
        self, sample_bookmark: BookmarkItem, sync_settings: SyncSettings
    ) -> None:
        """Test request includes collection ID."""
        requests = create_raindrop_requests(sample_bookmark, sync_settings.bookmarks)

        assert requests[0].collection_id == sync_settings.bookmarks.collection_id

    def test_creates_request_with_title(
        self, sample_bookmark: BookmarkItem, sync_settings: SyncSettings
    ) -> None:
        """Test request includes generated title."""
        requests = create_raindrop_requests(sample_bookmark, sync_settings.bookmarks)

        assert requests[0].title is not None
        assert "@testuser" in requests[0].title

    def test_creates_request_with_excerpt(
        self, sample_bookmark: BookmarkItem, sync_settings: SyncSettings
    ) -> None:
        """Test request includes tweet text as excerpt."""
        requests = create_raindrop_requests(sample_bookmark, sync_settings.bookmarks)

        assert requests[0].excerpt == sample_bookmark.text

    def test_creates_multiple_requests_for_both_two_raindrops(
        self,
        sample_bookmark: BookmarkItem,
        sync_settings_both_two_raindrops: SyncSettings,
    ) -> None:
        """Test creating multiple requests for TWO_RAINDROPS behavior."""
        requests = create_raindrop_requests(
            sample_bookmark,
            sync_settings_both_two_raindrops.bookmarks,
        )

        assert len(requests) == 2
        links = [r.link for r in requests]
        assert sample_bookmark.external_urls[0] in links
        assert sample_bookmark.permalink in links

    def test_raises_without_collection_id(self, sample_bookmark: BookmarkItem) -> None:
        """Test raises ValueError when collection_id is None."""
        settings = SourceSyncSettings(
            enabled=True,
            collection_id=None,
            tags=[],
            remove_from_x=False,
            link_mode=LinkMode.PERMALINK,
            both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
        )

        with pytest.raises(ValueError, match="collection_id must be set"):
            create_raindrop_requests(sample_bookmark, settings)


class TestSyncService:
    """Tests for SyncService orchestration."""

    def test_sync_creates_raindrops(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test that sync creates raindrops for each bookmark."""
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        result = service.sync()

        assert result.bookmarks.total == 3
        assert result.bookmarks.newly_synced == 3
        assert result.bookmarks.already_synced == 0
        assert result.bookmarks.failed == 0
        assert len(mock_raindrop_client.created_raindrops) == 3
        assert len(mock_raindrop_client.batch_create_calls) == 1
        assert len(mock_raindrop_client.batch_create_calls[0]) == 3

    def test_sync_skips_already_synced(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test that sync skips already synced bookmarks."""
        # Pre-mark one as synced
        in_memory_state.mark_synced("1111111111", ["https://example.com"], False)

        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        result = service.sync()

        assert result.bookmarks.total == 3
        assert result.bookmarks.newly_synced == 2
        assert result.bookmarks.already_synced == 1
        assert len(mock_raindrop_client.created_raindrops) == 2

    def test_sync_updates_state(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test that sync updates state for synced bookmarks."""
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        service.sync()

        assert in_memory_state.is_synced("1111111111")
        assert in_memory_state.is_synced("2222222222")
        assert in_memory_state.is_synced("3333333333")

    def test_sync_deletes_from_x_when_enabled(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_with_remove: SyncSettings,
    ) -> None:
        """Test that sync deletes from X when remove_from_x is enabled."""
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_with_remove,
        )

        result = service.sync()

        assert result.bookmarks.removed_from_x == 3
        assert len(mock_x_client.deleted_tweet_ids) == 3
        assert "1111111111" in mock_x_client.deleted_tweet_ids
        assert "2222222222" in mock_x_client.deleted_tweet_ids
        assert "3333333333" in mock_x_client.deleted_tweet_ids

    def test_sync_does_not_delete_when_disabled(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test that sync does not delete when remove_from_x is disabled."""
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        result = service.sync()

        assert result.bookmarks.removed_from_x == 0
        assert len(mock_x_client.deleted_tweet_ids) == 0

    def test_sync_dry_run_does_not_create(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_dry_run: SyncSettings,
    ) -> None:
        """Test that dry run does not create raindrops."""
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_dry_run,
        )

        result = service.sync()

        assert result.bookmarks.newly_synced == 3  # Counted as synced
        assert len(mock_raindrop_client.created_raindrops) == 0  # But not actually created

    def test_sync_with_progress_callback(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test that progress callback is called."""
        progress_calls: list[tuple[int, int, str]] = []

        def track_progress(current: int, total: int, message: str) -> None:
            progress_calls.append((current, total, message))

        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        service.sync(progress_callback=track_progress)

        # 4 calls: 1 initial "Fetched bookmarks" + 3 for each synced bookmark
        assert len(progress_calls) == 4
        # First call is for fetching
        assert progress_calls[0][2] == "Fetched bookmarks from X"
        # Check progress increases for sync calls
        for i, (current, total, _) in enumerate(progress_calls[1:], start=1):
            assert current == i
            assert total == 3

    def test_sync_with_first_external_url_mode(
        self,
        mock_x_client: MockXClient,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_first_external: SyncSettings,
    ) -> None:
        """Test sync with FIRST_EXTERNAL_URL link mode."""
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_first_external,
        )

        result = service.sync()

        assert result.bookmarks.newly_synced == 3

        # Check that external URLs are used when available
        created_links = [r.link for r in mock_raindrop_client.created_raindrops]
        assert "https://first.example.com" in created_links
        assert "https://third.example.com" in created_links
        # Bookmark without external URL should use permalink
        assert "https://x.com/user2/status/2222222222" in created_links

    def test_sync_handles_empty_bookmarks(
        self,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test sync handles case with no bookmarks."""
        empty_x_client = MockXClient(bookmarks=[])

        service = SyncService(
            x_client=empty_x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        result = service.sync()

        assert result.bookmarks.total == 0
        assert result.bookmarks.newly_synced == 0
        assert len(mock_raindrop_client.created_raindrops) == 0

    def test_sync_skips_links_that_already_exist_in_raindrop(
        self,
        mock_x_client: MockXClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test skipping bookmarks whose links already exist in Raindrop."""
        existing_link = "https://x.com/user2/status/2222222222"
        raindrop_client = MockRaindropClient(existing_links=[existing_link])
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        result = service.sync()

        assert result.bookmarks.total == 3
        assert result.bookmarks.newly_synced == 2
        assert result.bookmarks.already_synced == 1
        created_links = [request.link for request in raindrop_client.created_raindrops]
        assert existing_link not in created_links
        assert in_memory_state.is_synced("2222222222")

    def test_sync_can_disable_existing_link_check(
        self,
        mock_x_client: MockXClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test existing-link check can be disabled."""
        sync_settings.bookmarks.skip_existing_links = False
        existing_link = "https://x.com/user2/status/2222222222"
        raindrop_client = MockRaindropClient(existing_links=[existing_link])
        service = SyncService(
            x_client=mock_x_client,
            raindrop_client=raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        result = service.sync()

        assert result.bookmarks.total == 3
        assert result.bookmarks.newly_synced == 3
        assert result.bookmarks.already_synced == 0
        created_links = [request.link for request in raindrop_client.created_raindrops]
        assert existing_link in created_links


class TestSyncServiceLikes:
    """Tests for liked-post sync."""

    def test_sync_liked_posts(
        self,
        sample_bookmarks: list[BookmarkItem],
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_likes_only: SyncSettings,
    ) -> None:
        """Test syncing liked posts to Raindrop."""
        x_client = MockXClient(liked_posts=sample_bookmarks[:2])
        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_likes_only,
        )

        result = service.sync()

        assert result.bookmarks.total == 0
        assert result.likes.total == 2
        assert result.likes.newly_synced == 2
        assert len(mock_raindrop_client.created_raindrops) == 2
        for raindrop in mock_raindrop_client.created_raindrops:
            assert raindrop.collection_id == 200

    def test_sync_likes_tracks_state_separately(
        self,
        sample_bookmark: BookmarkItem,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_likes_only: SyncSettings,
    ) -> None:
        """Test likes and bookmarks use separate state keys."""
        from x2raindrop_cli.models import PostSource

        in_memory_state.mark_synced(
            sample_bookmark.tweet_id,
            ["https://example.com"],
            deleted_from_x=False,
            source=PostSource.BOOKMARKS,
        )

        x_client = MockXClient(liked_posts=[sample_bookmark])
        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_likes_only,
        )

        result = service.sync()

        assert result.likes.newly_synced == 1
        assert in_memory_state.is_synced(sample_bookmark.tweet_id, source=PostSource.LIKES)

    def test_sync_likes_unlikes_when_enabled(
        self,
        sample_bookmark: BookmarkItem,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
    ) -> None:
        """Test liked-post sync can unlike on X after creating raindrops."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(enabled=False),
            likes=SourceSyncSettings(
                enabled=True,
                collection_id=200,
                tags=["like-test"],
                remove_from_x=True,
                link_mode=LinkMode.PERMALINK,
                both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
            ),
        )
        x_client = MockXClient(liked_posts=[sample_bookmark])
        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=settings,
        )

        result = service.sync()

        assert result.likes.newly_synced == 1
        assert result.likes.removed_from_x == 1
        assert sample_bookmark.tweet_id in x_client.unliked_tweet_ids
        assert result.deleted_from_x == 1

    def test_sync_both_sources(
        self,
        sample_bookmarks: list[BookmarkItem],
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
    ) -> None:
        """Test syncing bookmarks and likes in one run."""
        settings = SyncSettings(
            bookmarks=SourceSyncSettings(
                enabled=True,
                collection_id=100,
                tags=["bookmark"],
                remove_from_x=False,
                link_mode=LinkMode.PERMALINK,
                both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
            ),
            likes=SourceSyncSettings(
                enabled=True,
                collection_id=200,
                tags=["like"],
                remove_from_x=False,
                link_mode=LinkMode.PERMALINK,
                both_behavior=BothBehavior.ONE_EXTERNAL_PLUS_NOTE,
            ),
        )
        x_client = MockXClient(
            bookmarks=sample_bookmarks[:1],
            liked_posts=sample_bookmarks[1:2],
        )
        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=settings,
        )

        result = service.sync()

        assert result.bookmarks.newly_synced == 1
        assert result.likes.newly_synced == 1
        assert result.newly_synced == 2
        assert len(mock_raindrop_client.created_raindrops) == 2
        collections = {r.collection_id for r in mock_raindrop_client.created_raindrops}
        assert collections == {100, 200}

    def test_remove_from_x_honors_false_return(
        self,
        sample_bookmark: BookmarkItem,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_with_remove: SyncSettings,
    ) -> None:
        """Test unsuccessful X removal is not counted as removed."""
        x_client = MockXClient(bookmarks=[sample_bookmark])

        def failing_delete(_tweet_id: str) -> bool:
            return False

        x_client.delete_bookmark = failing_delete  # type: ignore[method-assign]
        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_with_remove,
        )

        result = service.sync()

        assert result.bookmarks.newly_synced == 1
        assert result.bookmarks.removed_from_x == 0
        assert any("unsuccessful response" in error for error in result.bookmarks.errors)
        from x2raindrop_cli.models import PostSource

        record = in_memory_state.get_synced(sample_bookmark.tweet_id, source=PostSource.BOOKMARKS)
        assert record is not None
        assert record.deleted_from_x is False


class TestSyncServiceIntegration:
    """Integration-style tests for complete sync flows."""

    def test_full_sync_flow_with_both_two_raindrops(
        self,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings_both_two_raindrops: SyncSettings,
    ) -> None:
        """Test full sync with BOTH mode and TWO_RAINDROPS behavior."""
        # Create bookmarks - one with external URL, one without
        bookmarks = [
            BookmarkItem(
                tweet_id="111",
                text="Tweet with link https://external.com",
                author_username="user1",
                author_name="User 1",
                created_at=None,
                permalink="https://x.com/user1/status/111",
                external_urls=["https://external.com"],
            ),
            BookmarkItem(
                tweet_id="222",
                text="Tweet without link",
                author_username="user2",
                author_name="User 2",
                created_at=None,
                permalink="https://x.com/user2/status/222",
                external_urls=[],
            ),
        ]

        x_client = MockXClient(bookmarks=bookmarks)

        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings_both_two_raindrops,
        )

        result = service.sync()

        assert result.bookmarks.total == 2
        assert result.bookmarks.newly_synced == 2

        # First bookmark should create 2 raindrops (external + permalink)
        # Second bookmark should create 1 raindrop (permalink only)
        assert len(mock_raindrop_client.created_raindrops) == 3
        assert len(mock_raindrop_client.batch_create_calls) == 1
        assert len(mock_raindrop_client.batch_create_calls[0]) == 3

        created_links = [r.link for r in mock_raindrop_client.created_raindrops]
        assert "https://external.com" in created_links
        assert "https://x.com/user1/status/111" in created_links
        assert "https://x.com/user2/status/222" in created_links

    def test_idempotent_sync(
        self,
        mock_raindrop_client: MockRaindropClient,
        in_memory_state: InMemoryState,
        sync_settings: SyncSettings,
    ) -> None:
        """Test that running sync twice is idempotent."""
        bookmarks = [
            BookmarkItem(
                tweet_id="111",
                text="Test tweet",
                author_username="user",
                author_name=None,
                created_at=None,
                permalink="https://x.com/user/status/111",
                external_urls=[],
            ),
        ]

        x_client = MockXClient(bookmarks=bookmarks)

        service = SyncService(
            x_client=x_client,
            raindrop_client=mock_raindrop_client,
            state=in_memory_state,
            settings=sync_settings,
        )

        # First sync
        result1 = service.sync()
        assert result1.bookmarks.newly_synced == 1
        assert len(mock_raindrop_client.created_raindrops) == 1

        # Second sync - should skip
        result2 = service.sync()
        assert result2.bookmarks.newly_synced == 0
        assert result2.bookmarks.already_synced == 1
        assert len(mock_raindrop_client.created_raindrops) == 1  # Still just 1
