# SearchService

## Responsibility

Returns documents from the `products`, `instagram_messages` and `content` collections that are semantically close to a user query.

## Logic

- Use TypeSafe's JEV model to decide which collections to search against. Use Jev probability output that ranks each collection.
Endpoint: POST https://api.typesafe.ai/v1/systemone, with model jev-latest (currently jev-1.13.0). Use 0.3 as a treshhold. Each collection will have a hardcoded description.
- Embed user query using same model. 
- Execute call to FireStore database

## Methods

### findSimilar

Purpose:
- find documents related to a text query across all collections

Input:
- query: string, required
  - user query as free text
  - must not be empty

Output:
- SearchResult

Errors:
- InvalidArgument — query is empty
- EmbeddingError — embedding model or collection classifier cannot be reached
- DataSourceError — Firestore cannot be accessed

Behavior:
- Query is embedded with the same model and dimension as the indexed documents (`gemini-embedding-2`, 1536)
- A collection is searched only if its classifier probability is >= 0.3
- A collection that is not searched, or has no matches, yields an empty list, never null
- Each list holds documents of its own collection only
- Must not modify stored documents
- Use distanceMeasure: "COSINE" in FireStore
- Incldue distanceResultField, and pick top 5 results with the best match
- Documents in each field are sorted by similarity descending
- Return empty collections if no similar documents

Side Effects:
- None

## Data Contracts

### SearchResult

- products: list<Product>, required, default []
- instagramMessages: list<InstagramMessage>, required, default []
- content: list<Content>, required, default []

### Product, InstagramMessage, Content

- fields as in the collection schemas in [hd-marketing-rag.md](hd-marketing-rag.md)
- `embeddingText` and `embeddingVector` are not returned
