# hd-marketing-mcp

An MCP server for HealthyDoggo's SMM managers. Spec:
`../specs/marketing-mcp.md`. So far it has one tool, `search_knowledge_base`,
which finds products, Instagram conversations and content items through the
search API (`../src/api`).

```bash
uv sync
uv run pytest
uv run python src/mcp-server.py                       # HTTP on :8080/mcp
MCP_TRANSPORT=stdio uv run python src/mcp-server.py   # for a local MCP client
```

## search_knowledge_base

| Parameter | |
|---|---|
| `query` | required; a standalone search query |
| `productSku` | optional; narrows products to that SKU, and always searches them |
| `hasDog` | optional; content with (`true`) or without (`false`) a dog |
| `contentType` | optional; `лайфстайл`, `креатив` or `продуктове`. Left out, the API searches `лайфстайл` |

It returns the API's result as is: `products`, `instagramMessages`,
`content`. An API error comes back as a tool error carrying the API's message.

## Calling the API

The API sits behind Cloud Run IAM and normally wants a signed-in user's
token too. This server has no user: it calls as its own service account, with
an ID token from the metadata server, and the API admits it because the
account is listed in the API's `SERVICE_CALLERS`.

| Variable | |
|---|---|
| `API_URL` | the search API's URL |
| `API_AUDIENCE` | the API's URL again, the audience of the service token. Leave unset only for an API with no Cloud Run in front |
| `MCP_TRANSPORT` | `http` (default) or `stdio` |
| `PORT` | set by Cloud Run; 8080 otherwise |

## Deploying to Cloud Run

Nothing below has been run.

```bash
PROJECT=project-b2b68530-7524-4ecc-8e6
REGION=europe-central2
MCP_SA=hd-mcp@$PROJECT.iam.gserviceaccount.com
API_URL=https://hd-api-801813292191.europe-central2.run.app

gcloud iam service-accounts create hd-mcp

gcloud run deploy hd-mcp --source . --region=$REGION \
  --service-account=$MCP_SA --no-allow-unauthenticated \
  --set-env-vars=API_URL=$API_URL,API_AUDIENCE=$API_URL

# The same role the portal holds on the API...
gcloud run services add-iam-policy-binding hd-api --region=$REGION \
  --member=serviceAccount:$MCP_SA --role=roles/run.invoker
# ...and the API's leave to call without a user. --update-env-vars keeps the
# API's other settings. Both URLs Cloud Run gives the API are accepted.
gcloud run services update hd-api --region=$REGION \
  --update-env-vars="^;^SERVICE_CALLERS=$MCP_SA;SERVICE_TOKEN_AUDIENCE=$API_URL,<the API's other run.app URL>"
```

`--no-allow-unauthenticated` keeps the MCP endpoint itself private: it can
read every Instagram conversation in the knowledge base, so it must not be
open to the internet. Whoever connects to it needs `roles/run.invoker` on
`hd-mcp`.
