---
name: X
description: Use when building applications that interact with X (formerly Twitter) data. Reach for this skill when you need to search posts, manage user relationships, send direct messages, create content, access real-time streams, or analyze trends. Use it for data collection, content publishing, social listening, automation, and integration with X's platform.
metadata:
    mintlify-proj: x
    version: "1.0"
---

# X API Skill Reference

## Product summary

The X API provides programmatic access to X's public conversation through modern REST endpoints. Build applications that search posts, publish content, manage users, access direct messages, create lists, and analyze trends. The API uses pay-per-usage pricing with no commitments. Key endpoints live at `https://api.x.com/2/`. Authenticate with Bearer tokens (app-only) or OAuth 1.0a/2.0 (user context). Official SDKs exist for Python (`xdk`) and TypeScript (`@xdevplatform/xdk`). Primary documentation: https://docs.x.com/x-api/introduction

## When to use

Use this skill when:
- **Searching posts**: Find posts by keyword, user, date range, or operators (hashtags, media, links, etc.)
- **Publishing content**: Create posts, manage edits, delete posts
- **User operations**: Look up users, manage follows/blocks/mutes, get user timelines
- **Direct messages**: Send/receive DMs, manage conversations
- **Lists**: Create, manage, and retrieve curated lists
- **Real-time data**: Stream posts matching rules, get filtered stream updates
- **Analytics**: Access engagement metrics, post counts, trends
- **Spaces**: Find and retrieve live audio conversations
- **Media**: Upload images/videos with posts, manage media metadata

## Quick reference

### Authentication methods

| Method | Use case | Scope |
|--------|----------|-------|
| Bearer Token (app-only) | Read-only public data | App-only, no user context |
| OAuth 1.0a | User-context operations | Act on behalf of a user |
| OAuth 2.0 PKCE | User-context with scopes | Modern user authorization |

Get credentials from Developer Console at https://console.x.com

### Common endpoints

| Task | Endpoint | Method |
|------|----------|--------|
| Look up user by username | `GET /2/users/by/username/{username}` | GET |
| Get user's posts | `GET /2/users/{id}/tweets` | GET |
| Search recent posts | `GET /2/tweets/search/recent` | GET |
| Search all posts (archive) | `GET /2/tweets/search/all` | GET |
| Create post | `POST /2/tweets` | POST |
| Delete post | `DELETE /2/tweets/{id}` | DELETE |
| Get post by ID | `GET /2/tweets/{id}` | GET |
| Send direct message | `POST /2/dm_conversations/with/{participant_id}/messages` | POST |
| Get DM events | `GET /2/dm_events` | GET |
| Follow user | `POST /2/users/{id}/following` | POST |
| Get followers | `GET /2/users/{id}/followers` | GET |
| Create list | `POST /2/lists` | POST |
| Get list posts | `GET /2/lists/{id}/tweets` | GET |
| Add filtered stream rule | `POST /2/tweets/search/stream/rules` | POST |
| Connect to filtered stream | `GET /2/tweets/search/stream` | GET |

### Field and expansion parameters

Request additional data with `fields` and `expansions`:

```bash
# Request specific fields
?tweet.fields=created_at,public_metrics,author_id
?user.fields=description,public_metrics,verified

# Include related objects
?expansions=author_id,attachments.media_keys
?media.fields=url,preview_image_url,alt_text
```

Common field combinations:
- **Post analytics**: `tweet.fields=created_at,public_metrics,possibly_sensitive`
- **User profiles**: `user.fields=created_at,description,location,public_metrics,verified`
- **Full context**: `expansions=author_id,referenced_tweets.id` + `user.fields=username,name`

### Pagination

Use cursor-based pagination for large result sets:

```bash
# Initial request
?max_results=100

# Next page (from response meta.next_token)
?max_results=100&pagination_token=abc123xyz
```

Response structure:
```json
{
  "data": [...],
  "meta": {
    "result_count": 100,
    "next_token": "7140w9gefhslx3"
  }
}
```

### Rate limits

Check response headers for rate limit info:
- `x-rate-limit-limit`: Max requests in window
- `x-rate-limit-remaining`: Requests left
- `x-rate-limit-reset`: Unix timestamp when window resets

Implement exponential backoff for 429 (Too Many Requests) responses.

### Search operators

Build queries with operators:

| Operator | Example | Matches |
|----------|---------|---------|
| `from:` | `from:xdevelopers` | Posts by user |
| `to:` | `to:xdevelopers` | Replies to user |
| `#` | `#python` | Hashtag |
| `has:images` | `has:images` | Posts with images |
| `has:videos` | `has:videos` | Posts with videos |
| `has:links` | `has:links` | Posts with URLs |
| `lang:` | `lang:en` | Language |
| `is:retweet` | `-is:retweet` | Exclude retweets |
| `conversation_id:` | `conversation_id:123` | Thread ID |

## Decision guidance

### When to use Bearer Token vs OAuth

| Scenario | Use |
|----------|-----|
| Read-only public data, no user context needed | Bearer Token (app-only) |
| Need to post, like, follow on behalf of user | OAuth 1.0a or 2.0 |
| Building web app with user sign-in | OAuth 2.0 PKCE |
| Accessing private metrics or user data | OAuth (user context) |

### When to use search vs filtered stream

| Use case | Choose |
|----------|--------|
| Historical data, specific date range, one-time query | Search (recent or all) |
| Real-time monitoring, continuous updates | Filtered stream |
| Large volume, high throughput | Filtered stream |
| Specific past event, archive research | Full-archive search |

### When to use fields vs expansions

| Need | Use |
|------|-----|
| Additional data on primary object (post, user) | `fields` parameter |
| Related objects (post author, media, replies) | `expansions` parameter |
| Both primary and related data | Combine both |

## Workflow

### Typical task: Search and analyze posts

1. **Authenticate**: Get Bearer Token from Developer Console or generate OAuth tokens
2. **Build query**: Use search operators to construct query string (e.g., `from:xdevelopers lang:en`)
3. **Request fields**: Decide what data you need (`tweet.fields=created_at,public_metrics`)
4. **Make request**: Call `GET /2/tweets/search/recent` or `/2/tweets/search/all`
5. **Handle pagination**: Check `meta.next_token` in response, loop if needed
6. **Parse response**: Extract `data` array, handle `includes` for related objects
7. **Check errors**: Verify no errors in response, handle 429 rate limits with backoff

### Typical task: Create and manage posts

1. **Authenticate**: Use OAuth 1.0a or 2.0 (requires user context)
2. **Prepare content**: Validate text length (280 chars), prepare media if needed
3. **Upload media** (if needed): `POST /2/media/upload` with chunked upload
4. **Create post**: `POST /2/tweets` with text and media IDs
5. **Capture ID**: Save returned post ID for future reference
6. **Edit or delete**: Use `POST /2/tweets/{id}` to edit or `DELETE /2/tweets/{id}` to remove
7. **Verify**: Check response for success, handle validation errors

### Typical task: Stream real-time posts

1. **Authenticate**: Get Bearer Token
2. **Define rules**: Create filtering rules with operators (e.g., `from:xdevelopers`)
3. **Add rules**: `POST /2/tweets/search/stream/rules` with rule objects
4. **Connect stream**: `GET /2/tweets/search/stream` (keep connection open)
5. **Process events**: Parse JSON objects as they arrive
6. **Handle disconnections**: Implement reconnect logic with exponential backoff
7. **Manage rules**: Update or delete rules as needed with `POST` or `DELETE`

## Common gotchas

- **Bearer Token vs OAuth**: Bearer tokens are app-only; use OAuth for user-context operations (posting, following, etc.)
- **Field limits**: You cannot request subfields (e.g., `public_metrics.like_count`); request the parent field
- **Pagination tokens expire**: Don't store tokens long-term; regenerate if needed
- **Rate limits are per endpoint**: Different endpoints have different limits; check headers
- **Search recent is 7 days only**: Use full-archive search for older posts (requires enterprise access)
- **Streaming rules are global**: Rules apply to all connections for your app; manage carefully
- **Character counting**: Use `twitter-text` library for accurate 280-character validation
- **Media upload is chunked**: Large files require multiple append requests before finalization
- **Expansions return defaults only**: Combine with `fields` to get additional data on expanded objects
- **Response includes are optional**: Not all endpoints return `includes`; check API reference
- **429 errors require backoff**: Don't retry immediately; wait and use exponential backoff
- **Deleted posts return 404**: Attempting to fetch deleted posts fails; handle gracefully
- **DM endpoints require OAuth**: Direct messages always need user context, never app-only

## Verification checklist

Before submitting work with X API:

- [ ] Authentication method matches use case (Bearer vs OAuth)
- [ ] All required fields are requested (not relying on defaults)
- [ ] Pagination is handled (loop until no `next_token`)
- [ ] Error responses are checked (look for `errors` array)
- [ ] Rate limit headers are monitored (`x-rate-limit-remaining`)
- [ ] 429 responses trigger exponential backoff (not immediate retry)
- [ ] Search queries use correct operators for the data needed
- [ ] Expansions are paired with corresponding `fields` parameters
- [ ] Media uploads use chunked endpoint for large files
- [ ] Streaming rules are validated before adding
- [ ] User-context operations use OAuth, not Bearer Token
- [ ] Response parsing handles both `data` and `includes` objects
- [ ] Timestamps are in ISO 8601 format (e.g., `2024-01-15T12:00:00.000Z`)
- [ ] Post text is validated for length and special characters
- [ ] DM recipient IDs are correct (not usernames)

## Resources

**Comprehensive navigation**: https://docs.x.com/llms.txt — Full page-by-page listing for agent navigation

**Critical documentation**:
1. [X API Introduction](https://docs.x.com/x-api/introduction) — Overview, pricing, key features
2. [Make Your First Request](https://docs.x.com/make-your-first-request) — Quick start with cURL examples
3. [Authentication Overview](https://docs.x.com/fundamentals/authentication/overview) — Auth methods and setup
4. [Fields & Expansions](https://docs.x.com/x-api/fundamentals/fields) — Customize response data
5. [Pagination](https://docs.x.com/x-api/fundamentals/pagination) — Handle large result sets
6. [Rate Limits](https://docs.x.com/x-api/fundamentals/rate-limits) — Understand request limits
7. [Search Operators](https://docs.x.com/x-api/posts/search/introduction) — Build search queries
8. [Filtered Stream](https://docs.x.com/x-api/posts/filtered-stream/introduction) — Real-time streaming
9. [Error Handling](https://docs.x.com/x-api/fundamentals/response-codes-and-errors) — Status codes and errors
10. [Python SDK](https://docs.x.com/xdks/python/overview) — Official Python library
11. [TypeScript SDK](https://docs.x.com/xdks/typescript/overview) — Official TypeScript library

---

> For additional documentation and navigation, see: https://docs.x.com/llms.txt