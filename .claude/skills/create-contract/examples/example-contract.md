# ProductCatalog

## Responsibility:
Provides access to products available in the catalog.

## Methods

### getProduct

Purpose:
- return information about product

Input:
- productId: string, required
  - Unique product identifier
  - Must not be empty

Output:
- Product | null
  - Product if found
  - null if product does not exist

Errors:
- InvalidArgument — productId is empty
- DataSourceError — catalog cannot be accessed

Behavior:
- Must not modify product data
- Must not cache results
- Same productId must refer to the same catalog product


### searchProducts

Purpose:
- search products by filter

Input:
- criteria: ProductSearchCriteria
  - brand: string, optional
  - query: string, optional

Output:
- list<Product>

Errors:
- InvalidArgument — productId is empty
- DataSourceError — catalog cannot be accessed

Behavior:
- Multiple criteria use AND semantics
- Empty result → empty list, never null
- No duplicate products

## Data Contracts

### Product

- id: string, required
- name: string, required
- brand: string, required
- description: string, optional
- images: list<Image>, default []
- price: decimal, required, >= 0