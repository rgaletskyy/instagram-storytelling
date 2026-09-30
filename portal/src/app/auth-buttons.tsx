"use client";

import { signIn, signOut } from "next-auth/react";

import styles from "./page.module.css";

export function SignIn() {
  return (
    <button className={styles.primary} onClick={() => signIn("google", { callbackUrl: "/" })}>
      Sign in with Google
    </button>
  );
}

export function SignOut() {
  return (
    <button className={styles.link} onClick={() => signOut({ callbackUrl: "/" })}>
      Sign out
    </button>
  );
}
