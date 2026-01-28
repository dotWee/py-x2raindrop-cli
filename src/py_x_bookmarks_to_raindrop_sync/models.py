"""Domain models for X bookmarks and Raindrop items.

This module contains typed models representing bookmarks from X and
items to be created in Raindrop.io.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass


class LinkMode(str, Enum):
    """How to determine the link for a Raindrop item.

    Attributes:
        PERMALINK: Use the X post permalink (e.g., https://x.com/user/status/id).
        FIRST_EXTERNAL_URL: Use the first external URL found in the post.
        BOTH: Create raindrops for both (behavior controlled by BothBehavior).
    """

    PERMALINK = "permalink"
    FIRST_EXTERNAL_URL = "first_external_url"
    BOTH = "both"


class BothBehavior(str, Enum):
    """When LinkMode is BOTH, how to handle multiple links.

    Attributes:
        ONE_EXTERNAL_PLUS_NOTE: Create one Raindrop for the external URL,
            store the X permalink in the note/excerpt.
        TWO_RAINDROPS: Create two separate Raindrop items.
    """

    ONE_EXTERNAL_PLUS_NOTE = "one_external_plus_note"
    TWO_RAINDROPS = "two_raindrops"


class BookmarkItem(BaseModel):
    """Represents a bookmark from X (Twitter).

    Attributes:
        tweet_id: The unique identifier of the tweet/post.
        text: The full text content of the tweet.
        author_username: The username of the tweet author.
        author_name: The display name of the tweet author.
        created_at: When the tweet was created.
        permalink: The direct URL to the tweet.
        external_urls: List of external URLs found in the tweet.
    """

    model_config = ConfigDict(frozen=True)

    tweet_id: str = Field(..., description="Unique tweet identifier")
    text: str = Field(..., description="Tweet text content")
    author_username: str | None = Field(None, description="Author's username")
    author_name: str | None = Field(None, description="Author's display name")
    created_at: datetime | None = Field(None, description="Tweet creation timestamp")
    permalink: str = Field(..., description="Direct URL to the tweet")
    external_urls: list[str] = Field(default_factory=list, description="External URLs in tweet")

    def get_title(self) -> str:
        """Generate a title for the bookmark.

        Returns:
            A title string, preferring author info if available.
        """
        if self.author_username:
            prefix = f"@{self.author_username}"
            if self.author_name:
                prefix = f"{self.author_name} ({prefix})"
            return (
                f"{prefix}: {self.text[:100]}..."[:150]
                if len(self.text) > 100
                else f"{prefix}: {self.text}"
            )
        return self.text[:150] if len(self.text) > 150 else self.text


class RaindropCreateRequest(BaseModel):
    """Request to create a Raindrop item.

    Attributes:
        link: The URL to bookmark in Raindrop.
        title: Optional title for the bookmark.
        excerpt: Optional excerpt/description.
        tags: List of tags to apply.
        collection_id: Target collection ID.
        note: Optional note content.
    """

    model_config = ConfigDict(frozen=True)

    link: str = Field(..., description="URL to bookmark")
    title: str | None = Field(None, description="Bookmark title")
    excerpt: str | None = Field(None, description="Excerpt/description")
    tags: list[str] = Field(default_factory=list, description="Tags to apply")
    collection_id: int = Field(..., description="Target Raindrop collection ID")
    note: str | None = Field(None, description="Additional note content")
    source_tweet_id: str = Field(..., description="Source X tweet ID for tracking")


class SyncedBookmark(BaseModel):
    """Record of a successfully synced bookmark.

    Attributes:
        tweet_id: The X tweet ID that was synced.
        raindrop_links: List of Raindrop URLs created.
        synced_at: When the sync occurred.
        deleted_from_x: Whether it was removed from X bookmarks.
    """

    model_config = ConfigDict(frozen=True)

    tweet_id: str = Field(..., description="Source X tweet ID")
    raindrop_links: list[str] = Field(default_factory=list, description="Created Raindrop URLs")
    synced_at: datetime = Field(default_factory=datetime.now, description="Sync timestamp")
    deleted_from_x: bool = Field(False, description="Whether deleted from X")


class SyncResult(BaseModel):
    """Result of a sync operation.

    Attributes:
        total_bookmarks: Total bookmarks fetched from X.
        already_synced: Number skipped (already synced).
        newly_synced: Number successfully synced.
        failed: Number that failed to sync.
        deleted_from_x: Number deleted from X bookmarks.
        errors: List of error messages.
    """

    total_bookmarks: int = 0
    already_synced: int = 0
    newly_synced: int = 0
    failed: int = 0
    deleted_from_x: int = 0
    errors: list[str] = Field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message to the result.

        Args:
            error: The error message to add.
        """
        self.errors.append(error)
