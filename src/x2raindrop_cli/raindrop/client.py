"""Raindrop.io API client wrapper.

This module provides a thin wrapper around the python-raindropio library
for creating bookmarks and listing collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import quote

import structlog
from raindropio import API, Collection, CollectionRef, Raindrop

from x2raindrop_cli.models import RaindropCreateRequest

logger = structlog.get_logger(__name__)

# Maximum number of items accepted by Raindrop bulk create endpoint
MAX_BATCH_CREATE_SIZE = 100

# Raindrop list endpoint max page size
MAX_LIST_PAGE_SIZE = 50


def normalize_link(link: str) -> str:
    """Normalize links to avoid false negatives on trailing slashes.

    Args:
        link: Raw URL string.

    Returns:
        Stripped URL without a trailing slash.
    """
    return link.strip().rstrip("/")


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

    def create_raindrops(self, requests: list[RaindropCreateRequest]) -> list[CreatedRaindrop]:
        """Create multiple Raindrop bookmarks in batches.

        Args:
            requests: Details of bookmarks to create.

        Returns:
            Created Raindrop details in the same order as requests.
        """
        ...

    def list_collection_links(self, collection_id: int) -> set[str]:
        """List normalized links present in a Raindrop collection.

        Args:
            collection_id: Collection to inventory.

        Returns:
            Set of normalized link URLs in the collection.
        """
        ...

    def create_collection(self, title: str, parent_id: int) -> RaindropCollection:
        """Create a child collection under a parent collection.

        Args:
            title: Collection title.
            parent_id: Parent collection ID.

        Returns:
            Created collection details.
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

    def create_collection(self, title: str, parent_id: int) -> RaindropCollection:
        """Create a child collection under a parent collection.

        Uses the REST create endpoint so ``parent.$id`` is sent in the
        documented shape (the python-raindropio helper sends a bare integer).

        Args:
            title: Collection title.
            parent_id: Parent collection ID.

        Returns:
            Created collection details.

        Raises:
            ValueError: If the API response is missing a collection ID.
        """
        create_url = "https://api.raindrop.io/rest/v1/collection"
        payload = {"title": title, "parent": {"$id": parent_id}}
        logger.debug("Creating collection", title=title, parent_id=parent_id)
        response = self.api.post(create_url, json=payload)
        response.raise_for_status()
        response_data = response.json()
        item = response_data.get("item", {})
        if not isinstance(item, dict):
            raise ValueError("Unexpected collection create response: item is not an object")

        item_id = item.get("_id")
        if item_id is None:
            item_id = item.get("id")
        if item_id is None:
            raise ValueError("Unexpected collection create response: missing collection id")

        created = RaindropCollection(
            id=int(item_id),
            title=str(item.get("title") or title),
            count=int(item.get("count") or 0),
            parent_id=parent_id,
        )
        logger.info(
            "Created collection",
            collection_id=created.id,
            title=created.title,
            parent_id=parent_id,
        )
        return created

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
        create_kwargs = self._request_to_create_kwargs(request)

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

    def _request_to_create_kwargs(self, request: RaindropCreateRequest) -> dict[str, Any]:
        """Convert a request model to kwargs accepted by `Raindrop.create`."""
        collection_ref = self.get_collection_ref(request.collection_id)

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
        # python-raindropio has no dedicated note kwarg; fall back only when
        # excerpt is empty so note content is not silently dropped.
        elif request.note:
            create_kwargs["excerpt"] = request.note
        return create_kwargs

    def _request_to_bulk_payload(self, request: RaindropCreateRequest) -> dict[str, Any]:
        """Convert a request model to payload accepted by bulk create endpoint."""
        create_kwargs = self._request_to_create_kwargs(request)
        collection = create_kwargs.pop("collection", None)
        payload: dict[str, Any] = {"link": create_kwargs["link"]}

        if collection is not None:
            if isinstance(collection, (Collection, CollectionRef)):
                payload["collection"] = {"$id": collection.id}
            elif isinstance(collection, int):
                payload["collection"] = {"$id": collection}
        if "tags" in create_kwargs:
            payload["tags"] = create_kwargs["tags"]
        if "title" in create_kwargs:
            payload["title"] = create_kwargs["title"]
        if "excerpt" in create_kwargs:
            payload["excerpt"] = create_kwargs["excerpt"]
        # REST bulk create supports a dedicated note field distinct from excerpt.
        if request.note:
            payload["note"] = request.note

        return payload

    def create_raindrops(self, requests: list[RaindropCreateRequest]) -> list[CreatedRaindrop]:
        """Create multiple Raindrop bookmarks using the bulk endpoint.

        Raindrop currently accepts up to 100 items per request, so larger
        payloads are automatically split into multiple API calls.
        """
        if not requests:
            return []

        created_raindrops: list[CreatedRaindrop] = []
        bulk_create_url = "https://api.raindrop.io/rest/v1/raindrops"

        for batch_start in range(0, len(requests), MAX_BATCH_CREATE_SIZE):
            batch_requests = requests[batch_start : batch_start + MAX_BATCH_CREATE_SIZE]
            payload = {"items": [self._request_to_bulk_payload(r) for r in batch_requests]}

            logger.debug(
                "Creating raindrops batch",
                batch_size=len(batch_requests),
                total_requests=len(requests),
            )
            response = self.api.post(bulk_create_url, json=payload)
            response.raise_for_status()
            response_data = response.json()

            items = response_data.get("items", [])
            if not isinstance(items, list) or len(items) != len(batch_requests):
                msg = (
                    "Unexpected bulk create response: number of returned items does not "
                    "match the request size"
                )
                raise ValueError(msg)

            for request, item in zip(batch_requests, items, strict=True):
                if not isinstance(item, dict):
                    raise ValueError("Unexpected bulk create response: item is not an object")
                item_data = cast(dict[str, Any], item)

                item_id = item_data.get("_id")
                if item_id is None:
                    item_id = item_data.get("id")
                if item_id is None:
                    raise ValueError("Unexpected bulk create response: missing item id")

                item_title = item_data.get("title")
                item_link = item_data.get("link")
                created_raindrops.append(
                    CreatedRaindrop(
                        id=int(item_id),
                        link=str(item_link) if item_link is not None else request.link,
                        title=str(item_title) if item_title is not None else (request.title or ""),
                        collection_id=request.collection_id,
                    )
                )

        logger.info("Created raindrops in bulk", count=len(created_raindrops))
        return created_raindrops

    def list_collection_links(self, collection_id: int) -> set[str]:
        """Paginate a collection and return normalized link URLs.

        Uses the list endpoint (``perpage`` ≤ 50) instead of per-link search,
        so large syncs stay within Raindrop's rate limits.

        Args:
            collection_id: Target Raindrop collection ID.

        Returns:
            Set of normalized links currently in the collection.
        """
        links: set[str] = set()
        page = 0
        collection_path = str(collection_id)

        while True:
            list_url = (
                f"https://api.raindrop.io/rest/v1/raindrops/{collection_path}"
                f"?perpage={MAX_LIST_PAGE_SIZE}&page={page}"
            )
            logger.debug(
                "Listing collection links page",
                collection_id=collection_id,
                page=page,
            )
            response = self.api.get(list_url)
            response.raise_for_status()
            response_data = response.json()
            items = response_data.get("items", [])
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                item_link = item.get("link")
                if isinstance(item_link, str) and item_link:
                    links.add(normalize_link(item_link))

            if len(items) < MAX_LIST_PAGE_SIZE:
                break
            page += 1

        logger.info(
            "Loaded collection link inventory",
            collection_id=collection_id,
            link_count=len(links),
            pages=page + 1,
        )
        return links

    def check_link_exists(self, link: str, collection_id: int | None = None) -> bool:
        """Check if a link already exists in Raindrop.

        Prefer :meth:`list_collection_links` for bulk syncs. This method remains
        for one-off checks and uses a targeted search.

        Args:
            link: URL to check.
            collection_id: Optional collection to search in.

        Returns:
            True if the link exists.
        """
        normalized_link = normalize_link(link)
        collection_path = str(collection_id) if collection_id is not None else "0"
        search_term = quote(link, safe="")
        search_url = (
            f"https://api.raindrop.io/rest/v1/raindrops/{collection_path}"
            f"?search={search_term}&perpage={MAX_LIST_PAGE_SIZE}"
        )
        response = self.api.get(search_url)
        response.raise_for_status()
        response_data = response.json()
        items = response_data.get("items", [])
        if not isinstance(items, list):
            return False

        for item in items:
            if not isinstance(item, dict):
                continue
            item_link = item.get("link")
            if not isinstance(item_link, str):
                continue
            if normalize_link(item_link) == normalized_link:
                return True
        return False

    def _normalize_link(self, link: str) -> str:
        """Normalize links to avoid false negatives on trailing slashes."""
        return normalize_link(link)
