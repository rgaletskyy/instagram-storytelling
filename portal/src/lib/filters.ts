// The content filters the search API takes. Pure, so the chat, the server
// route and `node --test` all share one definition.

export const CONTENT_TYPES = ["лайфстайл", "креатив", "продуктове"] as const;
export type ContentType = (typeof CONTENT_TYPES)[number];
export const DEFAULT_CONTENT_TYPE: ContentType = "лайфстайл";

export type SearchFilters = {
  type: ContentType;
  /** true: only files with a dog. false: only files without one. Absent: either. */
  hasDog?: boolean;
};

// The portal's dog control. "any" leaves hasDog out of the request, so the
// API returns files with or without a dog; the other two ask for one or the
// other.
export type DogChoice = "any" | "with" | "without";
export const DOG_CHOICES: { value: DogChoice; label: string }[] = [
  { value: "any", label: "Any" },
  { value: "with", label: "With a dog" },
  { value: "without", label: "Without a dog" },
];

export function toFilters(type: ContentType, dog: DogChoice): SearchFilters {
  return dog === "any" ? { type } : { type, hasDog: dog === "with" };
}

export function isContentType(value: unknown): value is ContentType {
  return typeof value === "string" && (CONTENT_TYPES as readonly string[]).includes(value);
}

/** The filters in a request body, or why they are not acceptable. */
export function parseFilters(
  body: { type?: unknown; hasDog?: unknown } | null | undefined,
): { filters: SearchFilters } | { error: string } {
  const type = body?.type ?? DEFAULT_CONTENT_TYPE;
  if (!isContentType(type)) {
    return { error: `Type must be one of ${CONTENT_TYPES.join(", ")}.` };
  }
  const hasDog = body?.hasDog;
  if (hasDog !== undefined && hasDog !== null && typeof hasDog !== "boolean") {
    return { error: "hasDog must be true or false." };
  }
  return { filters: typeof hasDog === "boolean" ? { type, hasDog } : { type } };
}
