# Highlevel overview and purpose

hd-marketing-mcp server exposes tools to simplify work for SMM managers via searching, creating or improving existing content, searching insights and posted content by filters.
MCP will have next functionality:
- helps to find content inside repository of contents. Uses Firectore vector index for search.
- search content insights via customers query. E.g - top 5 posts from May based on customers interaction.
- generate copy/caption for post according to brand rules.
- validate captions and return comments, improvements.
- generate image(s) from scratch using user input and/or samples
- generate slide for story telling containing text, image and brand elements
- search thru client DM and comments to posts

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


### generate_image

Invoke this tool when user asks to generate image based on his description of the scene and elements that should be present on it. For example `собака сидить біля баночки з вітамінами`, `собака сидить у ванні, рука тримає шампунь Seтsitive Skin біля мордочки собаки`


#### parameters

- subject: string, A standalone subject that describes what should be on image. Rewrite the customer's message so it makes sense without the conversation: replace pronouns with the product or topic they refer to, include relevant details mentioned earlier (dog age, breed, problem, lifestyle or promo photos), and drop greetings and filler. Pay attention on 
description what should be present on content item. Extract most important descriptions customer provides for desired image.
- products: array of products that has to be present on image. Extract exact SKU if possible from conversation. If sku not presented, include product name or names mentioned in conversation.
- contentType: string, defines type of content. One of `Product photo`, `Lifestyle`, `Studio photoshoot`, `UGC`
- composition: string, describes how elements are positioned and framed. One of `Centered`, `Rule of Thirds`, `Flat Lay`, `Close-up`, `Wide`
- cameraLevel: string, defines the position of the camera relative to the subject. It determines whether the viewer sees the product from above, below, directly in front, or from the side. One of `Eye Level`, `High Angle`, `Top-Down`, `Low Angle`, `Ground Level`
- aspectRatio, string, Describes aspect ratio for content - portrait (posts), square (posts), full screen(story, reels) One of `9:16`, `1:1`, `4:5`; `4:5` when not given
- sampleUrls, string[], array if urls popinting to sample images, that have to be considered when generating new image

#### behaviour

- Each entry of `products` is looked up with `POST /searchcontent`: as a SKU first (`productSku` = the entry, exact match), otherwise by name (the closest product). The product's `imageUrl`, its main catalogue photo, is used as the reference; a product without one is drawn from its name.
- Product photos and `sampleUrls` are downloaded (Drive share links via their download link, shared by link), shrunk and attached to the Gemini request, at most 8 in all, with a rule to reproduce products, dogs and people as photographed.
- Returns the image as image content in the chat, plus a text note when a product had no photo or a photo was skipped. A sample that cannot be downloaded, or no image from Gemini, is a tool error.


### generate_slide

Invoke this tool when users asks to generate slide for story or post carousel based on input. For example `згенеруй слайд для сторіз використовуючи фотою На фото має буде текст в брендовому стилі із заклитком перейти за посиланням, під ним тест який вказує ціну продукту`


#### parameters

- subject: string, A standalone subject that describes what should be on slide. Rewrite the customer's message so it makes sense without the conversation: replace pronouns with the product or topic they refer to, include relevant details mentioned earlier (dog age, breed, problem, lifestyle or promo photos), and drop greetings and filler. Pay attention on 
description what should be present on slide, objects, text.
- backgroundImage: string, url to background image that should be used on this slide
- overlayText: string, text that should be present on slide
- aspectRatio: string, Describes aspect ratio for slide - portrait (posts), square (posts), full screen(story, reels) One of `9:16`, `1:1`, `4:5`; `9:16` when not given

#### behaviour

- `backgroundImage` is downloaded like a `generate_image` sample (Drive share links, HEIC) and shrunk to at most 2048 px.
- Claude, shown the background, writes the slide as one HTML document following `slide-design-guidelines.md`: 1080x1920 (`9:16`), 1080x1350 (`4:5`) or 1080x1080 (`1:1`), brand fonts, text inside the safe area, the text block at most 27% of the height and off the dog's face and the product, optional tinted decorative elements.
- Headless Chromium screenshots the page at that size. The page may load only its background, the decorative elements and Google Fonts, and runs no JavaScript.
- An image that does not load gets one new layout; a second failure, or a background that cannot be downloaded, is a tool error.
- Returns the slide as a JPEG image in the chat.


### search_messaging

Invoke this tool when users asks about instagram direct messages and comments and want to search thru them of fetch quantity. For example: `How many messages has been sent in June 2026`, `What is the most popular request in messages about Calmin Supplements`, `How many comments asking about product received in Septmeber 2025`

#### parameters

- from: string, optional, ISO 8601 datetime (e.g. `2026-05-01T00:00:00`). Start of the period, inclusive. Given only when the user names a period.
  Resolve the period the user names into exact dates: "May" = from the 1st of May 00:00:00; "previous week" = Monday 00:00:00 of last week; "in 2025" = 2025-01-01T00:00:00.
  Dates written as 01.04.2026 are day.month.year. Use the current year when the user gives none, or the previous one if that month has not come yet.
  Without a timezone, taken as UTC.
- to: string, optional, ISO 8601 datetime. End of the period, inclusive, e.g. `2026-05-31T23:59:59` for "May".
  Leave empty when the period runs up to now ("since March", "last 30 days"). Must not be before `from`.
- messageType: string, type of messaging client is asking. One of Message | Comment | Both. If none specifeid use Both. If user mentions messages and comments use Both.
- query: string, context user is asking about. For example `Find all messages related to Calming Supplemenets in 2025`. Required when no period is given; not used with a period.

#### behaviour

Based on messageType fetch data from proper collection. If messageType=Message, fetch from `instagram_messages`, if messageType=Comment fetch from `instagram_comments`. If messageType=Both, fetch from both collections.
Passed to the search API's `POST /searchMessaging` (see [search-api.md](search-api.md)).
- With a period (`from` and/or `to`): the newest 50 messages and/or 50 comments in it, plus `totalMessagesCount` (unique conversations) and `totalCommentsCount` for the whole period. "How many" questions are answered from the totals.
- Without a period: the 20 messages and/or 20 comments closest to `query`, no totals.
- Neither a period nor a query is a tool error.
- Returns the API's MessagingSearchResult as is: `totalMessagesCount`, `totalCommentsCount`, `messages`, each a conversation's day (`sender` = the customer, `text` = the day's messages from both sides, one a line as `username: text`, `timestamp` = the first message), and `comments`, each with `parentId`, the post or reel.
