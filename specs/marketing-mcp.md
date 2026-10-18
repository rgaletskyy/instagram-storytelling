# Highlevel overview and purpose

hd-marketing-mcp server exposes tools to simplify work for SMM managers via searching, creating or improving existing content.
MCP will have next functionality:
- helps to find proper bits of content inside repository of contents. Uses Firectore vector index for search.
- modify or improve existing image
- generate image(s) from scratch using prompts and samples
- create script for story telling
- generate copy according to brand rules
- generate slide for story telling containing text, image and brand elements
- validate copy and return comments
- validate slide and return comments
- search content insights via customers query. E.g - top 5 posts from May based on customersInteraction

## Tools


### search_knowledge_base

Invoke this tool when user asks about product information, reviews, questions about product or explicitly asks to search for product related content.
Use this tool to get extra information about product.

#### parameters

- query: string, A standalone search query. Rewrite the customer's message so it makes sense without the conversation: replace pronouns with the product or topic
they refer to, include relevant details mentioned earlier (dog age, breed, problem, lifestyle or promo photos), and drop greetings and filler. Pay attention on 
description what should be present on content item. Extract most important descriptions customer provides for desired content to build a target query.
- productSku: string, id that identifies product among others. Extract it from customer query as single string parameter
- hasDog: boolean, parameter that specifies if content should contain a dog. Don't pass anything if it's not possible to extract it from messaging
- contentType: Enum item ["лайфстайл", "креатив", "продуктове"], Kind of media to return. 
    "лайфстайл" = real-life photos or videos of dogs or people using products;
    "креатив" = designed banners with text, prices, or buttons;
    "продуктове" = product-only shots on a plain background.
    Leave empty if the user did not indicate a kind.


### search_content_insights

Invoke this tool when users asks about instagram posts, sotries, reels that matches some performance insights and stats. For example `top 5 posts from May 2026 that have most of interactions`, `search for two best performaing posts by likes and comments in period 01.01.2026-01.04.2026`, `Post from September that got maximum views and shares`, `Story from previous week that received maximum likes`


#### parameters

Passed to the search API's `POST /searchContentInsights` as is (see [search-api.md](search-api.md), [content-insights-service.md](content-insights-service.md)).

- from: string, required, ISO 8601 datetime (e.g. `2026-05-01T00:00:00`). Start of the period in which the content was published, inclusive.
  Resolve the period the user names into exact dates: "May" = from the 1st of May 00:00:00; "previous week" = Monday 00:00:00 of last week; "in 2025" = 2025-01-01T00:00:00.
  Dates written as 01.04.2026 are day.month.year. Use the current year when the user gives none, or the previous one if that month has not come yet.
  Without any period, use the last 30 days. Without a timezone, taken as UTC.
- to: string, optional, ISO 8601 datetime. End of the publication period, inclusive, e.g. `2026-05-31T23:59:59` for "May".
  Leave empty when the period runs up to now ("since March", "last 30 days"). Must not be before `from`.
- mediaProductType: Enum item ["FEED", "STORY", "REELS", "AD"], where the content was published.
    "FEED" = posts in the profile grid (photo or carousel posts);
    "STORY" = stories;
    "REELS" = reels;
    "AD" = ads.
    Leave empty if the user did not name a kind, or said "content" or "publications" in general.
- mediaType: Enum item ["IMAGE", "VIDEO", "CAROUSEL_ALBUM"], format of the media.
    "IMAGE" = a single photo;
    "VIDEO" = a video (reels are always VIDEO);
    "CAROUSEL_ALBUM" = a carousel of several photos or videos.
    Leave empty unless the user explicitly asks for photos, videos or carousels.
- sortBy: string, optional, comma-separated metric names, at most three, most important first (e.g. `likes,saved`). Results are sorted from highest to lowest.
    "views" = how many times the content was shown;
    "totalInteractions" = likes, comments, saves, shares and replies together; use it for "interactions", "engagement", "best performing", or when the user combines likes with comments;
    "likes" = likes;
    "saved" = saves;
    "shares" = shares;
    "reposts" = reposts.
    Leave empty to get the newest content first.
- topN: integer, optional, at least 1. How many items to return, taken after sorting: "top 5 posts" = 5, "two best" = 2,
  "the post with the most views" = 1. Leave empty when the user gives no number and asks for everything in the period.


### modify_image

### generate_image

### create_storytelling_script

### create_textcopy

### create_smm_slide

### validate_textcopy

### validate_smm_slide

