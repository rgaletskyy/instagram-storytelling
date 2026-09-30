"use client";

import { SessionProvider } from "next-auth/react";

// Fetching the session runs the `jwt` callback, which renews the user's Google
// ID token before it lapses and stores it back in the cookie.
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={5 * 60} refetchOnWindowFocus>
      {children}
    </SessionProvider>
  );
}
