---
name: create-contract
description: Creates a language-agnostic interface and behavioral contract skeleton for a software component/service.
---

When asked to create a contract:

1. Create a language-independent Markdown contract.
2. Do not generate implementation code.
3. Do not assume a programming language.
4. Do a skeleton of the contract based on information provided. If no information is available, just do an empty contract.
5. Define shared data structures under Data Contracts.
6. Put unresolved decisions under Open Questions.
7. Prefer precise, testable statements.
8. Do not invent requirements. If information is missing, leave a placeholder or Open Question.
9. Keep description precise and as short as possible just to convey the essential information.

Use the structure described in @contract-template.md
Use the example defined in @examples/example-contract.md