"""X (Twitter) API client for bookmarks operations.

This module provides a thin wrapper around the XDK for fetching
and managing bookmarks with proper pagination support.

RATE LIMIT NOTES:
- X API Free Tier: 1 request per 15 minutes per user
- Basic Tier: Higher limits but still limited
- Each operation (fetch bookmarks, delete bookmark) counts as a request
- User ID lookup is cached to avoid extra requests
- Bookmark deletion requires one API call per bookmark (no batch API)
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

import httpx
import structlog

from py_x_bookmarks_to_raindrop_sync.models import BookmarkItem
from py_x_bookmarks_to_raindrop_sync.x.auth_pkce import OAuth2Token

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# X API base URL
X_API_BASE = "https://api.x.com/2"

# URL pattern for extracting external URLs (non-t.co links)
URL_PATTERN = re.compile(r"https?://(?!t\.co)[^\s]+")

# Maximum results per page (X API limit)
MAX_RESULTS_PER_PAGE = 100


class XClientProtocol(Protocol):
    """Protocol for X client implementations (for testing)."""

    def get_bookmarks(self, max_results: int | None = None) -> Iterator[BookmarkItem]:
        """Fetch bookmarks from X.

        Args:
            max_results: Maximum total results to fetch.

        Yields:
            BookmarkItem for each bookmark.
        """
        ...

    def delete_bookmark(self, tweet_id: str) -> bool:
        """Remove a bookmark from X.

        Args:
            tweet_id: ID of the tweet to unbookmark.

        Returns:
            True if successful.
        """
        ...

    def get_authenticated_user_id(self) -> str:
        """Get the authenticated user's ID.

        Returns:
            User ID string.
        """
        ...


class XClient:
    """Client for interacting with X API bookmarks.

    This client uses direct HTTP requests to the X API v2 endpoints
    for bookmark operations, with OAuth2 bearer token authentication.

    RATE LIMIT AWARENESS:
    - Tracks API request count for monitoring
    - Caches user ID to avoid extra requests
    - Fetches maximum results per page to minimize pagination requests
    """

    def __init__(self, token: OAuth2Token) -> None:
        """Initialize the client with an OAuth2 token.

        Args:
            token: OAuth2 token for authentication.
        """
        self.token = token
        self._user_id: str | None = None
        self._request_count: int = 0
        self._http_client = httpx.Client(
            base_url=X_API_BASE,
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    @property
    def request_count(self) -> int:
        """Get the number of API requests made in this session."""
        return self._request_count

    def __enter__(self) -> XClient:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._http_client.close()

    def _make_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request and track it.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            url: URL path (relative to base URL)
            **kwargs: Additional arguments for httpx

        Returns:
            HTTP response

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        self._request_count += 1
        logger.debug(
            "Making X API request",
            method=method,
            url=url,
            request_number=self._request_count,
        )

        response = self._http_client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def get_authenticated_user_id(self) -> str:
        """Get the authenticated user's ID.

        NOTE: This makes an API request if not cached. Consider if you
        can get the user ID from another response (e.g., token metadata).

        Returns:
            User ID string.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        if self._user_id is not None:
            return self._user_id

        response = self._make_request("GET", "/users/me")
        data = response.json()
        self._user_id = data["data"]["id"]
        logger.debug("Got user ID", user_id=self._user_id)
        return self._user_id

    def set_user_id(self, user_id: str) -> None:
        """Set the user ID without making an API request.

        Use this if you already know the user ID (e.g., from token metadata)
        to save an API request.

        Args:
            user_id: The authenticated user's ID.
        """
        self._user_id = user_id
        logger.debug("User ID set manually", user_id=user_id)

    def get_bookmarks(self, max_results: int | None = None) -> Iterator[BookmarkItem]:
        """Fetch bookmarks from X with pagination.

        NOTE: Each page of results requires one API request. With rate limits,
        pagination may be slow. The client fetches the maximum allowed per page
        (100) to minimize requests.

        Args:
            max_results: Maximum total results to fetch. None for all.

        Yields:
            BookmarkItem for each bookmark.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        user_id = self.get_authenticated_user_id()
        total_fetched = 0
        pagination_token: str | None = None
        page_count = 0

        # Request maximum results per page to minimize API calls
        # Also request all needed expansions in a single call
        params: dict[str, Any] = {
            "max_results": MAX_RESULTS_PER_PAGE,  # Always fetch max to minimize requests
            "expansions": "author_id",
            "tweet.fields": "created_at,text,entities,author_id",
            "user.fields": "username,name",
        }

        while True:
            if pagination_token:
                params["pagination_token"] = pagination_token

            page_count += 1
            logger.debug(
                "Fetching bookmarks page",
                page=page_count,
                pagination_token=pagination_token,
            )

            response = self._make_request("GET", f"/users/{user_id}/bookmarks", params=params)
            data = response.json()

            # Build user lookup for author info
            users_lookup: dict[str, dict[str, str]] = {}
            if "includes" in data and "users" in data["includes"]:
                for user in data["includes"]["users"]:
                    users_lookup[user["id"]] = {
                        "username": user.get("username", ""),
                        "name": user.get("name", ""),
                    }

            # Process tweets
            tweets = data.get("data", [])
            if not tweets:
                logger.info(
                    "No bookmarks found or end of results",
                    pages_fetched=page_count,
                    total_fetched=total_fetched,
                )
                break

            for tweet in tweets:
                bookmark = self._parse_tweet(tweet, users_lookup)
                yield bookmark
                total_fetched += 1

                if max_results and total_fetched >= max_results:
                    logger.info(
                        "Reached max results limit",
                        max_results=max_results,
                        pages_fetched=page_count,
                    )
                    return

            # Check for next page
            meta = data.get("meta", {})
            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        logger.info(
            "Fetched all bookmarks",
            total=total_fetched,
            pages_fetched=page_count,
            api_requests=self._request_count,
        )

    def _parse_tweet(
        self, tweet: dict[str, Any], users_lookup: dict[str, dict[str, str]]
    ) -> BookmarkItem:
        """Parse a tweet dict into a BookmarkItem.

        Args:
            tweet: Tweet data from API.
            users_lookup: Mapping of user IDs to user info.

        Returns:
            BookmarkItem instance.
        """
        tweet_id = tweet["id"]
        text = tweet.get("text", "")
        author_id = tweet.get("author_id")

        # Get author info
        author_username: str | None = None
        author_name: str | None = None
        if author_id and author_id in users_lookup:
            author_username = users_lookup[author_id].get("username")
            author_name = users_lookup[author_id].get("name")

        # Parse created_at
        created_at: datetime | None = None
        if created_str := tweet.get("created_at"):
            with contextlib.suppress(ValueError):
                # X API returns ISO format with Z suffix
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))

        # Build permalink
        if author_username:
            permalink = f"https://x.com/{author_username}/status/{tweet_id}"
        else:
            permalink = f"https://x.com/i/status/{tweet_id}"

        # Extract external URLs from entities
        external_urls = self._extract_external_urls(tweet)

        return BookmarkItem(
            tweet_id=tweet_id,
            text=text,
            author_username=author_username,
            author_name=author_name,
            created_at=created_at,
            permalink=permalink,
            external_urls=external_urls,
        )

    def _extract_external_urls(self, tweet: dict[str, Any]) -> list[str]:
        """Extract external (non-t.co) URLs from a tweet.

        Args:
            tweet: Tweet data from API.

        Returns:
            List of external URLs.
        """
        external_urls: list[str] = []
        entities = tweet.get("entities", {})

        # URLs from entities (preferred, has expanded URLs)
        if "urls" in entities:
            for url_entity in entities["urls"]:
                # Use expanded_url if available, otherwise unwrapped_url
                expanded = url_entity.get("expanded_url") or url_entity.get("unwrapped_url")
                # Filter out t.co and X/Twitter internal URLs
                if (
                    expanded
                    and not expanded.startswith("https://t.co")
                    and not any(domain in expanded for domain in ["twitter.com", "x.com", "t.co"])
                ):
                    external_urls.append(expanded)

        # Fallback: extract from text if no entity URLs
        if not external_urls:
            text = tweet.get("text", "")
            matches = URL_PATTERN.findall(text)
            external_urls = [
                url
                for url in matches
                if not any(domain in url for domain in ["twitter.com", "x.com"])
            ]

        return external_urls

    def delete_bookmark(self, tweet_id: str) -> bool:
        """Remove a tweet from bookmarks.

        WARNING: Each delete operation requires one API request.
        With X API Free Tier (1 request/15 min), this is very expensive.
        Consider using --no-remove-from-x to avoid hitting rate limits.

        Args:
            tweet_id: ID of the tweet to unbookmark.

        Returns:
            True if successful.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        user_id = self.get_authenticated_user_id()

        logger.warning(
            "Deleting bookmark (uses 1 API request)",
            tweet_id=tweet_id,
            total_requests=self._request_count + 1,
        )

        response = self._make_request("DELETE", f"/users/{user_id}/bookmarks/{tweet_id}")
        data = response.json()
        success = data.get("data", {}).get("bookmarked") is False

        if success:
            logger.debug("Deleted bookmark", tweet_id=tweet_id)
        else:
            logger.warning(
                "Delete bookmark returned unexpected response",
                tweet_id=tweet_id,
                data=data,
            )

        return success


class MockXClient:
    """Mock X client for testing.

    This client can be configured with pre-defined bookmarks
    and tracks delete calls for verification.
    """

    def __init__(
        self,
        bookmarks: list[BookmarkItem] | None = None,
        user_id: str = "123456789",
    ) -> None:
        """Initialize mock client.

        Args:
            bookmarks: List of bookmarks to return.
            user_id: Fake user ID to return.
        """
        self.bookmarks = bookmarks or []
        self.user_id = user_id
        self.deleted_tweet_ids: list[str] = []

    def get_authenticated_user_id(self) -> str:
        """Get the mock user ID."""
        return self.user_id

    def get_bookmarks(self, max_results: int | None = None) -> Iterator[BookmarkItem]:
        """Yield pre-configured bookmarks."""
        for i, bookmark in enumerate(self.bookmarks):
            if max_results and i >= max_results:
                break
            yield bookmark

    def delete_bookmark(self, tweet_id: str) -> bool:
        """Track deleted bookmark."""
        self.deleted_tweet_ids.append(tweet_id)
        return True
