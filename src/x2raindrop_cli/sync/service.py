"""Sync orchestration service.

This module coordinates the sync process between X bookmarks/likes
and Raindrop.io, handling transformation, deduplication,
and optional removal from X.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import structlog

from x2raindrop_cli.config import SourceSyncSettings, SyncSettings
from x2raindrop_cli.models import (
    BookmarkItem,
    BothBehavior,
    LinkMode,
    PostSource,
    RaindropCreateRequest,
    SourceSyncResult,
    SyncResult,
)
from x2raindrop_cli.raindrop.client import RaindropClientProtocol, normalize_link
from x2raindrop_cli.state import SyncState
from x2raindrop_cli.x.client import XClientProtocol

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


# Type for progress callback: (current, total, message)
ProgressCallback = Callable[[int, int, str], None]

_SOURCE_LABELS = {
    PostSource.BOOKMARKS: "bookmarks",
    PostSource.LIKES: "likes",
}


def resolve_links(
    bookmark: BookmarkItem,
    link_mode: LinkMode,
    both_behavior: BothBehavior,
) -> list[tuple[str, str | None]]:
    """Resolve which links to create for a bookmark.

    Args:
        bookmark: The X bookmark to process.
        link_mode: How to determine the link(s).
        both_behavior: Behavior when link_mode is BOTH.

    Returns:
        List of (link, note) tuples. Note contains additional info
        to store (e.g., permalink when using external URL).
    """
    links: list[tuple[str, str | None]] = []

    if link_mode == LinkMode.PERMALINK:
        links.append((bookmark.permalink, None))

    elif link_mode == LinkMode.FIRST_EXTERNAL_URL:
        if bookmark.external_urls:
            links.append((bookmark.external_urls[0], f"From: {bookmark.permalink}"))
        else:
            links.append((bookmark.permalink, None))

    elif link_mode == LinkMode.BOTH:
        if bookmark.external_urls:
            if both_behavior == BothBehavior.ONE_EXTERNAL_PLUS_NOTE:
                links.append((bookmark.external_urls[0], f"X Post: {bookmark.permalink}"))
            else:
                links.append((bookmark.external_urls[0], f"From: {bookmark.permalink}"))
                links.append((bookmark.permalink, None))
        else:
            links.append((bookmark.permalink, None))

    return links


def create_raindrop_requests(
    bookmark: BookmarkItem,
    settings: SourceSyncSettings,
) -> list[RaindropCreateRequest]:
    """Create Raindrop request(s) from a bookmark or liked post.

    Args:
        bookmark: X post to convert.
        settings: Source-specific sync settings.

    Returns:
        List of RaindropCreateRequest objects.
    """
    if settings.collection_id is None:
        raise ValueError("collection_id must be set in sync settings")

    links = resolve_links(bookmark, settings.link_mode, settings.both_behavior)
    requests: list[RaindropCreateRequest] = []

    for link, note in links:
        title = bookmark.get_title()
        excerpt = bookmark.text

        requests.append(
            RaindropCreateRequest(
                link=link,
                title=title,
                excerpt=excerpt,
                tags=list(settings.tags),
                collection_id=settings.collection_id,
                note=note,
                source_tweet_id=bookmark.tweet_id,
            )
        )

    return requests


class SyncService:
    """Orchestrates syncing X bookmarks and likes to Raindrop.io.

    This service:
    1. Fetches enabled post sources from X
    2. Filters out already-synced items using local state
    3. Creates Raindrop items for new posts
    4. Optionally removes from X after sync
    5. Updates local state for idempotency
    """

    def __init__(
        self,
        x_client: XClientProtocol,
        raindrop_client: RaindropClientProtocol,
        state: SyncState,
        settings: SyncSettings,
    ) -> None:
        """Initialize the sync service.

        Args:
            x_client: Client for X API.
            raindrop_client: Client for Raindrop.io API.
            state: State manager for idempotency.
            settings: Sync configuration.
        """
        self.x_client = x_client
        self.raindrop_client = raindrop_client
        self.state = state
        self.settings = settings
        self._collection_link_cache: dict[int, set[str]] = {}

    def sync(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncResult:
        """Run the sync process for all enabled sources.

        Args:
            progress_callback: Optional callback for progress updates.

        Returns:
            SyncResult with statistics per source.
        """
        result = SyncResult()
        self.settings.validate_enabled_sources()
        self.state.load()
        self._collection_link_cache.clear()

        if self.settings.bookmarks.enabled:
            result.bookmarks = self._sync_source(
                source=PostSource.BOOKMARKS,
                source_settings=self.settings.bookmarks,
                fetch_items=self.x_client.get_bookmarks,
                remove_from_x=self.x_client.delete_bookmark,
                progress_callback=progress_callback,
            )

        if self.settings.likes.enabled:
            result.likes = self._sync_source(
                source=PostSource.LIKES,
                source_settings=self.settings.likes,
                fetch_items=self.x_client.get_liked_posts,
                remove_from_x=self.x_client.unlike_post,
                progress_callback=progress_callback,
            )

        self.state.save()

        logger.info(
            "Sync complete",
            bookmarks_total=result.bookmarks.total,
            bookmarks_new=result.bookmarks.newly_synced,
            likes_total=result.likes.total,
            likes_new=result.likes.newly_synced,
            failed=result.failed,
        )

        return result

    def _existing_links_for(self, collection_id: int) -> set[str]:
        """Load (and cache) normalized links already in a Raindrop collection."""
        cached = self._collection_link_cache.get(collection_id)
        if cached is not None:
            return cached

        links = self.raindrop_client.list_collection_links(collection_id)
        self._collection_link_cache[collection_id] = links
        return links

    def _remember_created_links(self, collection_id: int, links: list[str]) -> None:
        """Add newly created links to the in-run collection inventory cache."""
        cached = self._collection_link_cache.get(collection_id)
        if cached is None:
            return
        for link in links:
            cached.add(normalize_link(link))

    def _sync_source(
        self,
        source: PostSource,
        source_settings: SourceSyncSettings,
        fetch_items: Callable[[], Iterator[BookmarkItem]],
        remove_from_x: Callable[[str], bool],
        progress_callback: ProgressCallback | None,
    ) -> SourceSyncResult:
        """Sync one X post source to Raindrop."""
        source_result = SourceSyncResult()
        source_label = _SOURCE_LABELS[source]

        logger.info(f"Fetching {source_label} from X...")
        posts = list(fetch_items())
        source_result.total = len(posts)

        if progress_callback:
            progress_callback(0, source_result.total, f"Fetched {source_label} from X")

        logger.info(f"Found {source_label}", count=source_result.total)

        existing_links: set[str] | None = None
        if source_settings.skip_existing_links:
            if source_settings.collection_id is None:
                raise ValueError("collection_id must be set when skip_existing_links is enabled")
            if progress_callback:
                progress_callback(
                    0,
                    source_result.total,
                    f"Loading existing Raindrop links for {source_label}...",
                )
            existing_links = self._existing_links_for(source_settings.collection_id)
            logger.info(
                "Using Raindrop link inventory",
                source=source.value,
                collection_id=source_settings.collection_id,
                existing_count=len(existing_links),
            )

        pending_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]] = []

        for idx, post in enumerate(posts):
            log = logger.bind(
                tweet_id=post.tweet_id,
                source=source.value,
                progress=f"{idx + 1}/{source_result.total}",
            )

            if self.state.is_synced(post.tweet_id, source=source):
                log.debug("Skipping already synced post")
                source_result.already_synced += 1
                if progress_callback:
                    progress_callback(
                        idx + 1,
                        source_result.total,
                        f"Skipped (already synced): {post.tweet_id}",
                    )
                continue

            try:
                requests = create_raindrop_requests(post, source_settings)
            except ValueError as error:
                log.error("Failed to create request", error=str(error))
                source_result.failed += 1
                source_result.add_error(f"[{post.tweet_id}] {error}")
                continue

            if existing_links is not None:
                requests = self._filter_existing_requests(
                    requests=requests,
                    existing_links=existing_links,
                )
                if not requests:
                    log.debug("Skipping post with links already in Raindrop")
                    self.state.mark_synced(
                        post.tweet_id,
                        [],
                        deleted_from_x=False,
                        source=source,
                    )
                    source_result.already_synced += 1
                    if progress_callback:
                        progress_callback(
                            idx + 1,
                            source_result.total,
                            f"Skipped (existing links): {post.tweet_id}",
                        )
                    continue

            if self.settings.dry_run:
                log.info(
                    "Dry run - would create raindrop(s)",
                    links=[request.link for request in requests],
                )
                # Keep dry-run inventory consistent so later items aren't double-counted.
                if existing_links is not None:
                    for request in requests:
                        existing_links.add(normalize_link(request.link))
                source_result.newly_synced += 1
                if progress_callback:
                    progress_callback(
                        idx + 1,
                        source_result.total,
                        f"Dry run: {post.tweet_id}",
                    )
                continue

            pending_requests.append((idx, post, requests))

        self._sync_pending_posts(
            source=source,
            source_settings=source_settings,
            pending_requests=pending_requests,
            source_result=source_result,
            remove_from_x=remove_from_x,
            progress_callback=progress_callback,
        )

        return source_result

    def _filter_existing_requests(
        self,
        requests: list[RaindropCreateRequest],
        existing_links: set[str],
    ) -> list[RaindropCreateRequest]:
        """Filter out requests whose links already exist in Raindrop."""
        return [
            request for request in requests if normalize_link(request.link) not in existing_links
        ]

    def _sync_pending_posts(
        self,
        source: PostSource,
        source_settings: SourceSyncSettings,
        pending_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]],
        source_result: SourceSyncResult,
        remove_from_x: Callable[[str], bool],
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Create pending Raindrop requests in batch, with fallback mode."""
        if not pending_requests:
            return

        all_requests: list[RaindropCreateRequest] = [
            request for _, _, post_requests in pending_requests for request in post_requests
        ]

        try:
            created_raindrops = self.raindrop_client.create_raindrops(all_requests)
            if len(created_raindrops) != len(all_requests):
                raise ValueError("Batch create returned a different number of items than requested")
            self._finalize_batched_sync(
                source=source,
                source_settings=source_settings,
                pending_requests=pending_requests,
                created_links=[raindrop.link for raindrop in created_raindrops],
                source_result=source_result,
                remove_from_x=remove_from_x,
                progress_callback=progress_callback,
            )
        except Exception as batch_error:
            logger.warning(
                "Batch create failed; retrying with individual creates",
                source=source.value,
                error=str(batch_error),
            )
            self._sync_pending_posts_individually(
                source=source,
                source_settings=source_settings,
                pending_requests=pending_requests,
                source_result=source_result,
                remove_from_x=remove_from_x,
                progress_callback=progress_callback,
            )

    def _finalize_batched_sync(
        self,
        source: PostSource,
        source_settings: SourceSyncSettings,
        pending_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]],
        created_links: list[str],
        source_result: SourceSyncResult,
        remove_from_x: Callable[[str], bool],
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Update state/results after a successful batched create."""
        cursor = 0
        for idx, post, post_requests in pending_requests:
            request_count = len(post_requests)
            post_links = created_links[cursor : cursor + request_count]
            cursor += request_count
            self._mark_post_synced(
                source=source,
                source_settings=source_settings,
                idx=idx,
                post=post,
                created_links=post_links,
                source_result=source_result,
                remove_from_x=remove_from_x,
                progress_callback=progress_callback,
            )

    def _sync_pending_posts_individually(
        self,
        source: PostSource,
        source_settings: SourceSyncSettings,
        pending_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]],
        source_result: SourceSyncResult,
        remove_from_x: Callable[[str], bool],
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Fallback mode when bulk create fails."""
        for idx, post, post_requests in pending_requests:
            log = logger.bind(
                tweet_id=post.tweet_id,
                source=source.value,
                progress=f"{idx + 1}/{source_result.total}",
            )
            created_links: list[str] = []
            sync_failed = False
            for request in post_requests:
                try:
                    created = self.raindrop_client.create_raindrop(request)
                    created_links.append(created.link)
                    log.info("Created raindrop", link=created.link, raindrop_id=created.id)
                except Exception as error:
                    log.error("Failed to create raindrop", link=request.link, error=str(error))
                    source_result.add_error(
                        f"[{post.tweet_id}] Failed to create {request.link}: {error}"
                    )
                    sync_failed = True
                    break

            if sync_failed:
                source_result.failed += 1
                continue

            self._mark_post_synced(
                source=source,
                source_settings=source_settings,
                idx=idx,
                post=post,
                created_links=created_links,
                source_result=source_result,
                remove_from_x=remove_from_x,
                progress_callback=progress_callback,
            )

    def _mark_post_synced(
        self,
        source: PostSource,
        source_settings: SourceSyncSettings,
        idx: int,
        post: BookmarkItem,
        created_links: list[str],
        source_result: SourceSyncResult,
        remove_from_x: Callable[[str], bool],
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Mark a post as synced and handle optional X removal."""
        log = logger.bind(
            tweet_id=post.tweet_id,
            source=source.value,
            progress=f"{idx + 1}/{source_result.total}",
        )
        deleted_from_x = False
        if source_settings.remove_from_x:
            try:
                removed = remove_from_x(post.tweet_id)
                if removed:
                    deleted_from_x = True
                    source_result.removed_from_x += 1
                    log.info("Removed from X", source=source.value)
                else:
                    log.warning("X removal returned unsuccessful response")
                    source_result.add_error(
                        f"[{post.tweet_id}] Failed to remove from X: unsuccessful response"
                    )
            except Exception as error:
                log.warning("Failed to remove from X", error=str(error))
                source_result.add_error(f"[{post.tweet_id}] Failed to remove from X: {error}")

        self.state.mark_synced(
            post.tweet_id,
            created_links,
            deleted_from_x,
            source=source,
        )
        if source_settings.collection_id is not None:
            self._remember_created_links(source_settings.collection_id, created_links)
        source_result.newly_synced += 1
        if progress_callback:
            progress_callback(
                idx + 1,
                source_result.total,
                f"Synced: {post.tweet_id}",
            )
