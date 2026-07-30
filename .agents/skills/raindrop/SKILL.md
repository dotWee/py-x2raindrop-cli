---
name: raindrop
description: Use when building applications that interact with Raindrop.io bookmarks ("raindrops") and collections. Reach for this skill when agents need to create, search, update, or delete bookmarks, manage collections, handle OAuth2 authentication or test tokens, work with REST API endpoints, batch operations, tags, highlights, import/export, or manage rate limits. Covers both raw REST calls and the python-raindropio library used in this repo.
metadata:
    docs: https://developer.raindrop.io
    version: "1.0"
---

# Raindrop.io API Skill Reference

## Product summary

Raindrop.io is a bookmark manager. Its public REST API (v1) lets agents read,
create, update, and delete bookmarks (called **raindrops**) and organize them
into **collections**. Authentication is OAuth2; a per-app **test token** is
available for single-account use without the full OAuth dance. The API base URL
is `https://api.raindrop.io/rest/v1/`. Register apps and grab credentials at the
[App Management Console](https://app.raindrop.io/settings/integrations). Primary
docs: <https://developer.raindrop.io> (append `.md` to any page URL for a clean
Markdown version, e.g. `https://developer.raindrop.io/v1/raindrops/multiple.md`).

In **this repository** Raindrop access goes through the `python-raindropio`
library wrapped by `src/x2raindrop_cli/raindrop/client.py`. That wrapper uses the
library's `API`, `Collection`, `CollectionRef`, and `Raindrop` objects for most
work, and drops down to raw `api.get(...)` / `api.post(...)` calls for the bulk
create and search-existence endpoints the library doesn't cover.

## When to use

Reach for this skill when:

- Creating bookmarks one at a time or in batches (up to 100 per request)
- Searching, listing, or paginating raindrops within a collection
- Checking whether a link already exists (de-duplication)
- Managing collections (root/child lookup, create, update, move, merge)
- Handling OAuth2 token exchange/refresh or using a test token
- Working with tags, highlights, covers, reminders, or import/export
- Debugging API errors (401, 429, validation errors) or rate limits
- Extending or modifying `RaindropClient` in this repo

## Quick reference

### Authentication

| Method | Use case | How |
|:-------|:---------|:----|
| **Test token** | Your own account, scripts, prototyping | Copy from app settings; use directly as Bearer token |
| **OAuth2** | Acting on behalf of other users | Full authorize → code → token exchange flow |

All authorized calls send the token in a header:

```bash
curl "https://api.raindrop.io/rest/v1/user" \
     -H "Authorization: Bearer $RAINDROP_TOKEN"
```

OAuth2 access tokens (not test tokens) **expire after two weeks** — refresh with
the `refresh_token`. Token responses include `expires_in` (seconds; the
`expires` field in ms is deprecated).

### Base URL and core endpoints

Base: `https://api.raindrop.io/rest/v1/`

| Resource | Endpoint | Method | Use |
|:---------|:---------|:-------|:----|
| Get raindrop | `/raindrop/{id}` | GET | Single bookmark by ID |
| Create raindrop | `/raindrop` | POST | Create one bookmark |
| Update raindrop | `/raindrop/{id}` | PUT | Edit one bookmark |
| Remove raindrop | `/raindrop/{id}` | DELETE | Move to Trash (or purge if already in Trash) |
| List raindrops | `/raindrops/{collectionId}` | GET | List/search within a collection |
| Create many | `/raindrops` | POST | Batch create — **max 100 items** |
| Update many | `/raindrops/{collectionId}` | PUT | Batch update (filter by `ids`/`search`) |
| Remove many | `/raindrops/{collectionId}` | DELETE | Batch delete (filter by `ids`/`search`) |
| Suggest | `/raindrop/suggest` | POST | Suggest collection + tags for a new link |
| Root collections | `/collections` | GET | Top-level collections |
| Child collections | `/collections/childrens` | GET | Nested collections |
| Get collection | `/collection/{id}` | GET | Single collection |
| Create collection | `/collection` | POST | New collection |
| User / stats | `/user`, `/user/stats` | GET | Account info, system collection counts |

### System collection IDs

| ID | Meaning |
|:---|:--------|
| `0` | All raindrops except Trash (read-only for update/remove) |
| `-1` | Unsorted |
| `-99` | Trash (DELETE here purges permanently) |

### Key raindrop fields (request/response)

| Field | Type | Notes |
|:------|:-----|:------|
| `link`* | String | URL — the only required field on create |
| `title` | String | max 1000 chars |
| `excerpt` | String | description, max 10000 |
| `note` | String | max 10000 (separate from `excerpt`) |
| `tags` | Array | list of strings |
| `collection` | Object | `{"$id": collectionId}` to place/move |
| `important` | Boolean | "favorite" flag |
| `cover` / `media` | String / Array | cover URL; media list `[{"link":"url"}]` |
| `type` | String | `link` `article` `image` `video` `document` `audio` |
| `highlights` | Array | `{text, color, note}`; color e.g. `yellow`, `blue`, `green`... |
| `reminder` | Object | `{"data": "YYYY-MM-DDTHH:mm:ss.sssZ"}` |
| `pleaseParse` | Object | send `{}` to auto-parse cover/description/html in background |

> The API may return undocumented fields — do not depend on them; they can change.

### List/search query parameters (`/raindrops/{collectionId}`)

| Param | Type | Notes |
|:------|:-----|:------|
| `search` | String | Raindrop search syntax (test it in the app first) |
| `sort` | String | `-created` (default), `created`, `score`, `-sort`, `title`, `-title`, `domain`, `-domain` |
| `page` | Integer | 0-based |
| `perpage` | Integer | **50 max** |
| `nested` | Boolean | include nested collections |

### Response shape

```json
{ "result": true, "item": { } }        // single
{ "result": true, "items": [ ] }       // list / batch create
{ "result": true, "modified": 330 }    // batch update/remove count
```

Most successful responses include `"result": true`. Errors carry
`"result": false`, an `error` code, and an `errorMessage`.

### Rate limiting

120 requests/minute per authenticated user. Watch the headers and back off on
`429`:

- `X-RateLimit-Limit` — max requests in the window
- `X-RateLimit-Remaining` — requests left
- `X-RateLimit-Reset` — UTC epoch seconds until reset

## Using the python-raindropio library (this repo)

```python
from raindropio import API, Collection, CollectionRef, Raindrop

api = API(token)                       # token = test token or OAuth access token

# List collections
roots = Collection.get_roots(api)
kids = Collection.get_childrens(api)

# Create one raindrop
rd = Raindrop.create(
    api,
    link="https://example.com",
    collection=CollectionRef.Unsorted,   # or CollectionRef({"$id": 12345})
    tags=["x", "import"],
    title="Example",
    excerpt="A short description",
)

# Search Unsorted, page by page
page = 0
while items := Raindrop.search(api, collection=CollectionRef.Unsorted, page=page):
    for item in items:
        print(item.title)
    page += 1

api.close()
```

### When to drop to raw HTTP

The library has no first-class **bulk create** or lightweight **existence check**, so this repo calls the REST endpoints directly through the same authenticated session (see `RaindropClient.create_raindrops` and `check_link_exists`):

```python
# Bulk create — max 100 per call; split larger lists into batches
payload = {"items": [{"link": "...", "collection": {"$id": 12345}, "tags": [...]}]}
resp = api.post("https://api.raindrop.io/rest/v1/raindrops", json=payload)
resp.raise_for_status()
items = resp.json()["items"]   # same order as request items

# Existence / search within a collection (0 = all)
resp = api.get(
    "https://api.raindrop.io/rest/v1/raindrops/0"
    "?search=https%3A%2F%2Fexample.com&perpage=100"
)
```

Notes from the existing wrapper worth preserving:

- Bulk responses return items **in request order** — zip them back together.
- IDs may appear as `_id` (raw REST) or `id` (library object); handle both.
- Normalize links (strip + drop trailing `/`) before comparing for duplicates.
- `note` has no dedicated slot in the library's `Raindrop.create`; this repo
  falls back to `excerpt` when only a note is provided.

## Decision guidance

| Scenario | Choose | Why |
|:---------|:-------|:----|
| **One bookmark vs. many** | `/raindrops` bulk for >1 | One request instead of N; respects rate limits |
| **>100 items to create** | Split into batches of 100 | Hard API cap; >100 is rejected |
| **Library object vs. raw HTTP** | Library for CRUD, raw for bulk/search-existence | Library covers common cases; raw fills the gaps |
| **Test token vs. OAuth2** | Test token for own account | Skip OAuth entirely for personal/single-user scripts |
| **De-dupe before insert** | Search by `link` first | Avoids duplicate raindrops; `0` searches all collections |
| **Auto-parse metadata** | Send `pleaseParse: {}` | Lets Raindrop fetch cover/description in background |
| **Move vs. recreate** | Update `collection.$id` | Cheaper than delete+create; preserves history |

## Workflow

1. **Set up credentials**
   - Create an app at the App Management Console
   - Use the **test token** for your own account, or run OAuth2 for multi-user
   - Store the token in an env var (e.g. `RAINDROP_TOKEN`); never hardcode

2. **Resolve the target collection**
   - List roots + children, or use a system ID (`-1` Unsorted, `0` all, `-99` Trash)
   - Reference collections as `{"$id": id}` in payloads

3. **Build the request**
   - Single: POST `/raindrop` with at least `link`
   - Batch: POST `/raindrops` with `{"items": [...]}`, ≤100 items
   - Add `tags`, `title`, `excerpt`, `pleaseParse: {}` as needed

4. **Handle the response**
   - Check `result` is `true`; read `item`/`items`
   - For batch, map results back to inputs by order; read `_id`/`id`
   - For batch update/remove, read `modified` count

5. **Manage rate limits**
   - Stay under 120 req/min; watch `X-RateLimit-Remaining`
   - On `429`, wait until `X-RateLimit-Reset` (exponential backoff)
   - Prefer batch endpoints over per-item loops

6. **Verify**
   - Re-fetch or search to confirm creates/updates landed
   - Test search strings in the Raindrop app before encoding them into params

## Common gotchas

- **Bulk cap is 100**: `/raindrops` rejects more than 100 items; chunk larger lists.
- **`perpage` maxes at 50**: paginate with `page` (0-based) for full collections.
- **`link` is the only required create field**: everything else is optional.
- **DELETE moves to Trash**: it isn't permanent unless the raindrop is already in Trash, or you DELETE against collection `-99`.
- **`collection: 0` not supported for update/remove**: use a real ID, `-1`, or `-99`.
- **`_id` vs `id`**: raw REST uses `_id`; library objects expose `id`. Handle both when parsing bulk responses.
- **Token expiry**: OAuth2 tokens die after ~2 weeks — refresh; test tokens don't expire.
- **`expires` is deprecated**: use `expires_in` (seconds) from token responses.
- **URL-encode `search`**: encode the link/query, especially `://` and `&`.
- **Trailing-slash duplicates**: normalize links before existence checks.
- **`note` vs `excerpt`**: distinct fields in REST; the library exposes `excerpt` more readily.
- **OAuth redirect URI must match exactly**: same value in authorize and token-exchange steps.

## Verification checklist

Before submitting work:

- [ ] Token comes from an env var, not hardcoded
- [ ] Base URL is `https://api.raindrop.io/rest/v1/`
- [ ] `Authorization: Bearer <token>` header is set on every call
- [ ] Required `link` present on every created raindrop
- [ ] Batch payloads use `{"items": [...]}` and are split to ≤100
- [ ] Collections referenced as `{"$id": id}`; system IDs (`-1`/`0`/`-99`) used correctly
- [ ] List/search uses `perpage` ≤ 50 and paginates with `page`
- [ ] `search` values are URL-encoded
- [ ] Responses checked for `result === true`; errors handled via `error`/`errorMessage`
- [ ] Batch results mapped back to inputs by order; `_id`/`id` both handled
- [ ] Rate-limit headers monitored; `429` backoff implemented
- [ ] Links normalized before duplicate checks
- [ ] Tested against the real API, not just mocks

## Resources

- **Docs home**: <https://developer.raindrop.io> — append `.md` to any page for Markdown
- **Docs index (agent-friendly)**: <https://developer.raindrop.io/llms.txt>
- **Authentication / tokens**: <https://developer.raindrop.io/v1/authentication/token>
- **Single raindrop**: <https://developer.raindrop.io/v1/raindrops/single>
- **Multiple raindrops (batch)**: <https://developer.raindrop.io/v1/raindrops/multiple>
- **Raindrop fields**: <https://developer.raindrop.io/v1/raindrops>
- **Collection methods**: <https://developer.raindrop.io/v1/collections/methods>
- **Python library**: <https://github.com/atsuoishimoto/python-raindropio>
- **Raindrop on GitHub**: <https://github.com/raindropio>
- **Dynamic Q&A**: GET any `<page>.md?ask=<question>` for targeted answers

---

> For the full page-by-page index, see <https://developer.raindrop.io/llms.txt>
