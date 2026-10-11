import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_CONTENT_TYPE, parseFilters } from "./filters.ts";

test("type defaults to lifestyle and hasDog is left out when not given", () => {
  assert.deepEqual(parseFilters({}), { filters: { type: DEFAULT_CONTENT_TYPE } });
  assert.deepEqual(parseFilters(null), { filters: { type: "лайфстайл" } });
  assert.deepEqual(parseFilters({ hasDog: null }), { filters: { type: "лайфстайл" } });
});

test("a known type and a boolean hasDog pass through", () => {
  assert.deepEqual(parseFilters({ type: "креатив", hasDog: true }), {
    filters: { type: "креатив", hasDog: true },
  });
  assert.deepEqual(parseFilters({ type: "продуктове", hasDog: false }), {
    filters: { type: "продуктове", hasDog: false },
  });
});

test("an unknown type or a non-boolean hasDog is refused", () => {
  assert.ok("error" in parseFilters({ type: "lifestyle" }));
  assert.ok("error" in parseFilters({ type: "" }));
  assert.ok("error" in parseFilters({ hasDog: "true" }));
});
