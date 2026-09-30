"use client";

import { signIn } from "next-auth/react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import styles from "./page.module.css";

type Entry =
  | { role: "user"; text: string }
  | { role: "result"; data: unknown }
  | { role: "error"; text: string; signInAgain?: boolean };
type Message = Entry & { id: number };

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const nextId = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  function add(entry: Entry) {
    setMessages((all) => [...all, { ...entry, id: nextId.current++ }]);
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const text = query.trim();
    if (!text || busy) return;
    add({ role: "user", text });
    setQuery("");
    setBusy(true);
    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        add({ role: "result", data: body });
      } else {
        add({
          role: "error",
          text: describeError(response.status, body),
          signInAgain: response.status === 401,
        });
      }
    } catch {
      add({ role: "error", text: "The portal could not be reached." });
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter starts a new line.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  }

  return (
    <section className={styles.chat}>
      <div className={styles.messages}>
        {messages.length === 0 && (
          <p className={styles.hint}>
            Ask about products, Instagram conversations or photos and videos, e.g. «шампунь для шпіца».
          </p>
        )}
        {messages.map((message) => (
          <MessageView key={message.id} message={message} />
        ))}
        {busy && <p className={styles.hint}>Searching…</p>}
        <div ref={bottom} />
      </div>
      <form className={styles.composer} onSubmit={send}>
        <textarea
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Enter a query"
          rows={2}
          disabled={busy}
          aria-label="Query"
        />
        <button className={styles.primary} type="submit" disabled={busy || !query.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}

function MessageView({ message }: { message: Message }) {
  if (message.role === "user") {
    return <div className={styles.userMessage}>{message.text}</div>;
  }
  if (message.role === "error") {
    return (
      <div className={styles.errorMessage}>
        {message.text}
        {message.signInAgain && (
          <button className={styles.link} onClick={() => signIn("google", { callbackUrl: "/" })}>
            Sign in again
          </button>
        )}
      </div>
    );
  }
  return (
    <div className={styles.resultMessage}>
      <p className={styles.summary}>{summarize(message.data)}</p>
      <pre>{JSON.stringify(message.data, null, 2)}</pre>
    </div>
  );
}

function summarize(data: unknown): string {
  const result = (data ?? {}) as Record<string, unknown[] | undefined>;
  const count = (key: string) => result[key]?.length ?? 0;
  return `${count("products")} products · ${count("instagramMessages")} messages · ${count("content")} content`;
}

function describeError(status: number, body: { detail?: unknown }): string {
  const detail = typeof body?.detail === "string" ? body.detail : "";
  if (status === 403) return detail || "Your account is not allowed to search.";
  return detail || `The search failed (${status}).`;
}
