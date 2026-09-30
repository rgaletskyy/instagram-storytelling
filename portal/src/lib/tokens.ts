// Pure helpers, kept free of Next.js and network imports so `node --test` can
// run them directly.

/** Seconds before expiry at which a Google ID token is treated as expired. */
export const REFRESH_MARGIN_SECONDS = 60;

/** The `exp` claim of a JWT, in seconds since the epoch; 0 if unreadable. */
export function tokenExpiry(jwt: string): number {
  const payload = jwt.split(".")[1];
  if (!payload) return 0;
  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    return typeof claims.exp === "number" ? claims.exp : 0;
  } catch {
    return 0;
  }
}

/** True when the token is expired or will be within the margin. */
export function needsRefresh(jwt: string, nowSeconds = Date.now() / 1000): boolean {
  return tokenExpiry(jwt) - REFRESH_MARGIN_SECONDS <= nowSeconds;
}

/** Comma-separated emails, lower-cased. Empty or unset means nobody. */
export function parseAllowlist(value: string | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(",")
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function isAllowed(
  email: string | null | undefined,
  emailVerified: unknown,
  allowlist: Set<string>,
): boolean {
  return Boolean(email) && emailVerified === true && allowlist.has(email!.toLowerCase());
}
