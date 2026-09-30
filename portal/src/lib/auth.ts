import "server-only";

import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

import { refreshIdToken } from "./google";
import { isAllowed, needsRefresh, parseAllowlist } from "./tokens";

/**
 * Sign-in with a Google account, limited to the emails in ALLOWED_USERS.
 *
 * The session is a JWT encrypted with NEXTAUTH_SECRET in an HttpOnly cookie.
 * It holds the user's Google ID token and refresh token, which only server
 * code reads: the `session` callback below leaves them out of what the browser
 * can fetch.
 */
export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt" },
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      authorization: {
        // offline + consent: Google returns a refresh token, without which the
        // hour-long ID token could not be renewed.
        params: { prompt: "consent", access_type: "offline", response_type: "code" },
      },
    }),
  ],
  pages: { signIn: "/", error: "/" },
  callbacks: {
    async signIn({ profile }) {
      const google = profile as { email?: string; email_verified?: boolean } | undefined;
      // Read on every sign-in, so a change to the list needs no rebuild.
      return isAllowed(google?.email, google?.email_verified, parseAllowlist(process.env.ALLOWED_USERS));
    },
    async jwt({ token, account }) {
      if (account) {
        return {
          ...token,
          idToken: account.id_token,
          refreshToken: account.refresh_token,
          error: undefined,
        };
      }
      if (token.idToken && !needsRefresh(token.idToken)) return token;
      if (!token.refreshToken) return { ...token, error: "RefreshTokenMissing" };
      try {
        const refreshed = await refreshIdToken(token.refreshToken);
        return {
          ...token,
          idToken: refreshed.idToken,
          refreshToken: refreshed.refreshToken ?? token.refreshToken,
          error: undefined,
        };
      } catch {
        return { ...token, error: "RefreshFailed" };
      }
    },
    async session({ session, token }) {
      // Name, email and picture only -- never the tokens.
      session.error = token.error;
      return session;
    },
  },
};
