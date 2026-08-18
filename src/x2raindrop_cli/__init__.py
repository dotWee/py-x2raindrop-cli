"""X Bookmarks to Raindrop.io Sync Tool.

A CLI tool to sync your X (Twitter) bookmarks to Raindrop.io collections.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("x2raindrop-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"
