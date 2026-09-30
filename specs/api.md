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

# Endpoints

## searchcontext


### Request

POST /searchcontext
Body: {query: ""}

### Response

Serialized contract from searchservice

