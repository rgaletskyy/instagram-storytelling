import { getServerSession } from "next-auth";

import { authOptions } from "@/lib/auth";

import { Chat } from "./chat";
import { SignIn, SignOut } from "./auth-buttons";
import styles from "./page.module.css";

// Error codes NextAuth puts in the URL when sign-in fails.
const SIGN_IN_ERRORS: Record<string, string> = {
  AccessDenied: "This Google account is not allowed to use the portal.",
};

export default async function Home(props: PageProps<"/">) {
  const session = await getServerSession(authOptions);
  const { error } = await props.searchParams;

  if (!session?.user?.email || session.error) {
    const code = typeof error === "string" ? error : undefined;
    const message = session?.error
      ? "Your session expired. Sign in again."
      : code && (SIGN_IN_ERRORS[code] ?? "Sign-in failed. Try again.");
    return (
      <main className={styles.centered}>
        <h1>HealthyDoggo Marketing</h1>
        <p>Sign in with your Google account.</p>
        {message && <p className={styles.error}>{message}</p>}
        <SignIn />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1>Content search</h1>
        <span className={styles.user}>
          {session.user.email} <SignOut />
        </span>
      </header>
      <Chat />
    </main>
  );
}
