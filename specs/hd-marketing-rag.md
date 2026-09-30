# Highlevel description

Solution implements RAG - Retrieval Augmented Generation for products from HealthyDoggo catalogue


# Architecture

Solution consist from several components:
- Firestore database on google cloud - `healthydoggo`
- indexer routine (runs locally only) that builds embeddings and stores document inside vector database
- SearchService used to find simialr documents


## Firestore vector database

Database `healthydoggo` contains three collections - `products`, `instagram_messages`, `content`.

### Products collection schema

- sku: string, SKU of product, 
- name: string,  product name,
- price: double, product price
- brand: string, product's brand
- category: string, product's category
- description: string, description of product,
- volume: string, volume of products(makes sense for cosmetics),
- weight: string,
- size: string,
- embeddingText: concatenation of sku, name, brand, category, decription, volume, size, weight
- embeddingVector: calcualted by embedding model

### Instagram_messages schema

- sender: string, id of message sender
- text: string, message text
- timestamp: timestamp whne mesdsage being sent
- embeddingText: text
- embeddingVector: calcualted by embedding model

### Content schema

- fileName: string
- driveUrl: string
- description: string
- screenshotsPath: string
- audioTranscribe: string
- product: string
- brand: string
- breed: string
- tags: string, list of words describing image
- type: string, `лайфстайл`, `креатив`, `продуктове` etc
- textOnImage: string, text that appears on image
- sizeKb: double, size of file in kilobytes
- embeddingText: string, concat description, audioTranscribe, product, brand, breed, tags, type, textOnImage
- embeddingVector: calcualted by embedding model


## Indexer routine

Purpose of indexing routine is to read data from excel file, build document, calculate embeddings and store into FireStore.
Use Gemini embedding model to calculate embeddings for each docuemnt. Dimension should be 1536: Firestore indexes vectors of at most 2048 dimensions, so the model's native 3072 could not be searched. Model gemini-embedding-2.
Read data from @src/resources/indices folder

## SearchService

Purpose of SearchService is to analyze user query and fetch related documents from vector database. Details described in @specs/search-service.md


# Code structure

## src

### infrastructure

- fireStoreClient - calls to FireStore database. Keeps hardcoded names of collections
- jevClient - calls to TypeSafe's model
- embeddingClient - embedding via gemini model

### domain

- searchService
- contracts

### routiens
- indexer