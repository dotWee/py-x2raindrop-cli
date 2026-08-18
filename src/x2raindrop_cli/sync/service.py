"""Sync orchestration service.

This module coordinates the sync process between X bookmarks/likes
and Raindrop.io, handling transformation, deduplication,
and optional removal from X.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

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
    collection_id: int | None = None,
) -> list[RaindropCreateRequest]:
    """Create Raindrop request(s) from a bookmark or liked post.

    Args:
        bookmark: X post to convert.
        settings: Source-specific sync settings.
        collection_id: Optional collection override (e.g. a folder subcollection).

    Returns:
        List of RaindropCreateRequest objects.
    """
    target_collection_id = collection_id if collection_id is not None else settings.collection_id
    if target_collection_id is None:
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
                collection_id=target_collection_id,
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

    def _resolve_collection_ids(self) -> None:
        """Resolve ``collection_title`` to ``collection_id`` when ID is unset.

        Raises:
            ValueError: If a title is set but no matching collection exists.
        """
        for source_name, source_settings in (
            ("bookmarks", self.settings.bookmarks),
            ("likes", self.settings.likes),
        ):
            if not source_settings.enabled:
                continue
            if source_settings.collection_id:
                continue

            title = (source_settings.collection_title or "").strip()
            if not title:
                raise ValueError(
                    f"{source_name}.collection_id or {source_name}.collection_title must be set"
                )

            collection = self.raindrop_client.get_collection_by_title(title)
            if collection is None:
                raise ValueError(
                    f"Raindrop collection titled {title!r} not found for {source_name}"
                )

            logger.info(
                "Resolved collection title to ID",
                source=source_name,
                title=title,
                collection_id=collection.id,
            )
            source_settings.collection_id = collection.id

        self._validate_folder_mapping()

    def _validate_folder_mapping(self) -> None:
        """Require a regular parent collection when mapping X folders.

        Raises:
            ValueError: If folder mapping is enabled without a usable parent.
        """
        bookmarks = self.settings.bookmarks
        if not bookmarks.enabled or not bookmarks.map_folders_to_subcollections:
            return
        collection_id = bookmarks.collection_id
        if collection_id is None or collection_id <= 0:
            raise ValueError(
                "map_folders_to_subcollections requires a regular Raindrop collection "
                "(not 0/All, -1/Unsorted, or -99/Trash)"
            )

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
        self._resolve_collection_ids()
        self.state.load()
        self._collection_link_cache.clear()

        if self.settings.bookmarks.enabled:
            result.bookmarks = self._sync_source(
                source=PostSource.BOOKMARKS,
                source_settings=self.settings.bookmarks,
                fetch_items=self.x_client.get_bookmarks,
                remove_from_x=self.x_client.delete_bookmark,
                progress_callback=progress_callback,
                map_folders=self.settings.bookmarks.map_folders_to_subcollections,
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
        map_folders: bool = False,
    ) -> SourceSyncResult:
        """Sync one X post source to Raindrop."""
        source_result = SourceSyncResult()
        source_label = _SOURCE_LABELS[source]

        logger.info(f"Fetching {source_label} from X...")
        posts = list(fetch_items())
        if map_folders:
            if progress_callback:
                progress_callback(0, len(posts), "Mapping X bookmark folders...")
            posts = self._apply_bookmark_folders(posts)
        source_result.total = len(posts)

        if progress_callback:
            progress_callback(0, source_result.total, f"Fetched {source_label} from X")

        logger.info(f"Found {source_label}", count=source_result.total)

        folder_collection_ids = self._resolve_folder_subcollections(
            posts=posts,
            source_settings=source_settings,
            map_folders=map_folders,
        )

        if source_settings.skip_existing_links and progress_callback:
            progress_callback(
                0,
                source_result.total,
                f"Loading existing Raindrop links for {source_label}...",
            )

        pending_requests: list[tuple[int, BookmarkItem, list[RaindropCreateRequest]]] = []

        for idx, post in enumerate(posts):
            log = logger.bind(
                tweet_id=post.tweet_id,
                source=source.value,
                folder=post.folder_name,
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

            target_collection_id = self._target_collection_id(
                post=post,
                source_settings=source_settings,
                folder_collection_ids=folder_collection_ids,
            )
            if target_collection_id is None:
                log.info(
                    "Dry run - would create subcollection and raindrop(s)",
                    folder=post.folder_name,
                )
                source_result.newly_synced += 1
                if progress_callback:
                    progress_callback(
                        idx + 1,
                        source_result.total,
                        f"Dry run (would create folder): {post.folder_name}",
                    )
                continue

            try:
                requests = create_raindrop_requests(
                    post,
                    source_settings,
                    collection_id=target_collection_id,
                )
            except ValueError as error:
                log.error("Failed to create request", error=str(error))
                source_result.failed += 1
                source_result.add_error(f"[{post.tweet_id}] {error}")
                continue

            if source_settings.skip_existing_links:
                existing_links = self._existing_links_for(target_collection_id)
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
                    collection_id=target_collection_id,
                    folder=post.folder_name,
                )
                if source_settings.skip_existing_links:
                    self._remember_created_links(
                        target_collection_id,
                        [request.link for request in requests],
                    )
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

    def _apply_bookmark_folders(self, posts: list[BookmarkItem]) -> list[BookmarkItem]:
        """Annotate bookmarks with their X folder names.

        Posts that appear only in a folder (not in the main bookmarks list)
        are added as permalink-only items so folder contents are not dropped.
        """
        folders = self.x_client.get_bookmark_folders()
        tweet_to_folder: dict[str, str] = {}
        for folder in folders:
            for tweet_id in self.x_client.get_bookmark_ids_in_folder(folder.id):
                existing_folder = tweet_to_folder.get(tweet_id)
                if existing_folder and existing_folder != folder.name:
                    logger.warning(
                        "Bookmark is in multiple X folders; using the first folder",
                        tweet_id=tweet_id,
                        first_folder=existing_folder,
                        ignored_folder=folder.name,
                    )
                    continue
                tweet_to_folder[tweet_id] = folder.name

        annotated = [
            post.model_copy(update={"folder_name": tweet_to_folder.get(post.tweet_id)})
            for post in posts
        ]
        known_ids = {post.tweet_id for post in annotated}
        for tweet_id, folder_name in tweet_to_folder.items():
            if tweet_id in known_ids:
                continue
            annotated.append(
                BookmarkItem(
                    tweet_id=tweet_id,
                    text="",
                    permalink=f"https://x.com/i/status/{tweet_id}",
                    folder_name=folder_name,
                )
            )

        logger.info(
            "Mapped X bookmark folders",
            folder_count=len(folders),
            filed_count=sum(1 for post in annotated if post.folder_name),
            unfiled_count=sum(1 for post in annotated if not post.folder_name),
        )
        return annotated

    def _resolve_folder_subcollections(
        self,
        posts: list[BookmarkItem],
        source_settings: SourceSyncSettings,
        map_folders: bool,
    ) -> dict[str, int]:
        """Find or create Raindrop subcollections for X bookmark folders.

        Returns:
            Mapping of folder display name to Raindrop collection ID.
        """
        if not map_folders:
            return {}
        if source_settings.collection_id is None:
            raise ValueError("collection_id must be set when mapping folders")

        parent_id = source_settings.collection_id
        folder_names = sorted({post.folder_name for post in posts if post.folder_name})
        if not folder_names:
            return {}

        collections = self.raindrop_client.list_collections()
        children_by_title = {
            collection.title.lower(): collection
            for collection in collections
            if collection.parent_id == parent_id
        }

        mapping: dict[str, int] = {}
        for folder_name in folder_names:
            existing = children_by_title.get(folder_name.lower())
            if existing is not None:
                mapping[folder_name] = existing.id
                logger.info(
                    "Using existing Raindrop subcollection for X folder",
                    folder=folder_name,
                    collection_id=existing.id,
                    parent_id=parent_id,
                )
                continue
            if self.settings.dry_run:
                logger.info(
                    "Dry run - would create Raindrop subcollection",
                    folder=folder_name,
                    parent_id=parent_id,
                )
                continue
            created = self.raindrop_client.create_collection(folder_name, parent_id)
            children_by_title[folder_name.lower()] = created
            mapping[folder_name] = created.id

        return mapping

    def _target_collection_id(
        self,
        post: BookmarkItem,
        source_settings: SourceSyncSettings,
        folder_collection_ids: dict[str, int],
    ) -> int | None:
        """Return the Raindrop collection ID for a post.

        Returns:
            Collection ID, or None when a dry-run would still need to create
            the destination subcollection.
        """
        if post.folder_name:
            mapped_id = folder_collection_ids.get(post.folder_name)
            if mapped_id is not None:
                return mapped_id
            if self.settings.dry_run:
                return None
        if source_settings.collection_id is None:
            raise ValueError("collection_id must be set in sync settings")
        return source_settings.collection_id

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
                post_requests=post_requests,
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
                post_requests=post_requests,
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
        post_requests: list[RaindropCreateRequest],
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
        for request, link in zip(post_requests, created_links, strict=True):
            self._remember_created_links(request.collection_id, [link])
        source_result.newly_synced += 1
        if progress_callback:
            progress_callback(
                idx + 1,
                source_result.total,
                f"Synced: {post.tweet_id}",
            )
