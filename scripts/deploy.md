# Deploying to Google Cloud

Every service runs on Cloud Run in `europe-central2`, each as its own service
account. The commands below match what is deployed. The first-time setup of
each service runs once; after that, **redeploying code needs only that
service's `gcloud run deploy ... --source .`**, which keeps its settings,
secrets and IAM.

Secret values never go on the command line or into this repo. Commands that
create a secret read it from the prompt (`read -rs`): run them in a terminal,
paste the value, press Enter.

| Service | Kind | Access | Account | Source |
|---|---|---|---|---|
| `hd-api` | service | private (IAM) | `hd-api` | repo root |
| `hd-portal` | service | public, Google sign-in | `hd-portal` | `portal/` |
| `hd-mcp` | service | public, Google sign-in | `hd-mcp` | `marketing-mcp/` |
| `hd-webhook` | service | public, Meta signature | `hd-webhook` | repo root |
| `insights-sync` | job, weekly | scheduler only | `hd-insights-sync` | repo root |

## 0. Variables

Set these in every shell that runs the commands below.

```bash
PROJECT=project-b2b68530-7524-4ecc-8e6
REGION=europe-central2
gcloud config set project $PROJECT
gcloud config set run/region $REGION

API_URL=https://hd-api-801813292191.europe-central2.run.app
PORTAL_URL=https://hd-portal-801813292191.europe-central2.run.app
MCP_URL=https://hd-mcp-801813292191.europe-central2.run.app
WEBHOOK_URL=https://hd-webhook-801813292191.europe-central2.run.app

# The Google OAuth web client users sign in with (portal and MCP).
GOOGLE_CLIENT_ID=801813292191-a1p5sbr8t96cf6q692sj0rskbe11h7u1.apps.googleusercontent.com
# Emails allowed in, comma-separated; the same list on the API, portal and MCP.
ALLOWED_USERS="<a@example.com,b@example.com>"
# The Facebook Page linked to the Instagram account.
FACEBOOK_PAGE_ID=104256582042248

API_SA=hd-api@$PROJECT.iam.gserviceaccount.com
PORTAL_SA=hd-portal@$PROJECT.iam.gserviceaccount.com
MCP_SA=hd-mcp@$PROJECT.iam.gserviceaccount.com
WEBHOOK_SA=hd-webhook@$PROJECT.iam.gserviceaccount.com
SYNC_SA=hd-insights-sync@$PROJECT.iam.gserviceaccount.com
```

A service's URL is known only after its first deploy. On a fresh project,
deploy, read the URL from the output, set the variable, and continue.

## 1. Project (once)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  firestore.googleapis.com bigquery.googleapis.com cloudscheduler.googleapis.com

for sa in hd-api hd-portal hd-mcp hd-webhook hd-insights-sync; do
  gcloud iam service-accounts create $sa
done
```

**Google OAuth client** (console, once). Google Auth Platform:
- Audience: External, and **publish the app**. In Testing, refresh tokens
  expire after 7 days.
- Clients → Create client → Web application. Authorized redirect URIs:
  - `http://localhost:3000/api/auth/callback/google`
  - `$PORTAL_URL/api/auth/callback/google`
  - `$MCP_URL/auth/callback`

Its id is `GOOGLE_CLIENT_ID` above. Store its secret:

```bash
read -rs S && printf %s "$S" | gcloud secrets create portal-google-client-secret --data-file=- && unset S
```

## 2. Knowledge base: Firestore and the vector index (once)

```bash
gcloud firestore databases create --database=healthydoggo --location=$REGION

# One vector index per collection; vectors are 1536-d.
for c in products instagram_messages content; do
  gcloud firestore indexes composite create --database=healthydoggo \
    --collection-group=$c --query-scope=COLLECTION \
    --field-config field-path=embeddingVector,vector-config='{"dimension":"1536","flat":"{}"}'
done

# Embed the spreadsheets in src/resources/indices/ (needs .env, see run.md).
uv run rag-index
```

Filtered searches (content by `type`/`hasDog`, products by `productSku`) need
their own composite vector indexes; the first such query's error links to the
one to create.

## 3. Search API: `hd-api`

First time:

```bash
gcloud projects add-iam-policy-binding $PROJECT --condition=None \
  --member=serviceAccount:$API_SA --role=roles/datastore.user

read -rs S && printf %s "$S" | gcloud secrets create gemini-api-key --data-file=- && unset S
read -rs S && printf %s "$S" | gcloud secrets create typesafe-api-key --data-file=- && unset S
for s in gemini-api-key typesafe-api-key; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$API_SA --role=roles/secretmanager.secretAccessor
done
```

BigQuery access is granted in section 6, once the dataset exists.

Deploy, from the repo root. It is private: only accounts with `run.invoker`
get through, which are the portal and the MCP (sections 4 and 5).

```bash
gcloud run deploy hd-api --source . \
  --service-account=$API_SA --ingress=all --no-allow-unauthenticated --max-instances=3 \
  --set-env-vars="^;^USER_TOKEN_AUDIENCE=$GOOGLE_CLIENT_ID;ALLOWED_USERS=$ALLOWED_USERS;SERVICE_CALLERS=$MCP_SA;SERVICE_TOKEN_AUDIENCE=https://hd-api-5c64nevodq-lm.a.run.app,$API_URL" \
  --set-secrets=GEMINI_API_KEY=gemini-api-key:latest,TYPESAFE_API_KEY=typesafe-api-key:latest
```

`^;^` makes `;` the separator, since the values contain commas.
`SERVICE_TOKEN_AUDIENCE` lists both URLs Cloud Run gives the service.

Redeploy: `gcloud run deploy hd-api --source .`

## 4. Portal: `hd-portal`

First time:

```bash
openssl rand -base64 32 | tr -d '\n' | gcloud secrets create portal-nextauth-secret --data-file=-
for s in portal-nextauth-secret portal-google-client-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$PORTAL_SA --role=roles/secretmanager.secretAccessor
done

# Let the portal call the API.
gcloud run services add-iam-policy-binding hd-api \
  --member=serviceAccount:$PORTAL_SA --role=roles/run.invoker
```

Deploy, from `portal/`:

```bash
cd portal
gcloud run deploy hd-portal --source . \
  --service-account=$PORTAL_SA --allow-unauthenticated --max-instances=3 \
  --set-env-vars="^;^GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID;ALLOWED_USERS=$ALLOWED_USERS;API_URL=$API_URL;API_AUDIENCE=$API_URL;NEXTAUTH_URL=$PORTAL_URL" \
  --set-secrets=NEXTAUTH_SECRET=portal-nextauth-secret:latest,GOOGLE_CLIENT_SECRET=portal-google-client-secret:latest
```

Redeploy: `cd portal && gcloud run deploy hd-portal --source .`

## 5. MCP server: `hd-mcp`

First time. Its sign-in state lives in a Firestore database of its own, and
that is the only database it may touch.

```bash
gcloud firestore databases create --database=mcp-auth --location=$REGION
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:$MCP_SA --role=roles/datastore.user \
  --condition="expression=resource.name.startsWith(\"projects/$PROJECT/databases/mcp-auth\"),title=mcp-auth-only,description=Only the MCP sign-in database"

openssl rand -base64 32 | tr -d '\n' | gcloud secrets create mcp-jwt-signing-key --data-file=-
for s in mcp-jwt-signing-key portal-google-client-secret gemini-api-key ANTHROPIC_API_KEY; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$MCP_SA --role=roles/secretmanager.secretAccessor
done

# Let the MCP call the API, without a user token (SERVICE_CALLERS in section 3).
gcloud run services add-iam-policy-binding hd-api \
  --member=serviceAccount:$MCP_SA --role=roles/run.invoker
```

Deploy, from `marketing-mcp/`. It is public: Claude Desktop connects from
Anthropic's side, so Google sign-in (`src/auth.py`) is the gate.

```bash
cd marketing-mcp
gcloud run deploy hd-mcp --source . \
  --service-account=$MCP_SA --allow-unauthenticated --max-instances=3 --memory=2Gi \
  --set-env-vars="^;^GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID;ALLOWED_USERS=$ALLOWED_USERS;MCP_BASE_URL=$MCP_URL;AUTH_FIRESTORE_DATABASE=mcp-auth;API_URL=$API_URL;API_AUDIENCE=$API_URL" \
  --set-secrets=GOOGLE_CLIENT_SECRET=portal-google-client-secret:latest,MCP_JWT_SIGNING_KEY=mcp-jwt-signing-key:latest,GEMINI_API_KEY=gemini-api-key:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest
```

`generate_image` needs `GEMINI_API_KEY`. On a service deployed before it,
add the key once (the accessor grant above, then
`gcloud run services update hd-mcp --region=$REGION --update-secrets=GEMINI_API_KEY=gemini-api-key:latest`).
`generate_slide` needs `ANTHROPIC_API_KEY` (the existing secret of that name)
and room for Chromium: on a service deployed before it, the accessor grant
above, then
`gcloud run services update hd-mcp --region=$REGION --memory=2Gi --update-secrets=ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest`.

Claude Desktop adds it as a custom connector at `$MCP_URL/mcp`.

Redeploy: `cd marketing-mcp && gcloud run deploy hd-mcp --source .`

## 6. Content insights: BigQuery

First time: the dataset and the `organic` table.

```bash
bq --location=$REGION mk --dataset $PROJECT:instagram_insights

bq --location=$REGION query --nouse_legacy_sql '
CREATE TABLE instagram_insights.organic (
  id STRING NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  mediaType STRING(50) NOT NULL,
  mediaProductType STRING(50) NOT NULL,
  caption STRING(2500),
  mediaUrl STRING(2000),
  thumbnailUrl STRING(2000),
  permaLink STRING,
  views INT64, reach INT64, likes INT64, comments INT64, saved INT64,
  shares INT64, reposts INT64, totalInteractions INT64, profileVisits INT64,
  follows INT64, replies INT64, link_clicks INT64, navigation INT64,
  reelAvgWatchTime INT64, reelViewTotalTime INT64, reelSkipRate FLOAT64
)
PARTITION BY TIMESTAMP_TRUNC(timestamp, MONTH)
CLUSTER BY mediaProductType, mediaType, totalInteractions
OPTIONS (require_partition_filter = TRUE)'
```

Access: the API reads; the sync job and the webhook write; all three run
queries. Dataset roles are granted with SQL, because
`bq add-iam-policy-binding` on a dataset needs an allowlist.

```bash
bq --location=$REGION query --nouse_legacy_sql "
GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`$PROJECT.instagram_insights\` TO 'serviceAccount:$API_SA';
GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`$PROJECT.instagram_insights\` TO 'serviceAccount:$SYNC_SA', 'serviceAccount:$WEBHOOK_SA'"

for sa in $API_SA $SYNC_SA $WEBHOOK_SA; do
  gcloud projects add-iam-policy-binding $PROJECT --condition=None \
    --member=serviceAccount:$sa --role=roles/bigquery.jobUser
done
```

**Meta access token** (once; how to get one: a system user token from Meta
Business Suite, with `instagram_basic`, `instagram_manage_insights`,
`pages_read_engagement`, `pages_show_list`, `business_management`):

```bash
read -rs S && printf %s "$S" | gcloud secrets create meta-access-token --data-file=- && unset S
# To replace it later: ... | gcloud secrets versions add meta-access-token --data-file=-
for sa in $SYNC_SA $WEBHOOK_SA; do
  gcloud secrets add-iam-policy-binding meta-access-token \
    --member=serviceAccount:$sa --role=roles/secretmanager.secretAccessor
done
```

**Initial load** from the Business Suite CSV exports (gitignored; put them in
`specs/meta/posts/` and `specs/meta/stories/`), posts first, then stories:

```bash
uv run insights-sync --csv specs/meta/posts/*.csv specs/meta/stories/*.csv --types FEED,REELS
uv run insights-sync --csv specs/meta/posts/*.csv specs/meta/stories/*.csv --types STORY
```

## 7. Weekly sync: job `insights-sync`

Deploy, from the repo root. It reads feed posts, reels and ads of the last
30 days from the Graph API and merges them into `organic`.

```bash
gcloud run jobs deploy insights-sync --source . \
  --service-account=$SYNC_SA --command=insights-sync --max-retries=1 --task-timeout=30m \
  --set-env-vars=FACEBOOK_PAGE_ID=$FACEBOOK_PAGE_ID \
  --set-secrets=META_ACCESS_TOKEN=meta-access-token:latest
```

First time: the schedule, every Sunday at 00:00 Kyiv time.

```bash
gcloud run jobs add-iam-policy-binding insights-sync \
  --member=serviceAccount:$SYNC_SA --role=roles/run.invoker

gcloud scheduler jobs create http insights-sync-weekly --location=$REGION \
  --schedule="0 0 * * 0" --time-zone=Europe/Kyiv --http-method=POST \
  --uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/insights-sync:run" \
  --oauth-service-account-email=$SYNC_SA \
  --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform
```

Run it now: `gcloud run jobs execute insights-sync`.
Redeploy: `gcloud run jobs deploy insights-sync --source .`

## 8. Story webhook: `hd-webhook`

First time. The Meta app secret is in the App Dashboard under App settings →
Basic; the verify token is generated here and entered in the Dashboard.

```bash
read -rs S && printf %s "$S" | gcloud secrets create meta-app-secret --data-file=- && unset S
openssl rand -hex 24 | tr -d '\n' | gcloud secrets create meta-webhook-verify-token --data-file=-
for s in meta-app-secret meta-webhook-verify-token; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$WEBHOOK_SA --role=roles/secretmanager.secretAccessor
done
```

Deploy, from the repo root. It uses the API's image, starting the webhook app
instead. It is public: Meta cannot carry a Google token, and only requests
signed with the app secret are accepted.

```bash
gcloud run deploy hd-webhook --source . \
  --service-account=$WEBHOOK_SA --allow-unauthenticated --max-instances=2 \
  --command=uvicorn --args=webhook.app:create_app,--factory,--host,0.0.0.0,--port,8080 \
  --set-env-vars=FACEBOOK_PAGE_ID=$FACEBOOK_PAGE_ID \
  --set-secrets=META_APP_SECRET=meta-app-secret:latest,META_WEBHOOK_VERIFY_TOKEN=meta-webhook-verify-token:latest,META_ACCESS_TOKEN=meta-access-token:latest
```

Then in the Meta App Dashboard → Webhooks → Instagram: callback URL
`$WEBHOOK_URL/meta/webhook`, verify token from
`gcloud secrets versions access latest --secret=meta-webhook-verify-token`,
and subscribe to `story_insights`. Meta delivers real notifications only once
the app is published (Live).

Redeploy: `gcloud run deploy hd-webhook --source .`

## Checks after a deploy

```bash
gcloud run services logs read hd-api --limit=20      # or hd-portal, hd-mcp, hd-webhook
gcloud run jobs executions list --job=insights-sync

curl -s -o /dev/null -w '%{http_code}\n' -X POST $API_URL/searchcontent       # 403: IAM refuses anonymous calls
curl -s -o /dev/null -w '%{http_code}\n' $MCP_URL/.well-known/oauth-authorization-server  # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST $MCP_URL/mcp                 # 401: sign-in required
curl -s -o /dev/null -w '%{http_code}\n' -X POST $WEBHOOK_URL/meta/webhook    # 401: unsigned
```

The search routes are `/searchcontent` and `/searchContentInsights`; the
portal and the MCP call them by name, so a rename means redeploying the API,
the portal and the MCP together.
