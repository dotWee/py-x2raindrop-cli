"""X (Twitter) API client for bookmark operations.

This module wraps the official Python XDK client for bookmark workflows while
keeping the app-specific `BookmarkItem` parsing and request tracking behavior.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from xdk import Client as XdkClient

from x2raindrop_cli.models import BookmarkItem
from x2raindrop_cli.x.auth_pkce import OAuth2Token, refresh_access_token

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

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

    Uses the official Python XDK client for all API operations and tracks the
    number of API calls performed in this process for visibility.
    """

    def __init__(
        self,
        token: OAuth2Token,
        *,
        refresh_client_id: str | None = None,
        refresh_client_secret: str | None = None,
    ) -> None:
        """Initialize the client with an OAuth2 token.

        Args:
            token: OAuth2 token for authentication.
            refresh_client_id: OAuth2 client ID used to refresh access tokens (optional).
            refresh_client_secret: OAuth2 client secret used to refresh access tokens (optional).
        """
        self.token = token
        self._refresh_client_id = refresh_client_id
        self._refresh_client_secret = refresh_client_secret
        self._user_id: str | None = None
        self._request_count: int = 0
        self._x_client = XdkClient(access_token=token.access_token)

        # Best-effort early refresh if token is already expired.
        self._ensure_fresh_token()

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
        """Close the underlying XDK session."""
        self._x_client.session.close()

    def _ensure_fresh_token(self) -> None:
        """Refresh the access token if expired and refresh is configured."""
        if not self.token.is_expired():
            return
        if not self.token.refresh_token:
            return
        if not self._refresh_client_id:
            logger.warning(
                "Token expired but refresh client_id is missing; cannot refresh automatically"
            )
            return

        try:
            refreshed = refresh_access_token(
                self.token.refresh_token,
                self._refresh_client_id,
                self._refresh_client_secret,
            )
        except Exception as e:
            logger.warning("Automatic token refresh failed", error=str(e))
            return

        # Swap token + underlying client so future calls use the fresh access token.
        self.token = refreshed
        with contextlib.suppress(Exception):
            self._x_client.session.close()
        self._x_client = XdkClient(access_token=self.token.access_token)
        logger.info("Access token refreshed for XDK client")

    def get_authenticated_user_id(self) -> str:
        """Get the authenticated user's ID.

        Returns:
            User ID string.
        """
        if self._user_id is not None:
            return self._user_id

        self._ensure_fresh_token()
        self._request_count += 1
        response = self._x_client.users.get_me()
        self._user_id = self._extract_id_from_me_response(response)
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

        Args:
            max_results: Maximum total results to fetch. None for all.

        Yields:
            BookmarkItem for each bookmark.

        """
        self._ensure_fresh_token()
        user_id = self.get_authenticated_user_id()
        total_fetched = 0
        page_count = 0
        for page in self._x_client.users.get_bookmarks(
            id=user_id,
            max_results=MAX_RESULTS_PER_PAGE,
            expansions=["author_id"],
            tweet_fields=["created_at", "text", "entities", "author_id"],
            user_fields=["username", "name"],
        ):
            page_count += 1
            self._request_count += 1
            logger.debug("Fetching bookmarks page", page=page_count)
            data = self._model_to_dict(page)

            # Build user lookup for author info
            users_lookup: dict[str, dict[str, str]] = {}
            includes = data.get("includes", {})
            include_users = includes.get("users", []) if isinstance(includes, dict) else []
            for user in include_users:
                if not isinstance(user, dict):
                    continue
                user_id_raw = user.get("id")
                if user_id_raw is None:
                    continue
                users_lookup[str(user_id_raw)] = {
                    "username": str(user.get("username", "")),
                    "name": str(user.get("name", "")),
                }

            # Process tweets
            tweets = data.get("data", [])
            if not isinstance(tweets, list):
                tweets = []
            if not tweets:
                logger.info(
                    "No bookmarks found or end of results",
                    pages_fetched=page_count,
                    total_fetched=total_fetched,
                )
                break

            for tweet in tweets:
                if not isinstance(tweet, dict):
                    continue
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

        logger.info(
            "Fetched all bookmarks",
            total=total_fetched,
            pages_fetched=page_count,
            api_requests=self._request_count,
        )

    def _model_to_dict(self, model: Any) -> dict[str, Any]:
        """Convert an XDK response model into a dictionary."""
        if isinstance(model, dict):
            return model
        if hasattr(model, "model_dump"):
            dumped = model.model_dump()
            if isinstance(dumped, dict):
                return dumped
        return {}

    def _extract_id_from_me_response(self, response: Any) -> str:
        """Extract authenticated user ID from XDK get_me response."""
        data: Any = getattr(response, "data", None)
        if data is None:
            data = self._model_to_dict(response).get("data")
        if isinstance(data, dict):
            user_id = data.get("id")
            if user_id is not None:
                return str(user_id)
        if hasattr(data, "id"):
            return str(data.id)
        raise ValueError("X get_me response does not contain a user ID")

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

        Args:
            tweet_id: ID of the tweet to unbookmark.

        Returns:
            True if successful.
        """
        self._ensure_fresh_token()
        user_id = self.get_authenticated_user_id()
        self._request_count += 1

        logger.warning(
            "Deleting bookmark (uses 1 API request)",
            tweet_id=tweet_id,
            total_requests=self._request_count,
        )

        response = self._x_client.users.delete_bookmark(id=user_id, tweet_id=tweet_id)
        response_data = self._model_to_dict(response)
        data = response_data.get("data", {})
        success = isinstance(data, dict) and data.get("bookmarked") is False

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
