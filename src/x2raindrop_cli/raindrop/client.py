"""Raindrop.io API client wrapper.

This module provides a thin wrapper around the python-raindropio library
for creating bookmarks and listing collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from raindropio import API, Collection, CollectionRef, Raindrop

from x2raindrop_cli.models import RaindropCreateRequest

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


@dataclass
class RaindropCollection:
    """Represents a Raindrop.io collection.

    Attributes:
        id: Collection ID.
        title: Collection title.
        count: Number of items in the collection.
        parent_id: Parent collection ID (if nested).
    """

    id: int
    title: str
    count: int
    parent_id: int | None = None


@dataclass
class CreatedRaindrop:
    """Represents a successfully created Raindrop.

    Attributes:
        id: Raindrop ID.
        link: URL that was bookmarked.
        title: Title of the bookmark.
        collection_id: Collection it was added to.
    """

    id: int
    link: str
    title: str
    collection_id: int


class RaindropClientProtocol(Protocol):
    """Protocol for Raindrop client implementations (for testing)."""

    def list_collections(self) -> list[RaindropCollection]:
        """List all collections.

        Returns:
            List of collections.
        """
        ...

    def get_collection_by_title(self, title: str) -> RaindropCollection | None:
        """Find a collection by title.

        Args:
            title: Collection title to find.

        Returns:
            Collection if found, None otherwise.
        """
        ...

    def create_raindrop(self, request: RaindropCreateRequest) -> CreatedRaindrop:
        """Create a new Raindrop bookmark.

        Args:
            request: Details of the bookmark to create.

        Returns:
            Created Raindrop details.
        """
        ...

    def check_link_exists(self, link: str, collection_id: int | None = None) -> bool:
        """Check if a link already exists in Raindrop.

        Args:
            link: URL to check.
            collection_id: Optional collection to search in.

        Returns:
            True if the link exists.
        """
        ...


class RaindropClient:
    """Client for interacting with Raindrop.io API.

    This client wraps the python-raindropio library to provide
    a simpler interface for the sync operations we need.
    """

    def __init__(self, token: str) -> None:
        """Initialize the client with an API token.

        Args:
            token: Raindrop.io API token.
        """
        self.token = token
        self._api: API | None = None

    @property
    def api(self) -> API:
        """Get or create the API client."""
        if self._api is None:
            self._api = API(self.token)
        return self._api

    def __enter__(self) -> RaindropClient:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the API connection."""
        if self._api is not None:
            self._api.close()
            self._api = None

    def _get_parent_id(self, collection: Collection) -> int | None:
        """Safely get the parent ID of a collection.

        Args:
            collection: Collection to get parent ID from.

        Returns:
            Parent ID or None if no parent or error accessing it.
        """
        if not collection.parent:
            return None
        try:
            return collection.parent.id
        except (TypeError, AttributeError):
            # Handle case where parent exists but internal data is None
            return None

    def list_collections(self) -> list[RaindropCollection]:
        """List all collections (root and children).

        Returns:
            List of all collections.
        """
        collections: list[RaindropCollection] = []

        # Get root collections
        for c in Collection.get_roots(self.api):
            collections.append(
                RaindropCollection(
                    id=c.id,
                    title=c.title,
                    count=c.count,
                    parent_id=self._get_parent_id(c),
                )
            )

        # Get child collections
        for c in Collection.get_childrens(self.api):
            collections.append(
                RaindropCollection(
                    id=c.id,
                    title=c.title,
                    count=c.count,
                    parent_id=self._get_parent_id(c),
                )
            )

        logger.debug("Listed collections", count=len(collections))
        return collections

    def get_collection_by_title(self, title: str) -> RaindropCollection | None:
        """Find a collection by its title.

        Args:
            title: Title to search for (case-insensitive).

        Returns:
            Collection if found, None otherwise.
        """
        title_lower = title.lower()
        for collection in self.list_collections():
            if collection.title.lower() == title_lower:
                return collection
        return None

    def get_collection_ref(self, collection_id: int) -> CollectionRef | Collection:
        """Get a collection reference for use in Raindrop creation.

        Args:
            collection_id: Collection ID.

        Returns:
            CollectionRef or Collection instance for the ID.
        """
        # Check for special collection IDs
        if collection_id == -1:
            return CollectionRef.Unsorted
        if collection_id == -99:
            return CollectionRef.Trash

        # For regular collections, create a reference
        # We use CollectionRef with the ID
        return CollectionRef({"$id": collection_id})

    def create_raindrop(self, request: RaindropCreateRequest) -> CreatedRaindrop:
        """Create a new Raindrop bookmark.

        Args:
            request: Details of the bookmark to create.

        Returns:
            Created Raindrop details.

        Raises:
            Exception: If creation fails.
        """
        collection_ref = self.get_collection_ref(request.collection_id)

        # Build kwargs for Raindrop.create
        create_kwargs: dict[str, Any] = {
            "link": request.link,
            "collection": collection_ref,
        }

        if request.tags:
            create_kwargs["tags"] = request.tags

        if request.title:
            create_kwargs["title"] = request.title

        if request.excerpt:
            create_kwargs["excerpt"] = request.excerpt

        # Note: python-raindropio may not support 'note' field directly
        # We'll include it in excerpt if note is provided but excerpt is not
        if request.note and not request.excerpt:
            create_kwargs["excerpt"] = request.note

        logger.debug(
            "Creating raindrop",
            link=request.link,
            collection_id=request.collection_id,
            tags=request.tags,
        )

        raindrop = Raindrop.create(self.api, **create_kwargs)

        logger.info(
            "Created raindrop",
            id=raindrop.id,
            link=request.link,
            title=raindrop.title,
        )

        return CreatedRaindrop(
            id=raindrop.id,
            link=request.link,
            title=raindrop.title or "",
            collection_id=request.collection_id,
        )

    def check_link_exists(self, link: str, _collection_id: int | None = None) -> bool:
        """Check if a link already exists in Raindrop.

        Note: This is a basic implementation that searches through pages.
        For large collections, this may be slow.

        Args:
            link: URL to check.
            _collection_id: Optional collection to search in (currently unused).

        Returns:
            True if the link exists.
        """
        # Raindrop.search doesn't have a direct URL filter
        # We would need to iterate through results
        # For now, return False and rely on our local state for deduplication
        logger.debug("Link existence check skipped (using local state)", link=link)
        return False


class MockRaindropClient:
    """Mock Raindrop client for testing.

    This client can be configured with pre-defined collections
    and tracks created raindrops for verification.
    """

    def __init__(
        self,
        collections: list[RaindropCollection] | None = None,
    ) -> None:
        """Initialize mock client.

        Args:
            collections: List of collections to return.
        """
        self.collections = collections or [
            RaindropCollection(id=12345, title="Test Collection", count=0),
            RaindropCollection(id=-1, title="Unsorted", count=0),
        ]
        self.created_raindrops: list[RaindropCreateRequest] = []
        self._next_id = 1

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

    def check_link_exists(self, link: str, _collection_id: int | None = None) -> bool:
        """Check if link was already created in this session."""
        return any(r.link == link for r in self.created_raindrops)
