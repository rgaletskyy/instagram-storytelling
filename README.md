# hd-marketing

Tools for HealthyDoggo's SMM managers:

- **Product search (RAG) and the search API** — below.
- **Marketing portal** — `portal/`, see `portal/README.md`.
- **Marketing MCP** — `marketing-mcp/`, see `marketing-mcp/README.md`: search,
  content insights, image and slide generation for Claude.

Deploy steps for every service are in `scripts/deploy.md`, local runs in
`scripts/run.md`.

## Product search (RAG)

The catalogue, the Instagram DMs and the image index
are embedded into the Firestore database `healthydoggo`, and `SearchService`
finds what is close to a query. Specs: `specs/marketing-content-rag.md`,
`specs/content-search-service.md`. Code:
`infrastructure/` (Firestore, Jev, Gemini clients), `search-api/src/domain/`
(`SearchService`, contracts), `routines/vector_indexer/indexer.py`.

Needs `GEMINI_API_KEY`, `TYPESAFE_API_KEY`, `GOOGLE_CLOUD_PROJECT`, and
Application Default Credentials for Firestore
(`gcloud auth application-default login`).

**Vectors are 1536-dimensional**, not the model's native 3072: Firestore will
not index a vector over 2048 dimensions. Each collection needs a vector index
before it can be searched -- once per collection:

```bash
for c in products instagram_messages content; do
  gcloud firestore indexes composite create --database=healthydoggo \
    --collection-group=$c --query-scope=COLLECTION \
    --field-config field-path=embeddingVector,vector-config='{"dimension":"1536","flat":"{}"}'
done
```

Then index the spreadsheets in `src/resources/indices/`:

```bash
uv run rag-index --collection products --limit 20   # try it on a few rows
uv run rag-index                                    # everything
uv run rag-index --force                            # re-embed what is stored
```

Rows are embedded and written 200 at a time, with a 10-second pause between
chunks. Runs are resumable -- a row whose id is already stored is skipped -- and ids
are stable (SKU, Drive file id, a hash of conversation, sender and day).

**Messages are stored a day at a time.** One sender's messages in one
conversation on one day (Kyiv time) are joined, in the order sent, into a
single document stamped with the first message's time. Grouping by
conversation keeps the shop's replies to different customers apart. A day
already stored is not updated when more of its messages turn up in a later
export; `--force` rebuilds it.

Two kinds of row are never embedded: Instagram's own notices and placeholders (`Liked a message`,
`[Фото]` and the like), and image-index rows nobody has described yet.

```python
from domain.content_search_service import SearchService

result = await SearchService().find_similar("шампунь для шпіца")
result.products, result.instagram_messages, result.content  # top 5 / 10 / 20, closest first
```

Jev is asked a single choice question: the query is the state, and each
collection is an option described in `COLLECTION_DESCRIPTIONS`. A collection is
searched only when its probability is at least 0.3. The probabilities sum to 1,
so a query that clearly belongs to one collection searches only that one, while
one Jev is torn over can search two or all three.

## Search API

`search-api/src/api` puts `SearchService` behind one HTTP endpoint for the marketing portal
(a Next.js app). Spec: `specs/search-api.md`.

```
POST /searchcontent
Authorization: Bearer <ID token for the portal's service account>   -- checked by Cloud Run
X-User-Token:  <the signed-in user's Google ID token>              -- checked by the API
{"query": "шампунь для шпіца", "hasDog": true, "type": "лайфстайл", "productSku": "ND-PAWS-01"}
```

`hasDog` and `type` narrow the content results only. `type` is one of
`лайфстайл`, `креатив`, `продуктове` and defaults to `лайфстайл`; `hasDog`
asks for files with a dog (`true`), without one (`false`), or either when left
out. `productSku`, also optional, narrows the products to that exact SKU.
All three are Firestore pre-filters, and each combination of filter fields
needs its own vector index -- two on content, one on products:

```bash
for fields in type type,hasDog; do
  configs=()
  for f in ${fields//,/ }; do configs+=(--field-config=order=ASCENDING,field-path=$f); done
  gcloud firestore indexes composite create --database=healthydoggo \
    --collection-group=content --query-scope=COLLECTION "${configs[@]}" \
    --field-config='field-path=embeddingVector,vector-config={"dimension":"1536","flat":"{}"}'
done
gcloud firestore indexes composite create --database=healthydoggo \
  --collection-group=products --query-scope=COLLECTION \
  --field-config=order=ASCENDING,field-path=sku \
  --field-config='field-path=embeddingVector,vector-config={"dimension":"1536","flat":"{}"}'
```

The response is `SearchResult` with its contract field names: `products`,
`instagramMessages`, `content`. Status codes:

| Code | When |
|---|---|
| 400 | empty query |
| 401 | no user token, or one that fails Google's signature, expiry, audience or has no verified email |
| 403 | a verified user who is not on the allowlist |
| 422 | the body has no `query` |
| 502 | Gemini or Jev failed |
| 503 | Firestore failed, or Google's signing certificates could not be fetched |

**Who is calling is checked twice.** Cloud Run admits only two service
accounts, the portal's and the MCP server's (`--no-allow-unauthenticated`,
`roles/run.invoker` for those two alone), and both get their tokens from the
metadata server, so no secret exists to leak. The MCP server, which has no
user behind it, is admitted on its own verified token through
`SERVICE_CALLERS`; see `marketing-mcp/README.md`. The API then verifies the user's own Google ID token --
Google's signature, the portal's OAuth client id as audience -- and checks the
email against `ALLOWED_USERS`. A forwarded email in a plain header would prove
nothing. Every call and every refusal is logged as JSON with the user's email.

Settings (the app will not start without the first two):

| Variable | |
|---|---|
| `USER_TOKEN_AUDIENCE` | the portal's Google OAuth client id; comma-separated for more than one |
| `ALLOWED_USERS` | emails allowed to call, comma-separated |
| `GEMINI_API_KEY`, `TYPESAFE_API_KEY` | as for the indexer; from Secret Manager on Cloud Run |
| `SERVICE_CALLERS` | optional: service accounts that may call **without** a user token, comma-separated -- the MCP server (`marketing-mcp/`). Their ID token is verified and they are logged as the caller |
| `SERVICE_TOKEN_AUDIENCE` | the API's own URL(s), the audience those service tokens carry. Set with `SERVICE_CALLERS` or not at all |

Run it locally:

```bash
uv run uvicorn api.app:create_app --factory --port 8080
```

### Deploying to Cloud Run

**Private by IAM, not by network.** The service has a public URL, but Google's
front end rejects any request without an ID token for the portal's or the
MCP server's service account before it reaches the container. There is no VPC: the API calls
Firestore, Gemini and Jev over the public internet, with TLS and its own
service account.

Nothing below has been run; replace the placeholders. Region is where the
other services run.

```bash
PROJECT=project-b2b68530-7524-4ecc-8e6
REGION=europe-central2
API_SA=hd-api@$PROJECT.iam.gserviceaccount.com
PORTAL_SA=<the portal's service account>

# 1. The API's own identity: Firestore read/write, and its two secrets.
gcloud iam service-accounts create hd-api
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:$API_SA --role=roles/datastore.user
printf %s "$GEMINI_API_KEY"   | gcloud secrets create gemini-api-key   --data-file=-
printf %s "$TYPESAFE_API_KEY" | gcloud secrets create typesafe-api-key --data-file=-
for s in gemini-api-key typesafe-api-key; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$API_SA --role=roles/secretmanager.secretAccessor
done

# 2. Deploy with no anonymous calls. The ^;^ prefix makes ; the separator,
#    since the values contain commas.
gcloud run deploy hd-api --source . --region=$REGION \
  --service-account=$API_SA \
  --ingress=all --no-allow-unauthenticated \
  --set-env-vars="^;^USER_TOKEN_AUDIENCE=<portal OAuth client id>;ALLOWED_USERS=<a@x.ua,b@x.ua>" \
  --set-secrets=GEMINI_API_KEY=gemini-api-key:latest,TYPESAFE_API_KEY=typesafe-api-key:latest

# 3. Only the portal may invoke it -- and the MCP server, granted in
#    marketing-mcp/README.md along with SERVICE_CALLERS. The portal's account
#    must exist first (portal/README.md creates it).
gcloud run services add-iam-policy-binding hd-api --region=$REGION \
  --member=serviceAccount:$PORTAL_SA --role=roles/run.invoker
```

**What the portal sends on every call:**

- `Authorization: Bearer <service token>` -- an ID token for its service
  account, with the API's URL as audience, fetched from the metadata server
  (`google-auth-library`'s `getIdTokenClient(apiUrl)` in Node). No key is
  stored anywhere. Cloud Run checks it; the API never sees a request without it.
- `X-User-Token: <user token>` -- the Google ID token the user received on
  signing in to the portal. The API checks it. It expires after an hour, so the
  portal has to refresh it rather than forward the one from sign-in forever.

## Marketing portal

`portal/` is the Next.js app the marketing team uses: Gmail sign-in limited to
an allowlist, and a chat that sends each query to the search API and shows the
result as JSON. It is the only caller the API admits. Setup, the Google OAuth
client and Cloud Run deployment are in `portal/README.md`.
