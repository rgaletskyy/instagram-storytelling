# hd-marketing-mcp

An MCP server for HealthyDoggo's SMM managers. Spec:
`../specs/marketing-mcp.md`. So far it has three tools. Two call the search
API (`../search-api`): `search_knowledge_base` finds products, Instagram
conversations and content items, and `search_content_insights` ranks the
account's Instagram posts, reels and stories by their insights.
`generate_image` draws a new image with Gemini, and `generate_slide` lays
text out in the brand style over a photo.

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

## search_content_insights

Calls `POST /searchContentInsights`. The parameter descriptions tell the model
how to turn a request like "top 5 posts from May by likes and saves" into them.

| Parameter | |
|---|---|
| `from` | required; ISO 8601 datetime, start of the publication period |
| `to` | optional; end of the period, inclusive; now when left out |
| `mediaProductType` | optional; `FEED`, `STORY`, `REELS` or `AD` |
| `mediaType` | optional; `IMAGE`, `VIDEO` or `CAROUSEL_ALBUM` |
| `sortBy` | optional; up to three of `views`, `totalInteractions`, `likes`, `saved`, `shares`, `reposts`, comma-separated; newest first when left out |
| `topN` | optional; at least 1, the first N after sorting |

It returns the API's `items`. An API error, or a BigQuery failure the API
reports in `errorCode`, comes back as a tool error.

## generate_image

| Parameter | |
|---|---|
| `subject` | required; the scene, standalone |
| `products` | optional; SKUs or product names that must appear |
| `contentType` | optional; `Product photo`, `Lifestyle`, `Studio photoshoot` or `UGC` |
| `composition` | optional; `Centered`, `Rule of Thirds`, `Flat Lay`, `Close-up` or `Wide` |
| `cameraLevel` | optional; `Eye Level`, `High Angle`, `Top-Down`, `Low Angle` or `Ground Level` |
| `aspectRatio` | `9:16`, `1:1` or `4:5` (default) |
| `sampleUrls` | optional; https links to sample images (Drive links shared by link work) |

Each product is looked up through `/searchcontent` among the products: a SKU
exactly (`productSku`), otherwise the closest product to the name, and its
`imageUrl` (the catalogue's main photo) is taken. That photo, and the samples,
are downloaded without sign-in, so the files must be shared with anyone who
has the link. JPEG, PNG, WebP and HEIC/HEIF (iPhone photos) are accepted;
Drive serves HEIC as `application/octet-stream`, so a generic binary download
is accepted too and Pillow decides whether it is an image. References are shrunk to 1536 px JPEGs (at most 8) and sent to
Gemini with a rule to keep the products, dogs and people as photographed
(`src/tools/image_generation_service.py`). The tool returns the image as image
content, plus a text note when a product had no photo or a photo was skipped.
A sample that cannot be downloaded fails the call.

## generate_slide

| Parameter | |
|---|---|
| `subject` | required; what the slide is for and what should be on it, standalone |
| `backgroundImage` | required; https link to the photo (Drive links shared by link work) |
| `overlayText` | required; the copy, shown verbatim |
| `aspectRatio` | `9:16` (default, 1080x1920), `4:5` (1080x1350) or `1:1` (1080x1080) |

The background is downloaded like a `generate_image` sample (HEIC included,
shrunk to 2048 px). Claude (`SLIDE_LAYOUT_MODEL`) sees it and writes the slide
as one HTML document, following `src/resources/slide-design-guidelines.md`:
brand fonts, the safe area, a small text block kept off the dog and the
product, and optionally elements of the decorative library
(`src/resources/png/`, tinted to the brand colours on the fly). Headless
Chromium (Playwright) then screenshots it at the artboard's size
(`src/tools/slide_html_service.py`). The page is served from memory: it can
load only its background, the decorative elements and Google Fonts, and runs
no JavaScript. A page with an image that did not load is laid out once more;
a second failure, or a background that cannot be downloaded, is a tool error.
It returns the slide as a JPEG image. A call takes about a minute.

## Signing in

Claude Desktop reaches the server as a remote connector, from Anthropic's
side, so Cloud Run IAM cannot gate it: the service is public
(`--allow-unauthenticated`) and `src/auth.py` is the gate. Each user signs in
with Google once (FastMCP's OAuth proxy runs the flow), and only verified
emails in `ALLOWED_USERS` get through; a refusal is logged with its reason.
Over HTTP the server will not start unless all of the settings below marked
*required* are set. Over stdio there is no sign-in.

The proxy's state (Claude's client registration, sign-ins in flight, users'
Google tokens) is kept encrypted in the Firestore database `mcp-auth`, apart
from the knowledge base, so it survives restarts and is shared between
instances.

## Calling the API

The API sits behind Cloud Run IAM and normally wants a signed-in user's
token too. This server calls as its own service account instead, with an ID
token from the metadata server, and the API admits it because the account is
listed in the API's `SERVICE_CALLERS`.

## Settings

| Variable | |
|---|---|
| `GOOGLE_CLIENT_ID` | required; the Google OAuth web client (the portal's) |
| `GOOGLE_CLIENT_SECRET` | required; its secret, from Secret Manager |
| `MCP_BASE_URL` | required; this service's own URL. The OAuth client needs `<MCP_BASE_URL>/auth/callback` as a redirect URI |
| `MCP_JWT_SIGNING_KEY` | required; signs the tokens the proxy issues and keys the encryption of its state. Changing it signs everyone out |
| `ALLOWED_USERS` | required; emails allowed in, comma-separated |
| `AUTH_FIRESTORE_DATABASE` | Firestore database for the proxy's state; `mcp-auth` by default |
| `API_URL` | the search API's URL |
| `API_AUDIENCE` | the API's URL again, the audience of the service token. Leave unset only for an API with no Cloud Run in front |
| `GEMINI_API_KEY` | required by `generate_image`; from Secret Manager (`gemini-api-key`) |
| `GEMINI_IMAGE_MODEL` | the image model; `gemini-3-pro-image` by default |
| `ANTHROPIC_API_KEY` | required by `generate_slide`; from Secret Manager (`ANTHROPIC_API_KEY`) |
| `SLIDE_LAYOUT_MODEL` | the model that lays slides out; `claude-opus-5-5` by default |
| `MCP_TRANSPORT` | `http` (default) or `stdio` |
| `PORT` | set by Cloud Run; 8080 otherwise |

Nothing reads a `.env` file: export the variables in the shell for a local
HTTP run.

## Deploying to Cloud Run

What is deployed now, as commands. Redeploying code alone needs only the
last `gcloud run deploy hd-mcp --source .`: the settings are kept.

```bash
PROJECT=project-b2b68530-7524-4ecc-8e6
REGION=europe-central2
MCP_SA=hd-mcp@$PROJECT.iam.gserviceaccount.com
MCP_URL=https://hd-mcp-801813292191.europe-central2.run.app
API_URL=https://hd-api-801813292191.europe-central2.run.app

# 1. Identity, and the Firestore database it may use -- that one only.
gcloud iam service-accounts create hd-mcp
gcloud firestore databases create --database=mcp-auth --location=$REGION
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:$MCP_SA --role=roles/datastore.user \
  --condition="expression=resource.name.startsWith(\"projects/$PROJECT/databases/mcp-auth\"),title=mcp-auth only"

# 2. Secrets: the portal's OAuth client secret is shared; the signing key is
#    the server's own.
openssl rand -base64 32 | tr -d '\n' | gcloud secrets create mcp-jwt-signing-key --data-file=-
for s in mcp-jwt-signing-key portal-google-client-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$MCP_SA --role=roles/secretmanager.secretAccessor
done

# 3. Deploy, public: sign-in is the gate. ^;^ because ALLOWED_USERS has commas.
gcloud run deploy hd-mcp --source . --region=$REGION \
  --service-account=$MCP_SA --allow-unauthenticated --max-instances=3 \
  --set-env-vars="^;^GOOGLE_CLIENT_ID=<portal OAuth client id>;ALLOWED_USERS=<a@x.ua,b@x.ua>;MCP_BASE_URL=$MCP_URL;AUTH_FIRESTORE_DATABASE=mcp-auth;API_URL=$API_URL;API_AUDIENCE=$API_URL" \
  --set-secrets=GOOGLE_CLIENT_SECRET=portal-google-client-secret:latest,MCP_JWT_SIGNING_KEY=mcp-jwt-signing-key:latest

# 4. The API: the same role the portal holds on it, and leave to call without
#    a user. --update-env-vars keeps the API's other settings; both URLs
#    Cloud Run gives the API are accepted as audience.
gcloud run services add-iam-policy-binding hd-api --region=$REGION \
  --member=serviceAccount:$MCP_SA --role=roles/run.invoker
gcloud run services update hd-api --region=$REGION \
  --update-env-vars="^;^SERVICE_CALLERS=$MCP_SA;SERVICE_TOKEN_AUDIENCE=https://hd-api-5c64nevodq-lm.a.run.app,$API_URL"
```

In the Google Cloud console, the portal's OAuth client also needs
`$MCP_URL/auth/callback` among its authorized redirect URIs.

Check a deploy with `curl $MCP_URL/.well-known/oauth-authorization-server`
(200) and an unauthenticated `POST $MCP_URL/mcp` (401). Claude Desktop adds
it as a custom connector at `$MCP_URL/mcp`.
