# Highlevel description

Solution implements RAG - Retrieval Augmented Generation for content insights fetched from instagram via meta api graph.facebook.com. 
Facebook path is used for login.


# Architecture

Solution consist from several components:
- BigQuery database on google cloud - `instagram_insights`
- insights_sync job that runs on schedulle, fetches insights data and stores in bigquery table. Specification can be found in @specs/meta/insights.md
Add job under `routines` folder. Initial sync will be done reading from csv files in @specs folder.
- ContentInsightsService fetches data from BigQuery with filtering and sorting applied.
- Story webhook: a public Cloud Run service that receives Meta's `story_insights` notifications and stores them in `organic`. Setup as in @specs/meta/webhooks.md.


## BigQuery database

BigQuery dataset `instagram_insights` (location `europe-central2`) contains two tables - `organic`, `ads`.


### Organic collection schema

BigQuery table `organic`, one row per post, reel or story, keyed by `id`. Partitioned by month on `timestamp` with a partition filter required, so every query must bound `timestamp`; clustered by `mediaProductType`, `mediaType`, `totalInteractions`.

Metrics are lifetime values. A metric the API returns no value for is stored as NULL, never 0.

- id: STRING, required
- timestamp: TIMESTAMP, required
- mediaType: STRING(50), required
- mediaProductType: STRING(50), required
- caption: STRING(2500), nullable
- mediaUrl: STRING(2000), nullable
- thumbnailUrl: STRING(2000), nullable
- permaLink: STRING, nullable
- views: INTEGER, nullable
- reach: INTEGER, nullable
- likes: INTEGER, nullable
- comments: INTEGER, nullable
- saved: INTEGER, nullable
- shares: INTEGER, nullable
- reposts: INTEGER, nullable
- totalInteractions: INTEGER, nullable
- profileVisits: INTEGER, nullable
- follows: INTEGER, nullable
- replies: INTEGER, nullable
- link_clicks: INTEGER, nullable
- navigation: INTEGER, nullable
- reelAvgWatchTime: INTEGER, nullable
- reelViewTotalTime: INTEGER, nullable
- reelSkipRate: FLOAT, nullable, percentage


### Ads collection schema


## Sync job

Purpose of sync job is to fetch data using meta graph api and store it in bigquery. Job runs once per week, every Sunday at 00:00 Europe/Kyiv, and syncs only media product types FEED, REELS and AD.
Each sync fetches content within [now - 30d, now] time period. 
For stories, which expire every 24h, sync will be done via callback on a public webhook endpoint (see Story webhook).

- Code: `routines/insights_sync`, run as `insights-sync [--days N]` (default 30).
- Lists the account's media newest first and stops at the first one older than the period; only FEED, REELS and AD are synced, stories (STORY) come only through the webhook.
- AD media are asked for the FEED metrics.
- Asks each media's insights with the metrics its media product type supports (@specs/meta/insights.md); a request with an unsupported metric fails as a whole.
- Rows are merged into `organic` by `id`: an existing row is updated with the latest numbers, a new one inserted. Re-running is harmless.
- A media whose insights the API refuses (e.g. posted before the account became professional) is logged and skipped; the others are still stored. Failing to list media or to write to BigQuery fails the job.

Metric to column:

| Graph API metric | Column | Media product types |
|---|---|---|
| views | views | FEED, REELS, STORY |
| reach | reach | FEED, REELS, STORY |
| likes | likes | FEED, REELS |
| comments | comments | FEED, REELS |
| saved | saved | FEED, REELS |
| shares | shares | FEED, REELS, STORY |
| reposts | reposts | FEED, REELS, STORY |
| total_interactions | totalInteractions | FEED, REELS, STORY |
| profile_visits | profileVisits | FEED, STORY |
| follows | follows | FEED, STORY |
| replies | replies | STORY |
| link_clicks | link_clicks | STORY |
| navigation (total) | navigation | STORY |
| ig_reels_avg_watch_time | reelAvgWatchTime | REELS |
| ig_reels_video_view_total_time | reelViewTotalTime | REELS |
| reels_skip_rate | reelSkipRate | REELS |

Media fields: `id`, `timestamp`, `media_type` → `mediaType`, `media_product_type` → `mediaProductType`, `caption` (cut to 2500), `media_url` → `mediaUrl`, `thumbnail_url` → `thumbnailUrl`, `permalink` → `permaLink`. A URL longer than its column (2000) is stored as NULL rather than cut.

## Story webhook

- Code: `search-api/src/webhook`, a FastAPI app deployed as its own public Cloud Run service; the search API stays private.
- `GET /meta/webhook`: Meta's verification; answers `hub.challenge` when `hub.mode` is `subscribe` and `hub.verify_token` equals `META_WEBHOOK_VERIFY_TOKEN`, else 403.
- `POST /meta/webhook`: accepted only with a valid `X-Hub-Signature-256` (HMAC-SHA256 of the raw body with `META_APP_SECRET`), else 401. Each `story_insights` change is stored in `organic` with `mediaProductType` = `STORY`, merged by `id`; other fields are acknowledged and ignored.
- The story's own fields (timestamp, media type, permalink, …) are read from the Graph API by its `media_id`. If the API no longer returns the story, the row gets `mediaType` = "" and the notification's time as `timestamp`.
- The notification's numbers are stored under their metric names as in the table above. Older payloads that send `taps_forward`, `taps_back`, `exits`, `swipe_forward` instead of `navigation` are summed into `navigation`.
- Storing fails → 500, so Meta retries (for up to 36 hours); merging by `id` makes retries harmless.
- Setup: subscribe the app to the Instagram `story_insights` field in the App Dashboard with the callback URL `<service URL>/meta/webhook`, and subscribe the linked Facebook Page (`POST /{page-id}/subscribed_apps` with a Page access token). The app must be Live.

## Settings

| Variable | Used by | |
|---|---|---|
| `META_ACCESS_TOKEN` | sync, webhook | long-lived token with `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement` |
| `INSTAGRAM_USER_ID` or `FACEBOOK_PAGE_ID` | sync, webhook | the Instagram account, or the Page it is linked to |
| `META_GRAPH_VERSION` | sync, webhook | Graph API version, `v23.0` by default |
| `META_APP_SECRET` | webhook | required; checks Meta's signatures |
| `META_WEBHOOK_VERIFY_TOKEN` | webhook | required; the Verify Token set in the App Dashboard |
| `INSIGHTS_DATASET` | all | BigQuery dataset, `instagram_insights` by default |

## Open Questions

- Initial load from CSV: done from the Business Suite exports in `specs/meta/posts` and `specs/meta/stories` (`uv run insights-sync --csv FILE... [--types ...]`, `routines/insights_sync/csv_import.py`). Rows are classified by "Post type" (the 2023-24 files are swapped between the folders), "Publish time" is US Pacific, "Sticker taps" has no column, and `totalInteractions` and the reel watch-time columns are empty for imported rows until a sync reads them again.
- Instagram CDN `media_url` / `thumbnail_url` are signed and expire, so stored URLs stop working after a while. Columns widened to 2000 characters so they fit.
- The `story_insights` payload keys are taken from Meta's examples; confirm them with the App Dashboard's Test button.
- `ads` table: no schema yet.

## ContentInsightsService

Purpose of `ContentInsightsService` is to query BigQuery tables using params provided.