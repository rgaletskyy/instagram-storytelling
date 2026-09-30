import "server-only";

import { GoogleAuth, type IdTokenClient } from "google-auth-library";

import { requireEnv } from "./google";

const googleAuth = new GoogleAuth();
let serviceClient: Promise<IdTokenClient> | undefined;

/**
 * An ID token for this service's own account, with the API's URL as audience.
 *
 * On Cloud Run it comes from the metadata server, so no key exists anywhere.
 * Cloud Run checks it in front of the API and lets through only the account
 * granted roles/run.invoker. Left out when API_AUDIENCE is unset, which is how
 * the portal talks to an API running locally with no Cloud Run in front.
 */
async function serviceToken(): Promise<string | undefined> {
  const audience = process.env.API_AUDIENCE;
  if (!audience) return undefined;
  serviceClient ??= googleAuth.getIdTokenClient(audience);
  return (await serviceClient).idTokenProvider.fetchIdToken(audience);
}

export type ApiResponse = { status: number; body: unknown };

/** POST /searchcontext as the signed-in user. */
export async function searchContext(query: string, userIdToken: string): Promise<ApiResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-User-Token": userIdToken,
  };
  const token = await serviceToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(new URL("/searchcontext", requireEnv("API_URL")), {
    method: "POST",
    headers,
    body: JSON.stringify({ query }),
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({ detail: response.statusText }));
  return { status: response.status, body };
}
