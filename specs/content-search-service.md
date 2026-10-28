# ContentSearchService

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
- hasDog: boolean, optional
  - if content should contain a dog on it (true), not contain one (false), or either (absent)
  - applies to content only; matched against `hasDog`, which the indexer sets when `breed` is not empty
- type: string, required
  - type of content to filter. one of `лайфстайл`, `креатив`, `продуктове`
  - must not be empty. default to `лайфстайл`
- productSku: string, optional
  - sku of product to filter products
  
Output:
- SearchResult

Errors:
- InvalidArgument — query is empty
- EmbeddingError — embedding model or collection classifier cannot be reached
- DataSourceError — Firestore cannot be accessed

Behavior:
- Query is embedded with the same model and dimension as the indexed documents (`gemini-embedding-2`, 1536)
- A collection is searched only if its classifier probability is >= 0.3
- When productSku is present, products are always searched, whatever their probability
- A collection that is not searched, or has no matches, yields an empty list, never null; the API leaves an empty list out of its response
- Each list holds documents of its own collection only
- Must not modify stored documents
- Use distanceMeasure: "COSINE" in FireStore
- Incldue distanceResultField, and pick the best matches: top 5 products, top 10 instagram messages, top 20 content
- Documents in each field are sorted by similarity descending
- Return empty collections if no similar documents

Side Effects:
- None

### findMessages

Purpose:
- find messages related to a text query and filtered by period

Input:
- query: string, optional; the topic to match. Required when neither `from` nor `to` is given
- from: timestamp, optional, inclusive; without a timezone, taken as UTC
- to: timestamp, optional, inclusive; now when absent. Must not be before `from`
- messageType: string, required, default Both
  One of Message | Comment | Both

Output:
- MessagingSearchResult

Errors:
- InvalidArgument — messageType outside the allowed values, `to` before `from`, or no period and an empty query
- EmbeddingError — embedding model cannot be reached
- DataSourceError — Firestore cannot be accessed

Behavior:
- Message reads `instagram_messages`, Comment reads `instagram_comments`, Both reads both
- The matches are the documents whose `timestamp` is in the period (`from` and/or `to`; the whole history without one) and, when a query is given, whose cosine distance to the embedded query is at most 0.4 (up to 1000 per collection, Firestore's maximum for one vector search). A message document is a conversation's day, dated by its first message
- At most 50 matches of each collection are returned: the closest first with a query, with `distance`; the newest first without one
- `totalMessagesCount` counts the conversations among all matches, each once however many of its days match (distinct `sender`), and `totalCommentsCount` the matching comments. With a query they are an estimate, since the match is by similarity
- A collection not read, or with no matches, yields an empty list
- Must not modify stored documents

## Data Contracts


### SearchResult

- products: list<Product>, required, default []
- instagramMessages: list<InstagramMessage>, required, default []
- content: list<Content>, required, default []

### Product, InstagramMessage, Content

- fields as in the collection schemas in [marketing-content-rag.md](marketing-content-rag.md)
- `embeddingText` and `embeddingVector` are not returned

### MessagingSearchResult

- messages: list<InstagramMessage>, optional, default []
- comments: list<InstagramComment>, optional, default [] (InstagramMessage's fields plus `parentId`, the post or reel)
- totalMessagesCount: integer, optional. The unique conversations among all matches (not only those returned); absent when messages are not read
- totalCommentsCount: integer, optional. The comments among all matches; absent when comments are not read