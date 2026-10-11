"use client";

import { signIn } from "next-auth/react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import {
  CONTENT_TYPES,
  DEFAULT_CONTENT_TYPE,
  isContentType,
  type ContentType,
  type SearchFilters,
} from "@/lib/filters";

import styles from "./page.module.css";

type Entry =
  | { role: "user"; text: string; filters: SearchFilters }
  | { role: "result"; data: unknown }
  | { role: "error"; text: string; signInAgain?: boolean };
type Message = Entry & { id: number };

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [contentType, setContentType] = useState<ContentType>(DEFAULT_CONTENT_TYPE);
  // Off means with or without a dog, not "without": the switch only narrows.
  const [withDog, setWithDog] = useState(false);
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
    const filters: SearchFilters = withDog
      ? { type: contentType, hasDog: true }
      : { type: contentType };
    add({ role: "user", text, filters });
    setQuery("");
    setBusy(true);
    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, ...filters }),
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
      <div className={styles.filters}>
        <label className={styles.field}>
          Content type
          <select
            value={contentType}
            onChange={(event) => {
              if (isContentType(event.target.value)) setContentType(event.target.value);
            }}
            disabled={busy}
          >
            {CONTENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <button
            type="button"
            role="switch"
            aria-checked={withDog}
            className={styles.switch}
            onClick={() => setWithDog((on) => !on)}
            disabled={busy}
          >
            <span className={styles.knob} />
          </button>
          With a dog
        </label>
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
    return (
      <div className={styles.userMessage}>
        {message.text}
        <span className={styles.filterTag}>
          {message.filters.type}
          {message.filters.hasDog ? " · with a dog" : ""}
        </span>
      </div>
    );
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
