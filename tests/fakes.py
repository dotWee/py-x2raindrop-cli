"""Test doubles for X and Raindrop clients.

These fakes live in the test package so production modules stay free of mocks.
"""

from __future__ import annotations

from collections.abc import Iterator

from x2raindrop_cli.models import BookmarkFolder, BookmarkItem, RaindropCreateRequest
from x2raindrop_cli.raindrop.client import CreatedRaindrop, RaindropCollection, normalize_link


class MockXClient:
    """Mock X client for testing.

    This client can be configured with pre-defined bookmarks
    and tracks delete calls for verification.
    """

    def __init__(
        self,
        bookmarks: list[BookmarkItem] | None = None,
        liked_posts: list[BookmarkItem] | None = None,
        user_id: str = "123456789",
        bookmark_folders: list[BookmarkFolder] | None = None,
        folder_bookmark_ids: dict[str, list[str]] | None = None,
    ) -> None:
        """Initialize mock client.

        Args:
            bookmarks: List of bookmarks to return.
            liked_posts: List of liked posts to return.
            user_id: Fake user ID to return.
            bookmark_folders: X bookmark folders to return.
            folder_bookmark_ids: Mapping of folder ID to tweet IDs in that folder.
        """
        self.bookmarks = bookmarks or []
        self.liked_posts = liked_posts or []
        self.user_id = user_id
        self.deleted_tweet_ids: list[str] = []
        self.unliked_tweet_ids: list[str] = []
        self.bookmark_folders = bookmark_folders or []
        self.folder_bookmark_ids = folder_bookmark_ids or {}

    def get_authenticated_user_id(self) -> str:
        """Get the mock user ID."""
        return self.user_id

    def get_bookmarks(self, max_results: int | None = None) -> Iterator[BookmarkItem]:
        """Yield pre-configured bookmarks."""
        yield from self._yield_items(self.bookmarks, max_results)

    def get_liked_posts(self, max_results: int | None = None) -> Iterator[BookmarkItem]:
        """Yield pre-configured liked posts."""
        yield from self._yield_items(self.liked_posts, max_results)

    def get_bookmark_folders(self) -> list[BookmarkFolder]:
        """Return pre-configured bookmark folders."""
        return list(self.bookmark_folders)

    def get_bookmark_ids_in_folder(self, folder_id: str) -> list[str]:
        """Return pre-configured tweet IDs for a bookmark folder."""
        return list(self.folder_bookmark_ids.get(folder_id, []))

    def _yield_items(
        self,
        items: list[BookmarkItem],
        max_results: int | None,
    ) -> Iterator[BookmarkItem]:
        """Yield items up to max_results."""
        for i, item in enumerate(items):
            if max_results and i >= max_results:
                break
            yield item

    def delete_bookmark(self, tweet_id: str) -> bool:
        """Track deleted bookmark."""
        self.deleted_tweet_ids.append(tweet_id)
        return True

    def unlike_post(self, tweet_id: str) -> bool:
        """Track unliked post."""
        self.unliked_tweet_ids.append(tweet_id)
        return True


class MockRaindropClient:
    """Mock Raindrop client for testing.

    This client can be configured with pre-defined collections
    and tracks created raindrops for verification.
    """

    def __init__(
        self,
        collections: list[RaindropCollection] | None = None,
        existing_links: list[str] | None = None,
    ) -> None:
        """Initialize mock client.

        Args:
            collections: List of collections to return.
            existing_links: Links already present in Raindrop.
        """
        self.collections = collections or [
            RaindropCollection(id=12345, title="Test Collection", count=0),
            RaindropCollection(id=-1, title="Unsorted", count=0),
        ]
        self.created_raindrops: list[RaindropCreateRequest] = []
        self.batch_create_calls: list[list[RaindropCreateRequest]] = []
        self.created_collections: list[RaindropCollection] = []
        self._next_id = 1
        self._next_collection_id = 90000
        self.existing_links = {normalize_link(link) for link in existing_links or []}
        self.list_collection_links_calls: list[int] = []

    def list_collections(self) -> list[RaindropCollection]:
        """Return pre-configured collections."""
        return self.collections

    def get_collection_by_title(self, title: str) -> RaindropCollection | None:
        """Find collection by title."""
        title_lower = title.lower()
        for c in self.collections:
            if c.title.lower() == title_lower:
                return c
        return None

    def create_raindrop(self, request: RaindropCreateRequest) -> CreatedRaindrop:
        """Track created raindrop."""
        self.created_raindrops.append(request)
        raindrop_id = self._next_id
        self._next_id += 1
        return CreatedRaindrop(
            id=raindrop_id,
            link=request.link,
            title=request.title or "",
            collection_id=request.collection_id,
        )

    def create_raindrops(self, requests: list[RaindropCreateRequest]) -> list[CreatedRaindrop]:
        """Track bulk-created raindrops in order."""
        self.batch_create_calls.append(list(requests))
        return [self.create_raindrop(request) for request in requests]

    def create_collection(self, title: str, parent_id: int) -> RaindropCollection:
        """Create and track a child collection."""
        collection = RaindropCollection(
            id=self._next_collection_id,
            title=title,
            count=0,
            parent_id=parent_id,
        )
        self._next_collection_id += 1
        self.collections.append(collection)
        self.created_collections.append(collection)
        return collection

    def list_collection_links(self, collection_id: int) -> set[str]:
        """Return configured existing links plus links created in this session."""
        self.list_collection_links_calls.append(collection_id)
        links = set(self.existing_links)
        for request in self.created_raindrops:
            if request.collection_id == collection_id:
                links.add(normalize_link(request.link))
        return links

    def check_link_exists(self, link: str, collection_id: int | None = None) -> bool:
        """Check if link was already created in this session."""
        del collection_id
        normalized = normalize_link(link)
        if normalized in self.existing_links:
            return True
        return any(normalize_link(r.link) == normalized for r in self.created_raindrops)

    def _normalize_link(self, link: str) -> str:
        """Normalize links for duplicate checks."""
        return normalize_link(link)
