# Highlevel overview and purpose

hd-marketing-mcp server exposes tools to simplify work for SMM managers via searching, creating or improving existing content.
MCP will have next functionality:
- helps to find proper bits of content inside repository of contents
- modify or improve existing image
- generate image(s) from scratch using prompts and samples
- create script for story telling
- generate copy according to brand rules
- generate slide for story telling containing text, image and brand elements
- validate copy and return comments
- validate slide and return comments

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


### modify_image

### generate_image

### create_storytelling_script

### create_textcopy

### create_smm_slide

### validate_textcopy

### validate_smm_slide

