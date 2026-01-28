# X Bookmarks to Raindrop.io Sync

A Python CLI tool to sync your X (Twitter) bookmarks to Raindrop.io collections.

## Features

- Sync X bookmarks to a specified Raindrop.io collection
- Configurable link handling:
  - Use X post permalink
  - Use first external URL from the post (with fallback to permalink)
  - Both: create entries for external URLs with X permalink stored in notes
- Apply custom tags to synced bookmarks
- Optional: Remove bookmarks from X after syncing
- Idempotent syncing with local state tracking
- Dry-run mode for safe testing
- Interactive OAuth 2.0 PKCE authentication flow for X

## Requirements

- Python 3.12 or higher
- Poetry for dependency management
- X Developer account with OAuth 2.0 app
- Raindrop.io account with API token

## Installation

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/py-x-bookmarks-to-raindrop-sync.git
cd py-x-bookmarks-to-raindrop-sync

# Install with Poetry
poetry install
```

### 2. Set Up X API Credentials

1. Go to the [X Developer Portal](https://developer.x.com/en/portal/dashboard)
2. Create a new project and app (or use an existing one)
3. Under "User authentication settings", configure:
   - **App permissions**: Read and write
   - **Type of App**: Native App (for PKCE without client secret) or Confidential Client
   - **Callback URL**: `http://127.0.0.1:8765/callback`
4. Note your **Client ID** (and **Client Secret** if using Confidential Client)

**Required OAuth 2.0 Scopes:**
- `bookmark.read` - Read your bookmarks
- `bookmark.write` - Remove bookmarks (optional, only if using `--remove-from-x`)
- `tweet.read` - Read tweet data
- `users.read` - Read user profile data
- `offline.access` - Refresh tokens for persistent access

### 3. Set Up Raindrop.io API Token

1. Go to [Raindrop.io Integrations](https://app.raindrop.io/settings/integrations)
2. Under "For Developers", create a new app or use "Test token"
3. Copy the **Test token** for personal use

### 4. Configure the Application

Create a configuration file:

```bash
# Create default config file
poetry run x2raindrop config init

# Edit the config file
nano ~/.config/py-x-bookmarks-to-raindrop-sync/config.toml
```

Or use environment variables:

```bash
# X API credentials
export X_CLIENT_ID="your_client_id"
export X_CLIENT_SECRET="your_client_secret"  # Optional for public clients

# Raindrop.io credentials
export RAINDROP_TOKEN="your_raindrop_token"

# Sync settings
export SYNC_COLLECTION_ID="12345"  # Target collection ID
export SYNC_TAGS="x-bookmark,auto-synced"
export SYNC_REMOVE_FROM_X="false"
export SYNC_LINK_MODE="permalink"  # permalink, first_external_url, or both
```

## Usage

### Authenticate with X

First, authenticate with X using the interactive OAuth 2.0 PKCE flow:

```bash
poetry run x2raindrop x login
```

This will open your browser for authorization. After approving, the tokens are saved locally.

### List Raindrop.io Collections

Find the collection ID you want to sync to:

```bash
poetry run x2raindrop raindrop collections
```

### Sync Bookmarks

Basic sync:

```bash
poetry run x2raindrop sync --collection 12345
```

With options:

```bash
# Sync with custom tags
poetry run x2raindrop sync --collection 12345 --tags "x,bookmarks,auto"

# Use first external URL from tweets
poetry run x2raindrop sync --collection 12345 --link-mode first_external_url

# Remove from X after syncing (use with caution!)
poetry run x2raindrop sync --collection 12345 --remove-from-x

# Dry run - see what would happen without making changes
poetry run x2raindrop sync --collection 12345 --dry-run
```

### Check X Authentication Status

```bash
poetry run x2raindrop x status
```

### Logout from X

```bash
poetry run x2raindrop x logout
```

## Configuration Reference

### Config File Location

Default: `~/.config/py-x-bookmarks-to-raindrop-sync/config.toml`

Override with `--config` flag on any command.

### Config File Format

```toml
log_level = "INFO"

[x]
client_id = "YOUR_X_CLIENT_ID"
client_secret = ""  # Leave empty for public clients
redirect_uri = "http://127.0.0.1:8765/callback"
scopes = [
    "bookmark.read",
    "bookmark.write",
    "tweet.read",
    "users.read",
    "offline.access",
]

[raindrop]
token = "YOUR_RAINDROP_TOKEN"

[sync]
collection_id = 12345
collection_title = ""  # Optional: look up collection by title
tags = ["x-bookmark", "auto-synced"]
remove_from_x = false
link_mode = "permalink"  # permalink, first_external_url, or both
both_behavior = "one_external_plus_note"  # one_external_plus_note or two_raindrops
dry_run = false
```

### Link Modes

| Mode | Description |
|------|-------------|
| `permalink` | Create a Raindrop with the X post URL |
| `first_external_url` | Use the first external URL in the tweet (falls back to permalink if none) |
| `both` | Create entries for both external URL and permalink (behavior configurable) |

### Both Behavior Options

When `link_mode = "both"` and the tweet contains an external URL:

| Option | Description |
|--------|-------------|
| `one_external_plus_note` | Create one Raindrop for the external URL, store X permalink in the note |
| `two_raindrops` | Create two separate Raindrops (one for external URL, one for X permalink) |

## Data Storage

The tool stores data in `~/.config/py-x-bookmarks-to-raindrop-sync/`:

- `config.toml` - Configuration file
- `x_token.json` - X OAuth tokens (keep secure!)
- `state.json` - Sync state for idempotency

## Safety Notes

1. **Dry Run First**: Always use `--dry-run` before syncing to preview changes
2. **Remove from X**: The `--remove-from-x` flag permanently removes bookmarks from X. Use with caution and consider backing up first
3. **Token Security**: The `x_token.json` file contains sensitive tokens. Ensure proper file permissions
4. **Rate Limits**: X API has rate limits. The tool handles pagination but very large bookmark collections may require multiple runs

## Development

### Setup Development Environment

```bash
poetry install --with dev
```

### Run Tests

```bash
poetry run pytest
```

### Run Tests with Coverage

```bash
poetry run pytest --cov=py_x_bookmarks_to_raindrop_sync --cov-report=html
```

### Linting

```bash
poetry run ruff check src tests
poetry run ruff format src tests
```

### Type Checking

```bash
poetry run mypy src
```

## Troubleshooting

### "Not authenticated with X"

Run `x2raindrop x login` to authenticate.

### "Token expired"

The tool automatically refreshes tokens. If issues persist, run `x2raindrop x logout` then `x2raindrop x login`.

### "Collection ID not found"

Run `x2raindrop raindrop collections` to list available collections and their IDs.

### Rate Limit Errors

Wait 15 minutes and try again. X API allows 180 bookmark requests per 15-minute window.

## License

Copyright (c) 2026 Lukas 'dotWee' Wolfsteiner <lukas@wolfsteiner.media>

Licensed under the Do What The Fuck You Want To Public License. See the [LICENSE](LICENSE) file for details.

## Credits

- [python-raindropio](https://github.com/atsuoishimoto/python-raindropio) - Raindrop.io API wrapper
- [X Python XDK](https://docs.x.com/xdks/python/quickstart) - X API documentation
