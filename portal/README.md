# Marketing portal

A Next.js app for the marketing team: sign in with a Google (Gmail) account,
type a query, and see what the search API finds -- products, Instagram
messages, content -- as formatted JSON in a chat. Spec:
`../specs/marketing-portal.md`.

```bash
npm install
cp .env.example .env.local   # fill it in, see below
npm run dev                  # http://localhost:3000

npm test                     # token and allowlist helpers
npm run typecheck && npm run lint
npm run build
```

## How a search travels

```
browser ──cookie──▶ /api/search (this app) ──▶ search API /searchcontext
                     Authorization: Bearer <service token>   checked by Cloud Run
                     X-User-Token: <user's Google ID token>  checked by the API
```

- **Sign-in** (`src/lib/auth.ts`): Google through NextAuth, refused unless the
  account's email is verified and in `ALLOWED_USERS`.
- **Session**: an encrypted, HttpOnly cookie holding the user's Google ID
  token and refresh token. Only server code reads them; `/api/auth/session`
  returns name and email alone. Nothing is kept in the server's memory, so a
  Cloud Run restart does not sign anyone out.
- **Token refresh**: a Google ID token lasts an hour. The page re-fetches the
  session every five minutes and on focus, which renews it; `/api/search`
  renews it too if a call arrives after it lapsed.
- **API call** (`src/lib/api.ts`): the browser never calls the API. The
  server adds an ID token for its own service account from the metadata
  server -- no key anywhere -- when `API_AUDIENCE` is set.

## Settings

See `.env.example`. `ALLOWED_USERS` should match the API's.

## Google OAuth client

One-time, in the Google Cloud console:

1. **Google Auth Platform → Audience: External** -- users sign in with Gmail
   accounts, not a Workspace domain. **Publish the app.** Left in *Testing*,
   Google expires refresh tokens after 7 days and everyone has to sign in
   again each week. With only the `openid`, `email` and `profile` scopes, which
   are not sensitive, publishing needs no verification review.
2. **Clients → Create client → Web application.** Authorized redirect URIs:
   `http://localhost:3000/api/auth/callback/google` and, once deployed,
   `https://<portal URL>/api/auth/callback/google`.
3. Its client id goes in `GOOGLE_CLIENT_ID` here **and** in the API's
   `USER_TOKEN_AUDIENCE`.

## Deploying to Cloud Run

Nothing below has been run. The portal is public -- it is the sign-in page --
and runs as its own service account, the one the API admits.

```bash
PROJECT=project-b2b68530-7524-4ecc-8e6
REGION=europe-central2
PORTAL_SA=hd-portal@$PROJECT.iam.gserviceaccount.com
API_URL=<the hd-api service URL>

gcloud iam service-accounts create hd-portal

openssl rand -base64 32 | gcloud secrets create portal-nextauth-secret --data-file=-
printf %s "$GOOGLE_CLIENT_SECRET" | gcloud secrets create portal-google-client-secret --data-file=-
for s in portal-nextauth-secret portal-google-client-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$PORTAL_SA --role=roles/secretmanager.secretAccessor
done

gcloud run deploy hd-portal --source . --region=$REGION \
  --service-account=$PORTAL_SA --allow-unauthenticated \
  --set-env-vars="^;^GOOGLE_CLIENT_ID=<client id>;ALLOWED_USERS=<a@gmail.com,b@gmail.com>;API_URL=$API_URL;API_AUDIENCE=$API_URL" \
  --set-secrets=NEXTAUTH_SECRET=portal-nextauth-secret:latest,GOOGLE_CLIENT_SECRET=portal-google-client-secret:latest

# The URL is known only after the first deploy.
gcloud run services update hd-portal --region=$REGION \
  --update-env-vars=NEXTAUTH_URL=<the hd-portal service URL>

# Let the portal, and nothing else, call the API.
gcloud run services add-iam-policy-binding hd-api --region=$REGION \
  --member=serviceAccount:$PORTAL_SA --role=roles/run.invoker
```
