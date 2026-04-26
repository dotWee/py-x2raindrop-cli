---
name: X
description: Use when building applications that interact with X (formerly Twitter) data and functionality. Reach for this skill when agents need to search posts, manage user interactions, stream real-time data, handle authentication, work with API endpoints, manage rate limits, or integrate X data into applications.
metadata:
    mintlify-proj: x
    version: "1.0"
---

# X API Skill Reference

## Product summary

The X API provides programmatic access to X's public conversation through REST endpoints. Agents use it to read posts, publish content, manage users, search archives, stream real-time data, and analyze trends. The API uses pay-per-usage pricing with flexible authentication methods (OAuth 1.0a, OAuth 2.0, Bearer tokens). Key files: Developer Console at console.x.com for app credentials; API base URL is `https://api.x.com/2/`. Official SDKs available for Python (`xdk`) and TypeScript (`@xdevplatform/xdk`). Primary docs: https://docs.x.com/x-api/introduction

## When to use

Reach for this skill when:
- Building applications that read, search, or publish posts
- Integrating user authentication (OAuth flows)
- Streaming real-time posts or managing filtered rules
- Looking up user profiles, followers, or relationships
- Managing direct messages, lists, bookmarks, or spaces
- Handling API authentication, rate limits, or error responses
- Paginating through large result sets
- Requesting specific data fields or related objects via expansions
- Debugging API errors (401, 403, 429, etc.)
- Choosing between recent search (7 days) vs. full-archive search

## Quick reference

### Authentication methods

| Method | Use case | Scope |
|:-------|:---------|:------|
| **Bearer Token** | App-only, public data | Read-only, no user context |
| **OAuth 1.0a** | User-context requests, actions on behalf of user | Read, write, DMs (3 levels) |
| **OAuth 2.0** | Modern user-context, fine-grained scopes | Recommended for new projects |
| **Basic Auth** | Enterprise APIs only | Server-to-server |

### Common endpoints

| Resource | Endpoint | Method | Use |
|:---------|:---------|:-------|:----|
| User lookup | `/2/users/by/username/:username` | GET | Get user by username |
| Post lookup | `/2/tweets/:id` | GET | Get post by ID |
| Recent search | `/2/tweets/search/recent` | GET | Search last 7 days |
| Full-archive search | `/2/tweets/search/all` | GET | Search all posts (paid) |
| Filtered stream | `/2/tweets/search/stream` | GET | Real-time posts matching rules |
| Create post | `/2/tweets` | POST | Publish a post |
| User timeline | `/2/users/:id/tweets` | GET | Get user's posts |
| Followers | `/2/users/:id/followers` | GET | Get user's followers |

### Field parameters

Request additional data with field parameters:

```bash
# Post fields
?tweet.fields=created_at,public_metrics,lang,author_id

# User fields
?user.fields=created_at,description,public_metrics,verified

# Media fields
?media.fields=url,preview_image_url,alt_text

# Expansions (include related objects)
?expansions=author_id,referenced_tweets.id
```

### Rate limit headers

Every response includes:
- `x-rate-limit-limit` — max requests in window
- `x-rate-limit-remaining` — requests left
- `x-rate-limit-reset` — Unix timestamp when window resets

### Response structure

```json
{
  "data": { /* primary result */ },
  "includes": { /* related objects from expansions */ },
  "meta": { /* pagination, result count */ }
}
```

## Decision guidance

| Scenario | Choose | Why |
|:---------|:-------|:----|
| **Search recent vs. full-archive** | Recent if <7 days old | Recent is free; full-archive requires paid access |
| **Bearer token vs. OAuth** | Bearer for public data only | OAuth needed for user-context actions (post, like, DM) |
| **Filtered stream vs. polling** | Filtered stream for real-time | Stream is efficient; polling wastes rate limits |
| **Pagination vs. since_id** | Pagination for backfill | since_id for incremental updates (fewer API calls) |
| **Fields vs. expansions** | Fields for object's own data | Expansions for related objects (author, media, etc.) |

## Workflow

1. **Set up credentials**
   - Create app at console.x.com
   - Generate Bearer Token (app-only) or OAuth credentials (user-context)
   - Store securely; never commit to code

2. **Choose authentication method**
   - Public data only? Use Bearer Token
   - Need user actions? Use OAuth 1.0a or 2.0
   - Check endpoint docs for required auth type

3. **Build the request**
   - Identify endpoint (search, lookup, manage, stream)
   - Add required parameters (query, user_id, etc.)
   - Request fields and expansions for needed data
   - Set max_results and pagination_token if needed

4. **Handle the response**
   - Check HTTP status code (200 = success, 4xx/5xx = error)
   - Parse `data` field for primary results
   - Check `includes` for related objects
   - Use `meta.next_token` for pagination

5. **Manage rate limits**
   - Monitor `x-rate-limit-remaining` header
   - Implement exponential backoff for 429 errors
   - Cache responses when possible
   - Use streaming instead of polling for real-time data

6. **Verify and test**
   - Test with cURL or Postman first
   - Check error responses match expected format
   - Verify pagination works for large result sets
   - Confirm fields/expansions return expected data

## Common gotchas

- **Missing Bearer Token**: Ensure token is in `Authorization: Bearer $TOKEN` header, not as query parameter
- **Forgetting expansions**: Requesting `author_id` field without `expansions=author_id` returns only the ID, not author details
- **Rate limit confusion**: Rate limits and billing are separate; you can hit rate limits without incurring costs
- **Protected accounts**: Posts from protected accounts only visible with user authorization; returns 403 otherwise
- **Pagination tokens expire**: Don't store tokens long-term; regenerate if needed
- **Query length limits**: Recent search = 512 chars, full-archive = 1,024 chars (4,096 for Enterprise)
- **Stream rules limit**: Filtered stream allows max 1,000 rules; hitting cap returns error
- **Deleted posts return 404**: Don't assume post exists; handle 404 gracefully
- **Partial errors in batch requests**: 200 response may include both `data` and `errors` array; check both
- **OAuth 2.0 callback URLs**: Must match exactly in Developer Console (including trailing slashes); use `http://127.0.0.1` for local dev, not `localhost`

## Verification checklist

Before submitting work:

- [ ] Authentication credentials are correct and not hardcoded
- [ ] Endpoint URL matches API docs (base: `https://api.x.com/2/`)
- [ ] Required parameters are included (query, user_id, etc.)
- [ ] Field parameters use correct syntax (`tweet.fields=`, `user.fields=`, etc.)
- [ ] Expansions are paired with field parameters for related objects
- [ ] Error handling checks HTTP status code and `errors` array
- [ ] Rate limit headers are monitored (implement backoff for 429)
- [ ] Pagination logic handles `next_token` correctly
- [ ] Response parsing handles both `data` and `includes` objects
- [ ] OAuth tokens are stored securely (env vars, not code)
- [ ] Tested with actual API (not just mock data)

## Resources

- **Comprehensive navigation**: https://docs.x.com/llms.txt — Full page-by-page listing for agent reference
- **Getting started**: https://docs.x.com/x-api/introduction — Overview and quick start
- **Authentication guide**: https://docs.x.com/fundamentals/authentication/overview — All auth methods explained
- **Rate limits reference**: https://docs.x.com/x-api/fundamentals/rate-limits — Per-endpoint limits and handling

---

> For additional documentation and navigation, see: https://docs.x.com/llms.txt