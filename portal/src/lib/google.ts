import "server-only";

const TOKEN_URL = "https://oauth2.googleapis.com/token";

export type RefreshedTokens = { idToken: string; refreshToken?: string };

/**
 * A new Google ID token for the signed-in user, from their refresh token.
 *
 * A Google ID token lasts an hour and the API rejects an expired one, so the
 * token from sign-in cannot simply be kept and forwarded.
 */
export async function refreshIdToken(refreshToken: string): Promise<RefreshedTokens> {
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: requireEnv("GOOGLE_CLIENT_ID"),
      client_secret: requireEnv("GOOGLE_CLIENT_SECRET"),
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    }),
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || typeof body.id_token !== "string") {
    throw new Error(`Google refused to refresh the token: ${response.status} ${body.error ?? ""}`);
  }
  // Google usually keeps the refresh token the same and omits it here.
  return { idToken: body.id_token, refreshToken: body.refresh_token };
}

export function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set`);
  return value;
}
