# Running locally

Each service on its own port, so they can run side by side:

| Service | Port | Directory |
|---|---|---|
| Search API | 8080 | repo root |
| Portal | 3000 | `portal/` |
| MCP server (HTTP) | 8090 | `marketing-mcp/` |
| Story webhook | 8081 | repo root |

## Once

```bash
# Python (repo root) and the MCP's own project
uv sync --extra dev
(cd marketing-mcp && uv sync)
(cd portal && npm install)

# Google APIs (Firestore, BigQuery) as yourself
gcloud auth application-default login
gcloud config set project project-b2b68530-7524-4ecc-8e6

# Settings: fill in the values (never commit them)
cp .env.example .env                       # API, webhook, sync job, rag-index
cp portal/.env.example portal/.env.local   # portal
```

`.env` is read by the Python services at the repo root
(`infrastructure/env.py`); real environment variables win over it. The MCP
reads no file: export its variables in the shell.

## Search API

Needs `GEMINI_API_KEY`, `TYPESAFE_API_KEY`, `GOOGLE_CLOUD_PROJECT`,
`USER_TOKEN_AUDIENCE` (the OAuth client id) and `ALLOWED_USERS` in `.env`.

```bash
uv run uvicorn api.app:create_app --factory --port 8080 --reload
```

Every call needs a Google ID token for an allowed user in `X-User-Token`; the
portal sends it. Locally there is no Cloud Run in front, so no other token is
needed.

## Portal

In `portal/.env.local`: `NEXTAUTH_URL=http://localhost:3000`,
`API_URL=http://localhost:8080`, `API_AUDIENCE` left empty, plus the OAuth
client, `NEXTAUTH_SECRET` (`openssl rand -base64 32`) and `ALLOWED_USERS`.

```bash
cd portal
npm run dev          # http://localhost:3000
```

## MCP server

Over stdio, for a local MCP client; no sign-in:

```bash
cd marketing-mcp
API_URL=https://hd-api-801813292191.europe-central2.run.app \
API_AUDIENCE=https://hd-api-801813292191.europe-central2.run.app \
MCP_TRANSPORT=stdio uv run python src/mcp-server.py
```

Over HTTP, as on Cloud Run (sign-in required; add
`http://localhost:8090/auth/callback` to the OAuth client's redirect URIs):

```bash
cd marketing-mcp
export GOOGLE_CLIENT_ID=<OAuth client id> GOOGLE_CLIENT_SECRET=<its secret> \
  MCP_BASE_URL=http://localhost:8090 MCP_JWT_SIGNING_KEY=$(openssl rand -base64 32) \
  ALLOWED_USERS=<a@example.com> API_URL=<API URL> PORT=8090
uv run python src/mcp-server.py      # http://localhost:8090/mcp
```

The tools call the API as the server's service account, without a user
token, and the API admits only `hd-mcp` that way. On a laptop there is no
metadata server, so the token comes from Application Default Credentials
instead; they have to impersonate `hd-mcp` (needs
`roles/iam.serviceAccountTokenCreator` on it):

```bash
gcloud auth application-default login \
  --impersonate-service-account=hd-mcp@project-b2b68530-7524-4ecc-8e6.iam.gserviceaccount.com
```

Not tried yet. Without it, listing the tools works but calling them fails
with "could not get a service token". Log in again without the flag
afterwards, or the API, webhook and sync run as `hd-mcp` too.

## Story webhook

Needs `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`, `META_ACCESS_TOKEN` and
`FACEBOOK_PAGE_ID` in `.env`. It writes to the real BigQuery table.

```bash
uv run uvicorn webhook.app:create_app --factory --port 8081 --reload

# Meta's verification handshake
curl "http://localhost:8081/meta/webhook?hub.mode=subscribe&hub.verify_token=<your token>&hub.challenge=123"
```

Meta reaches only public URLs; for real notifications use the deployed
`hd-webhook`, or a tunnel to port 8081.

## Insights sync

Needs `META_ACCESS_TOKEN` and `FACEBOOK_PAGE_ID` in `.env`. It writes to the
real BigQuery table.

```bash
uv run insights-sync                  # feed, reels and ads of the last 30 days
uv run insights-sync --days 90
uv run insights-sync --csv specs/meta/posts/*.csv --types FEED,REELS   # load Business Suite exports
```

## Knowledge base indexing

Needs `GEMINI_API_KEY` and `GOOGLE_CLOUD_PROJECT` in `.env`.

```bash
uv run rag-index --collection products --limit 20   # try on a few rows
uv run rag-index                                    # everything
```

## Tests and checks

```bash
uv run pytest && uv run ruff check .              # repo root
(cd marketing-mcp && uv run pytest)
(cd portal && npm test && npm run typecheck && npm run lint)
```
