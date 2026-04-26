"""Sync orchestration service.

This module coordinates the sync process between X bookmarks
and Raindrop.io, handling transformation, deduplication,
and optional deletion from X.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from x2raindrop_cli.config import SyncSettings
from x2raindrop_cli.models import (
    BookmarkItem,
    BothBehavior,
    LinkMode,
    RaindropCreateRequest,
    SyncResult,
)
from x2raindrop_cli.raindrop.client import RaindropClientProtocol
from x2raindrop_cli.state import SyncState
from x2raindrop_cli.x.client import XClientProtocol

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


# Type for progress callback: (current, total, message)
ProgressCallback = Callable[[int, int, str], None]


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
        # Just use the permalink
        links.append((bookmark.permalink, None))

    elif link_mode == LinkMode.FIRST_EXTERNAL_URL:
        # Use first external URL, fallback to permalink
        if bookmark.external_urls:
            links.append((bookmark.external_urls[0], f"From: {bookmark.permalink}"))
        else:
            links.append((bookmark.permalink, None))

    elif link_mode == LinkMode.BOTH:
        if bookmark.external_urls:
            if both_behavior == BothBehavior.ONE_EXTERNAL_PLUS_NOTE:
                # One raindrop with external URL, permalink in note
                links.append((bookmark.external_urls[0], f"X Post: {bookmark.permalink}"))
            else:  # TWO_RAINDROPS
                # Two separate raindrops
                links.append((bookmark.external_urls[0], f"From: {bookmark.permalink}"))
                links.append((bookmark.permalink, None))
        else:
            # No external URLs, just use permalink
            links.append((bookmark.permalink, None))

    return links


def create_raindrop_requests(
    bookmark: BookmarkItem,
    settings: SyncSettings,
) -> list[RaindropCreateRequest]:
    """Create Raindrop request(s) from a bookmark.

    Args:
        bookmark: X bookmark to convert.
        settings: Sync settings.

    Returns:
        List of RaindropCreateRequest objects.
    """
    if settings.collection_id is None:
        raise ValueError("collection_id must be set in sync settings")

    links = resolve_links(bookmark, settings.link_mode, settings.both_behavior)
    requests: list[RaindropCreateRequest] = []

    for link, note in links:
        # Build title
        title = bookmark.get_title()

        # Build excerpt (tweet text)
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
    """Orchestrates syncing X bookmarks to Raindrop.io.

    This service:
    1. Fetches bookmarks from X
    2. Filters out already-synced items using local state
    3. Creates Raindrop items for new bookmarks
    4. Optionally deletes from X bookmarks after sync
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

    def sync(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncResult:
        """Run the sync process.

        Args:
            progress_callback: Optional callback for progress updates.

        Returns:
            SyncResult with statistics.
        """
        result = SyncResult()

        # Load existing state
        self.state.load()

        # Fetch bookmarks from X
        logger.info("Fetching bookmarks from X...")
        bookmarks = list(self.x_client.get_bookmarks())
        result.total_bookmarks = len(bookmarks)

        if progress_callback:
            progress_callback(0, result.total_bookmarks, "Fetched bookmarks from X")

        logger.info("Found bookmarks", count=result.total_bookmarks)

        pending_bookmark_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]] = []
        checked_link_cache: dict[tuple[int, str], bool] = {}

        # Build request payloads for each bookmark
        for idx, bookmark in enumerate(bookmarks):
            log = logger.bind(
                tweet_id=bookmark.tweet_id,
                progress=f"{idx + 1}/{result.total_bookmarks}",
            )

            # Check if already synced
            if self.state.is_synced(bookmark.tweet_id):
                log.debug("Skipping already synced bookmark")
                result.already_synced += 1
                if progress_callback:
                    progress_callback(
                        idx + 1,
                        result.total_bookmarks,
                        f"Skipped (already synced): {bookmark.tweet_id}",
                    )
                continue

            # Create Raindrop requests
            try:
                requests = create_raindrop_requests(bookmark, self.settings)
            except ValueError as e:
                log.error("Failed to create request", error=str(e))
                result.failed += 1
                result.add_error(f"[{bookmark.tweet_id}] {e}")
                continue

            if self.settings.skip_existing_links:
                requests = self._filter_existing_requests(
                    requests=requests,
                    checked_link_cache=checked_link_cache,
                )
                if not requests:
                    log.debug("Skipping bookmark with links already in Raindrop")
                    self.state.mark_synced(
                        bookmark.tweet_id,
                        [],
                        deleted_from_x=False,
                    )
                    result.already_synced += 1
                    if progress_callback:
                        progress_callback(
                            idx + 1,
                            result.total_bookmarks,
                            f"Skipped (existing links): {bookmark.tweet_id}",
                        )
                    continue

            # Dry run mode
            if self.settings.dry_run:
                log.info(
                    "Dry run - would create raindrop(s)",
                    links=[r.link for r in requests],
                )
                result.newly_synced += 1
                if progress_callback:
                    progress_callback(
                        idx + 1,
                        result.total_bookmarks,
                        f"Dry run: {bookmark.tweet_id}",
                    )
                continue

            pending_bookmark_requests.append((idx, bookmark, requests))

        self._sync_pending_bookmarks(
            pending_bookmark_requests,
            result,
            progress_callback,
        )

        # Save state
        self.state.save()

        logger.info(
            "Sync complete",
            total=result.total_bookmarks,
            newly_synced=result.newly_synced,
            already_synced=result.already_synced,
            failed=result.failed,
            deleted_from_x=result.deleted_from_x,
        )

        return result

    def _filter_existing_requests(
        self,
        requests: list[RaindropCreateRequest],
        checked_link_cache: dict[tuple[int, str], bool],
    ) -> list[RaindropCreateRequest]:
        """Filter out requests whose links already exist in Raindrop."""
        filtered: list[RaindropCreateRequest] = []
        for request in requests:
            cache_key = (request.collection_id, request.link)
            exists = checked_link_cache.get(cache_key)
            if exists is None:
                exists = self.raindrop_client.check_link_exists(
                    request.link,
                    collection_id=request.collection_id,
                )
                checked_link_cache[cache_key] = exists
            if not exists:
                filtered.append(request)
        return filtered

    def _sync_pending_bookmarks(
        self,
        pending_bookmark_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]],
        result: SyncResult,
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Create pending Raindrop requests in batch, with fallback mode."""
        if not pending_bookmark_requests:
            return

        all_requests: list[RaindropCreateRequest] = [
            request
            for _, _, bookmark_requests in pending_bookmark_requests
            for request in bookmark_requests
        ]

        try:
            created_raindrops = self.raindrop_client.create_raindrops(all_requests)
            if len(created_raindrops) != len(all_requests):
                raise ValueError("Batch create returned a different number of items than requested")
            self._finalize_batched_sync(
                pending_bookmark_requests=pending_bookmark_requests,
                created_links=[raindrop.link for raindrop in created_raindrops],
                result=result,
                progress_callback=progress_callback,
            )
        except Exception as batch_error:
            logger.warning(
                "Batch create failed; retrying with individual creates",
                error=str(batch_error),
            )
            self._sync_pending_bookmarks_individually(
                pending_bookmark_requests=pending_bookmark_requests,
                result=result,
                progress_callback=progress_callback,
            )

    def _finalize_batched_sync(
        self,
        pending_bookmark_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]],
        created_links: list[str],
        result: SyncResult,
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Update state/results after a successful batched create."""
        cursor = 0
        for idx, bookmark, bookmark_requests in pending_bookmark_requests:
            request_count = len(bookmark_requests)
            bookmark_links = created_links[cursor : cursor + request_count]
            cursor += request_count
            self._mark_bookmark_synced(
                idx=idx,
                bookmark=bookmark,
                created_links=bookmark_links,
                result=result,
                progress_callback=progress_callback,
            )

    def _sync_pending_bookmarks_individually(
        self,
        pending_bookmark_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]],
        result: SyncResult,
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Fallback mode when bulk create fails."""
        for idx, bookmark, bookmark_requests in pending_bookmark_requests:
            log = logger.bind(
                tweet_id=bookmark.tweet_id,
                progress=f"{idx + 1}/{result.total_bookmarks}",
            )
            created_links: list[str] = []
            sync_failed = False
            for request in bookmark_requests:
                try:
                    created = self.raindrop_client.create_raindrop(request)
                    created_links.append(created.link)
                    log.info("Created raindrop", link=created.link, raindrop_id=created.id)
                except Exception as error:
                    log.error("Failed to create raindrop", link=request.link, error=str(error))
                    result.add_error(
                        f"[{bookmark.tweet_id}] Failed to create {request.link}: {error}"
                    )
                    sync_failed = True
                    break

            if sync_failed:
                result.failed += 1
                continue

            self._mark_bookmark_synced(
                idx=idx,
                bookmark=bookmark,
                created_links=created_links,
                result=result,
                progress_callback=progress_callback,
            )

    def _mark_bookmark_synced(
        self,
        idx: int,
        bookmark: BookmarkItem,
        created_links: list[str],
        result: SyncResult,
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Mark a bookmark as synced and handle optional X deletion."""
        log = logger.bind(
            tweet_id=bookmark.tweet_id,
            progress=f"{idx + 1}/{result.total_bookmarks}",
        )
        deleted_from_x = False
        if self.settings.remove_from_x:
            try:
                self.x_client.delete_bookmark(bookmark.tweet_id)
                deleted_from_x = True
                result.deleted_from_x += 1
                log.info("Deleted from X bookmarks")
            except Exception as error:
                log.warning("Failed to delete from X", error=str(error))
                result.add_error(f"[{bookmark.tweet_id}] Failed to delete from X: {error}")

        self.state.mark_synced(
            bookmark.tweet_id,
            created_links,
            deleted_from_x,
        )
        result.newly_synced += 1
        if progress_callback:
            progress_callback(
                idx + 1,
                result.total_bookmarks,
                f"Synced: {bookmark.tweet_id}",
            )
