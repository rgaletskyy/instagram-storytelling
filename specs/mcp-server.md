# Highlevel task

I want to build application on Python for generating story telling for instagram (series of stories). Application should have MCP server to connect it to Claude/OpenAi chats and MCP client + Python moduile to run from code locally.
Application receives array of images and string with topic as input. Input should be taken from content/input folder. Output should be written to content/output folder.

# Technologies and infrastructure

Python, ffmpeg, claude api, gemini api

# Architecture and implementation

Application consists from MCP server, MCP client, Python module (for executing from code)
MCP server should expose resources, tools and prompts. MCP server will be used in claude chats or custom AI chats. MCP client and Python module should be used to run applicaiton on local PC from code.

## MCP server structure

MCP server will run locally via stdio.
MCP server should expose these:

### TOOLS

<!-- Start an agentic workflow that generates instagram story telling based on higlevel brief and input content - images or/and video -->
<!-- As input receives array of product skus or names, topic we discuss in story telling, number of slides -->
create_story_campaign

<!-- Returns all information about product, inclduing text, price and reference to image and website -->
get_product

<!-- Generates bacvkground image using with Nano Banana using prompt provided-->
generate_image

<!-- Generates script for whole storytelling campaign -->
generate_storytelling_script

<!-- Renders ready to use design with background image, text overlays, emojis and other UI symbols -->
render_story_slide

<!-- Will be added in next iterations -->
validate_slide

<!-- Updates existing slide with cahgnes to text, colors or layout -->
regenerate_slide

<!-- Describes image in text using Sonnet model -->
describe_image

<!-- Extracts audio uisng ffmpeg and then transcribes to text with nano banana -->
transcribe_video

<!-- Saves generated iamges in .jpg fromat on local drive -->
save_project

### RESOURCES

<!-- Describes brand guidelines and generice rules for user story composition-->
content://story-design-guidelines.md

<!-- List of rules how to do story telling. Descriebs what should go first, waht shouild be ending of story telling. Which slide will contain links or instagram built-in objects like stikers, emojis, polls etc -->
content://story-telling-rules.md

## MCP internal implementation

### Create story campaign

entry method that runs whole processing:

1. fetch products data, describe images, describe video
2. Generates campaign script from descriptions
3. Run slides generation in parallel using info from story telling script
4. Save project

### Transcribe video

Use ffmpgeg tool to extract audio. Then transcribe audio into text with nanobanana

### Describe image

USe sonnet Claude model to describe in details the image. Images will be located on server harddrive in firt version of app.

### Get Product

Using provided list of skus or product names fetch products from excel. Excel will be stored as static file on server.
Response will contain product text, price, link to main image

### Generate story telling script

Using products information, description of each image and campaign topic generate script for story telling. Script should contain prompt for each image to generate, text that should be added as overlay and notes about instagram objects to add durring possting on instagram. After generation script file should be saved along with resulting images in output directory. Use @src/resources/story-telling-rules.md as a context when generating script

### Generate image

Use internal prompt and image description from generated script to generate image with gemini nano banana. Save resulting image in output directory

### Render story slide

Take generated iamge and apply text overlay or/and other visual effects using ffmpeg. Use design guidelines resource on this step

### Regeenrate slide 

Rerenders slide using user comments

### Describe video

use ffmpeg to extract 5-10 slides from video as images. Then describe each image using _describe_image tool. Then Transcribe video to get description. Complie all descriptions into one. 

### save project

Save all resulting slides along with story script into seperate fodler. Name folder based on topic + date_time ending

## MCP Client

Clien will be used to execute tools, resources, prompts from Python module.

## Python module

Python module will be used to run workflow from code. Module will directly execute create_story_cmpaing workflow

# Models to use

Use latest sonnet for images and video description
Use gemini-3.1-flash-lite-image to transctibe audio into text
USe gemini-3.1-flash-image to generate images
If image need to be regenerated use gemini-3-pro-image
Use latet claude opus to generate campaing script containing prompt for each image and label(s)

## FFMpeg integration

Use ffmpeg documentation to find proper commands.

Build integration with local ffmpeg to perform operations
1. Extract audio
2. Extract frames at specified timecode
3. Add text overlay over image
4. draw over image

## Products fetch logic
Fetch product info from src/resources/products.xlsx file. Return next fields: shortened file name, description, image url, price
