import { getToken } from "next-auth/jwt";
import type { NextRequest } from "next/server";

import { searchContext } from "@/lib/api";
import { refreshIdToken } from "@/lib/google";
import { needsRefresh } from "@/lib/tokens";

/**
 * The browser's only way to the API: it posts a query here, and this handler
 * calls the API with the service token and the user's own ID token, neither of
 * which the browser ever holds.
 */
export async function POST(request: NextRequest) {
  const token = await getToken({ req: request });
  if (!token?.email || !token.idToken) {
    return Response.json({ detail: "Sign in first." }, { status: 401 });
  }

  const body = await request.json().catch(() => null);
  const query = typeof body?.query === "string" ? body.query.trim() : "";
  if (!query) {
    return Response.json({ detail: "Enter a query." }, { status: 400 });
  }

  // The session is refreshed whenever the page fetches it; this covers a call
  // made after the ID token lapsed but before that happened. The refreshed
  // token is used for this call only.
  let idToken = token.idToken;
  if (needsRefresh(idToken)) {
    if (!token.refreshToken) {
      return Response.json({ detail: "Session expired. Sign in again." }, { status: 401 });
    }
    try {
      idToken = (await refreshIdToken(token.refreshToken)).idToken;
    } catch {
      return Response.json({ detail: "Session expired. Sign in again." }, { status: 401 });
    }
  }

  try {
    const { status, body: result } = await searchContext(query, idToken);
    return Response.json(result, { status });
  } catch (error) {
    console.error(JSON.stringify({ severity: "ERROR", message: "API call failed", user: token.email, error: String(error) }));
    return Response.json({ detail: "The search API could not be reached." }, { status: 502 });
  }
}
