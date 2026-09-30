import assert from "node:assert/strict";
import { test } from "node:test";

import {
  REFRESH_MARGIN_SECONDS,
  isAllowed,
  needsRefresh,
  parseAllowlist,
  tokenExpiry,
} from "./tokens.ts";

function jwt(claims: object): string {
  const part = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${part({ alg: "RS256" })}.${part(claims)}.signature`;
}

test("reads the expiry from the token's payload", () => {
  assert.equal(tokenExpiry(jwt({ exp: 1_900_000_000 })), 1_900_000_000);
});

test("an unreadable token has no expiry, so it always needs refreshing", () => {
  assert.equal(tokenExpiry("not-a-jwt"), 0);
  assert.equal(tokenExpiry("a.%%%.c"), 0);
  assert.equal(needsRefresh("not-a-jwt"), true);
});

test("a token is refreshed shortly before it expires, not only after", () => {
  const now = 1_000_000;
  assert.equal(needsRefresh(jwt({ exp: now + 3600 }), now), false);
  assert.equal(needsRefresh(jwt({ exp: now + REFRESH_MARGIN_SECONDS }), now), true);
  assert.equal(needsRefresh(jwt({ exp: now - 1 }), now), true);
});

test("the allowlist ignores case, spaces and empty entries", () => {
  assert.deepEqual(
    [...parseAllowlist(" Anna@HealthyDoggo.ua , ,petro@gmail.com")],
    ["anna@healthydoggo.ua", "petro@gmail.com"],
  );
  assert.equal(parseAllowlist(undefined).size, 0);
});

test("only a verified email on the list may sign in", () => {
  const allowlist = parseAllowlist("anna@healthydoggo.ua");
  assert.equal(isAllowed("ANNA@healthydoggo.ua", true, allowlist), true);
  assert.equal(isAllowed("anna@healthydoggo.ua", false, allowlist), false);
  assert.equal(isAllowed("anna@healthydoggo.ua", "true", allowlist), false);
  assert.equal(isAllowed("eve@gmail.com", true, allowlist), false);
  assert.equal(isAllowed(undefined, true, allowlist), false);
  assert.equal(isAllowed("anna@healthydoggo.ua", true, parseAllowlist("")), false);
});
