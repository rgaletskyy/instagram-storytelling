# ContentInsightsService

## Responsibility
Returns insights on Instagram posts, reels and stories stored in BigQuery table `organic` (see [instagram-insights-rag.md](instagram-insights-rag.md)).

## Logic
Insights are fetched from Meta's Graph API by the weekly sync job and the story webhook, and stored in BigQuery. This service only reads them: it filters by publication date, mediaType and mediaProductType, and sorts by a metric.

## Methods

### queryContentInsights

Purpose:
- Return insights for a content filtered and sorted based on input params.

Inputs:
- from: datetime, required
  - datetime from which to query data, inclusive
  - without a timezone, taken as UTC
- to: datetime, optional
  - datetime up to which to perform the search, inclusive; now when absent
  - must not be before `from`
- mediaType: string, optional, IMAGE, VIDEO or CAROUSEL_ALBUM
  - content media type
- mediaProductType: string, optional, FEED, STORY, REELS or AD
  - type of posted content
- sortBy: string, optional
  - sorting parameter. One of views|totalInteractions|shares|reposts|likes|saved. Specify column names seperate by comma to sort results. Maximum three sort orders are allowed.
- topN: integer, optional, at least 1
  - number of items to return, the first N after sorting; all matching items when absent

Output:
- ContentInsights, collection of content items with insights

Errors:
- InvalidArgument — `to` is before `from`, mediaType, mediaProductType or a sortBy column is not one of its allowed values, sortBy has more than three columns or one twice, or topN is below 1

Behavior:
- Use `BigQueryClient` infrastructure class to access BigQuery
- Apply all nonempty filtering parameters when building query; empty ones are ignored
- `from` bounds the table's required partition filter on `timestamp`
- Sort descending by the columns in sortBy, in the given order: each column only breaks ties in the ones before it, and the newest break any ties left. Without sortBy, newest first. Rows without a value in a sort column come after those with one
- Spaces around the commas in sortBy are ignored
- With topN, return only the first topN rows of that order (BigQuery `LIMIT`)
- Response contains array of items, errorCode and errorMessage fields
- A BigQuery failure is returned in errorCode / errorMessage with empty items, not raised
- Must not modify stored rows

Side Effects:
- None

### storiesInsightsCallback

Purpose:
- Handles callback initiated by meta to store story insights on expiration. Data should be stored in `organic` table with mediaProductType = `STORY`
- Webhook setup for receiving callback described in @specs/meta/webhooks.md

Implemented by the story webhook service (`search-api/src/webhook`), not by this service: it must be public, while the service is reached through the private search API. Behavior is specified in [instagram-insights-rag.md](instagram-insights-rag.md), "Story webhook".

## API

`POST /searchContentInsights` on the search API, with the same caller checks as `/searchcontent`.

- Body: `from`, `to`, `mediaType`, `mediaProductType`, `sortBy`, `topN` as above
- 200: ContentInsights, including when BigQuery failed (errorCode set)
- 400: InvalidArgument; 422: `from` missing or not a datetime, or `topN` not an integer

## Data Contracts

### ContentInsights

- items: list<ContentInsight>, required, array of content insights. Can be empty; the API leaves an empty one out
- errorCode: string, optional, error reason returned from BigQuery (e.g. `accessDenied`)
- errorMessage: string, optional, error message returned from BigQuery

### ContentInsight

- fields as the columns of `organic` in [instagram-insights-rag.md](instagram-insights-rag.md), with the same names
- metrics without a value are null, never 0; the API leaves them out of its response

## Open Questions

- Without topN there is no limit on the number of items: a wide `from`/`to` range returns every row in it.
