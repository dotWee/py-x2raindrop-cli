# x2raindrop-cli

A Python CLI tool to sync your X (Twitter) bookmarks to Raindrop.io collections.

[![PyPI version](https://badge.fury.io/py/x2raindrop-cli.svg)](https://badge.fury.io/py/x2raindrop-cli)
[![Docker Image](https://ghcr-badge.egpl.dev/dotwee/x2raindrop-cli/latest_tag?trim=major&label=docker)](https://ghcr.io/dotwee/x2raindrop-cli)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-WTFPL-green.svg)](LICENSE)

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

### From PyPI (Recommended)

```bash
pip install x2raindrop-cli
```

### From Source

```bash
git clone https://github.com/dotWee/x2raindrop-cli.git
cd x2raindrop-cli

# Install with Poetry
poetry install
```

### Using Docker

Pull the image from GitHub Container Registry:

```bash
docker pull ghcr.io/dotwee/x2raindrop-cli:latest
```

Run commands by mounting your local directory (for config and state persistence):

```bash
# Show help
docker run --rm ghcr.io/dotwee/x2raindrop-cli --help

# Initialize config in current directory
docker run --rm -v "$PWD":/data ghcr.io/dotwee/x2raindrop-cli config init

# Sync bookmarks
docker run --rm -v "$PWD":/data ghcr.io/dotwee/x2raindrop-cli sync --collection 12345
```

See the [Docker Usage](#docker-usage) section for more details.

### 2. Set Up X API Credentials

You have two options for X authentication:

#### Option A: Direct Access Token (Simplest)

If you already have an access token (e.g., from another OAuth flow or the X Developer Portal):

1. Set `X_ACCESS_TOKEN` in your config or environment
2. No browser login required - just run sync directly

```toml
[x]
access_token = "your_access_token_here"
```

#### Option B: OAuth 2.0 PKCE Flow (Interactive)

For browser-based login:

1. Go to the [X Developer Portal](https://developer.x.com/en/portal/dashboard)
2. Create a new project and app (or use an existing one)
3. Under "User authentication settings", configure:
   - **App permissions**: Read and write
   - **Type of App**: Native App (for PKCE without client secret) or Confidential Client
   - **Callback URL**: `http://127.0.0.1:8765/callback`
4. Note your **Client ID** (and **Client Secret** if using Confidential Client)
5. Run `x2raindrop x login` to authenticate

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
# Create default config file in current directory
poetry run x2raindrop config init

# Edit the config file
nano config.toml
```

Or use environment variables:

```bash
# X API credentials (choose one method)
# Option A: Direct access token
export X_ACCESS_TOKEN="your_access_token"

# Option B: OAuth PKCE flow (then run `x2raindrop x login`)
export X_CLIENT_ID="your_client_id"
export X_CLIENT_SECRET="your_client_secret"  # Optional for public clients

# Raindrop.io credentials
export RAINDROP_TOKEN="your_raindrop_token"

# Sync settings
export SYNC_COLLECTION_ID="12345"  # Target collection ID
export SYNC_TAGS='["x-bookmark", "auto-synced"]'  # JSON array format
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

Default: `config.toml` in the current working directory (project root).

Override with `--config` flag on any command.

### Config File Format

```toml
log_level = "INFO"

[x]
# Option A: Direct access token (simplest - no browser login needed)
access_token = ""

# Option B: OAuth PKCE flow (use `x2raindrop x login`)
client_id = ""
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

The tool stores data in the current working directory:

- `config.toml` - Configuration file
- `.x2raindrop/x_token.json` - X OAuth tokens (keep secure!)
- `.x2raindrop/state.json` - Sync state for idempotency

## Safety Notes

1. **Dry Run First**: Always use `--dry-run` before syncing to preview changes
2. **Remove from X**: The `--remove-from-x` flag permanently removes bookmarks from X. Use with caution and consider backing up first
3. **Token Security**: The `x_token.json` file contains sensitive tokens. Ensure proper file permissions

## X API Rate Limits

**IMPORTANT**: X API has strict rate limits, especially on the Free Tier.

| Tier | Rate Limit | Notes |
|------|------------|-------|
| Free | 1 request / 15 min | Very limited - sync may take a long time |
| Basic | Higher limits | Check X Developer Portal for current limits |

**API Request Breakdown:**
- Fetching bookmarks: 1 request per 100 bookmarks (paginated)
- Deleting a bookmark: 1 request per bookmark

**Automatic Rate Limit Handling:**
The tool automatically handles rate limit errors (429 Too Many Requests):
- Detects rate limit responses from the X API
- Parses `x-rate-limit-reset` or `Retry-After` headers to determine wait time
- Automatically waits and retries (up to 5 times)
- Logs wait time and progress so you can monitor

**Recommendations for Free Tier:**
1. **Don't use `--remove-from-x`** - each deletion is a separate request
2. Be patient - the tool will automatically wait when rate limited
3. The tool tracks synced bookmarks locally, so interrupted syncs can resume
4. Consider upgrading to Basic tier if you have many bookmarks

## Docker Usage

The Docker image provides a convenient way to run x2raindrop-cli without installing Python dependencies locally.

### Pulling the Image

```bash
# Latest version
docker pull ghcr.io/dotwee/x2raindrop-cli:latest

# Specific version
docker pull ghcr.io/dotwee/x2raindrop-cli:1.0.0
```

### Running Commands

The container's working directory is `/data`. Mount your local directory there to persist configuration and state:

```bash
# Create an alias for convenience
alias x2raindrop='docker run --rm -v "$PWD":/data ghcr.io/dotwee/x2raindrop-cli'

# Now use it like the native CLI
x2raindrop --version
x2raindrop config init
x2raindrop raindrop collections
x2raindrop sync --collection 12345 --dry-run
```

### Using Environment Variables

Pass credentials via environment variables instead of a config file:

```bash
docker run --rm \
  -e X_ACCESS_TOKEN="your_token" \
  -e RAINDROP_TOKEN="your_raindrop_token" \
  -e SYNC_COLLECTION_ID="12345" \
  -v "$PWD":/data \
  ghcr.io/dotwee/x2raindrop-cli sync
```

### OAuth Authentication in Docker

The interactive OAuth 2.0 PKCE flow (`x2raindrop x login`) requires a browser, which doesn't work well inside a container. You have two options:

**Option 1: Use a Direct Access Token (Recommended for Docker)**

Set `X_ACCESS_TOKEN` in your config or as an environment variable. No browser login required.

**Option 2: Authenticate on Host, Then Use in Docker**

1. Install the CLI locally and run `x2raindrop x login` on your host machine
2. This creates `.x2raindrop/x_token.json` in your current directory
3. Mount that directory when running Docker:

```bash
docker run --rm -v "$PWD":/data ghcr.io/dotwee/x2raindrop-cli sync --collection 12345
```

The container will use the token file from your mounted directory.

### Data Persistence

The container stores data in `/data` (the working directory):

| File | Purpose |
|------|---------|
| `config.toml` | Configuration file |
| `.x2raindrop/x_token.json` | X OAuth tokens |
| `.x2raindrop/state.json` | Sync state for idempotency |

Always mount a volume to `/data` to persist this data between runs.

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
poetry run pytest --cov=x2raindrop_cli --cov-report=html
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
