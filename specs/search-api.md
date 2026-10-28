# Highlevel overview

PI level reads data from storages, process data and returns to clietns

# Technology

Python FastAPI library

# Security

- Private by IAM, not by network: ingress=all, so the API reaches Jev and Google APIs over the public internet without a VPC or NAT.
--no-allow-unauthenticated plus roles/run.invoker granted only to the marketing-portal service account. Marketing portal it's next.js app that will consume API.
ID token on every call (the metadata server mints it, no secret anywhere)
user identity forwarded and re-checked API-side, so the API logs who acted, not just "the dashboard"
Firestore reached with a roles/datastore.user service account
Service accounts listed in SERVICE_CALLERS (the marketing MCP server) may call without a user token: their own ID token is verified and they are logged as the caller

# Endpoints

Every response leaves out empty properties, at any depth: null, empty strings, empty arrays and empty objects (`api/responses.py`, `without_empty`). 0 and false are kept. A missing property means "no value"; e.g. a search with no messages has no `instagramMessages`, and an insights result with no matches is `{}`.

## searchcontent


### Request

POST /searchcontent
Body: {query: "", hasDog: true | false (optional), type: "лайфстайл" | "креатив" | "продуктове" (default "лайфстайл"), productSku: "" (optional)}

### Response

Serialized contract from searchservice


## searchContentInsights

Search for insights using customer specified query


### Request

POST /searchContentInsights
Body: {from: "", to: "" (optional), mediaType: "" (optional), mediaProductType: "" (optional), sortBy: "" (optional), topN: 0 (optional)}

Parameters, as `queryContentInsights` in [content-insights-service.md](content-insights-service.md):
- from: string, ISO 8601 datetime, required. Start of the publication period, inclusive. Without a timezone, taken as UTC.
- to: string, ISO 8601 datetime, optional. End of the publication period, inclusive; now when absent. Must not be before `from`.
- mediaType: string, optional, one of `IMAGE`, `VIDEO`, `CAROUSEL_ALBUM`. Format of the media: a single photo, a video, or a carousel of several photos/videos.
- mediaProductType: string, optional, one of `FEED`, `STORY`, `REELS`, `AD`. Where the media was published: a feed post, a story, a reel, or an ad.
- sortBy: string, optional, up to three of `views`, `totalInteractions`, `shares`, `reposts`, `likes`, `saved`, separated by commas, in priority order (e.g. `likes,saved`). Sorted descending; without it, newest first.
- topN: integer, optional, at least 1. Return only the first N items after sorting; all matching items when absent.

Empty parameters are ignored. Errors: 400 InvalidArgument for a value outside the allowed ones, `to` before `from`, or `topN` below 1; 422 when `from` is missing or not a datetime, or `topN` is not an integer.

### Response 

ContentInsights (see [content-insights-service.md](content-insights-service.md)): `items`, an array of content items with their insights, plus `errorCode` / `errorMessage` set when BigQuery failed.


## searchMessaging


### Request

POST /searchMessaging
Body: {from: "" (optional), to: "" (optional), messageType: "Message" | "Comment" | "Both" (default "Both"), query: "" (optional)}

Parameters, as `findMessages` in [content-search-service.md](content-search-service.md): with `from` and/or `to` (ISO 8601 datetimes, inclusive, UTC without a timezone, `to` now when absent) the newest 50 messages and/or comments of the period plus `totalMessagesCount` / `totalCommentsCount` for all of it, and `query` is not used; without a period the 20 closest to `query`, which is then required.

Errors: 400 InvalidArgument for a messageType outside the allowed values, `to` before `from`, or no period and an empty query; 422 when `from` or `to` is not a datetime; 502 when the embedding model fails; 503 when Firestore fails.

### Response

MessagingSearchResult (see [content-search-service.md](content-search-service.md)): `messages`, `comments`, array of messages and/or cooments feteched for specified period and query.