# Feature Specification: Instagram Story Telling Agent

**Feature Branch**: `001-instagram-story-agent`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Use specification from requirements.md file. Do not complicate things. Keep code to minimum"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a complete story campaign from local content (Priority: P1)

A marketer drops product photos (and optionally a short video) into the input folder, writes a one-paragraph brief describing the topic and desired narrative and naming the product SKU the story is about, and runs the campaign generator from code. The system studies the supplied media, looks the named SKU up in the product catalogue, writes a slide-by-slide story script that follows the brand's story-telling rules, produces a background image per slide, applies the text overlays and visual treatment required by the design guidelines, and saves the finished slides plus the script into a dated project folder in the output folder.

**Why this priority**: This is the entire product value. Without it nothing else has a reason to exist, and it is the one path that can be demonstrated end to end.

**Independent Test**: Place the sample images and a topic brief in the input folder, invoke the campaign workflow with a slide count, and confirm a new output project folder appears containing that number of finished slide images plus the script file.

**Acceptance Scenarios**:

1. **Given** input images and a topic brief are present in the input folder, **When** the user runs the campaign workflow requesting 5 slides, **Then** a new project folder is created in the output folder containing 5 rendered slide images and the campaign script.
2. **Given** the topic brief names one or more product SKUs, **When** the campaign workflow runs, **Then** those SKUs are looked up in the product catalogue and the generated script references the real product name, description and price returned by that lookup.
3. **Given** a campaign has been generated, **When** the user opens the saved script, **Then** each slide entry states its background-image prompt, its overlay text, and any Instagram interactive elements (stickers, polls, link) to add at posting time, and the script carries the product page URL for the link sticker.
4. **Given** the requested slide count is outside the supported story length, **When** the workflow runs, **Then** the system reports the valid range and does not produce a partial project.

---

### User Story 2 - Drive the same workflow from an AI chat (Priority: P2)

A user working inside Claude (or another compatible AI chat) connects to the locally running story server and asks it, in conversation, to build a campaign, fetch a product, describe an image, or render a single slide. The chat can also read the brand's design guidelines and story-telling rules directly so its suggestions stay on-brand.

**Why this priority**: It is the requested distribution channel and makes the capability usable without writing code, but it re-uses the same underlying workflow as P1, so it is only valuable once P1 works.

**Independent Test**: Connect a compatible AI chat client to the server, list the offered capabilities, invoke the product lookup, and confirm the returned product data matches the catalogue.

**Acceptance Scenarios**:

1. **Given** the server is running locally, **When** a chat client connects, **Then** it can discover every published capability (campaign creation, product lookup, image generation, script generation, slide rendering, slide regeneration, image description, video transcription, project saving) and both brand documents.
2. **Given** a connected chat client, **When** the user asks it to describe one of the input images, **Then** a written description of that image is returned in the conversation.
3. **Given** a connected chat client, **When** the user asks for a full campaign on a topic, **Then** the same output project folder is produced as in User Story 1.

---

### User Story 3 - Revise one slide after review (Priority: P3)

After reviewing a generated campaign, the user is unhappy with a single slide. They ask for that slide to be redone with a comment such as "make the headline shorter and the background lighter", and only that slide is replaced.

**Why this priority**: A quality-of-life refinement. The campaign is already usable without it, since the whole campaign can simply be regenerated.

**Independent Test**: Generate a campaign, request a revision of slide 3 with a written comment, and confirm slide 3 changes while the other slides are untouched.

**Acceptance Scenarios**:

1. **Given** a saved campaign project, **When** the user requests a revision of one slide with a comment, **Then** that slide is regenerated to reflect the comment and the remaining slides are unchanged.

---

### Edge Cases

- The input folder contains no images, or no topic brief: the system reports what is missing instead of generating an empty campaign.
- A SKU named in the topic brief is not in the catalogue: the system reports which SKUs were not found and continues with the ones it did find.
- The topic brief names no SKU at all: the campaign is generated from the brief and images alone, without product data.
- An image or slide fails to generate: the system reports which slide failed and keeps the slides that succeeded rather than discarding the run.
- A supplied video has no audio track: visual description still proceeds and the campaign notes that no spoken content was available.
- Two campaigns are generated on the same topic: each run lands in its own project folder and never overwrites the previous one.
- Overlay text is too long for the safe area defined by the design guidelines: the system shortens or reflows it rather than letting it fall outside the readable zone.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a topic brief, a set of input images and/or video, and a desired slide count as the inputs to a campaign.
- **FR-001a**: System MUST identify the product SKUs named inside the topic brief and use them as the lookup keys for the product catalogue, without requiring the user to list the SKUs separately.
- **FR-002**: System MUST read input media and the topic brief from the input content folder and write all results to the output content folder.
- **FR-003**: System MUST produce a written description of each supplied image for use as context when writing the campaign script.
- **FR-004**: System MUST produce a combined description of a supplied video, covering both what is shown across the video and what is spoken in it.
- **FR-004a**: System MUST sample between 5 and 10 frames from a video, spread across its full duration rather than clustered at the start, and MUST NOT exceed 10 regardless of clip length.
- **FR-005**: System MUST look up each SKU taken from the topic brief in the product catalogue and return, for each match, a shortened product name, description, image reference, price and product page URL.
- **FR-006a2**: System MUST deliver exactly the requested number of slides, enforcing it rather than relying on the script model to honour the request.
- **FR-006**: System MUST generate a campaign script that assigns each slide a background-image prompt, the overlay text for that slide, and notes on Instagram interactive elements to add at posting time.
- **FR-006a**: The campaign script MUST record the product page URL so the person posting the story can attach it as the link sticker.
- **FR-007**: The generated script MUST follow the project's story-telling rules, including the ordered narrative structure (hook through call to action) and the supported story length.
- **FR-008**: System MUST generate a background image for each slide from that slide's prompt.
- **FR-008b**: When a slide features the product, System MUST supply the user's own product photograph to image generation and reproduce that exact container, rather than letting the image model invent packaging, branding or label artwork.
- **FR-008c**: System MUST identify which supplied photographs show the product, and MUST pass them only to slides that feature it.
- **FR-008d**: When generating product photography, System MUST skip any product whose image cannot be obtained, reporting it with the reason, rather than generating frames that would carry invented packaging. If no named product has an obtainable image, the run MUST fail rather than produce a set.
- **FR-008a**: The product page URL MUST NOT be passed to image generation or rendered onto any slide; it exists only as script metadata for the human posting the story.
- **FR-009**: System MUST render each finished slide by laying the copy out over its background image as a styled document and capturing the result, respecting the project's design guidelines for canvas size, safe zones and typography.
- **FR-008f**: Image prompts MUST describe the scene only — setting, action, light, framing and exclusions — and MUST NOT describe the appearance of the dog, the person or the product. Their appearance MUST come from real photographs attached to the generation, because a subject described in words is reinvented differently in every image.
- **FR-008h**: The catalogue photograph of a SKU MUST take precedence over any other image of that product. A frame extracted from a supplied video MUST be used as a product reference only when the SKU has no catalogue photograph.
- **FR-008i**: When an image shows several products, System MUST attach a photograph of each of them, so the model reproduces every label rather than inventing the ones it was not given.
- **FR-008g**: System MUST attach a real photograph of each subject appearing in an image, drawing on the supplied photos and on the frames already sampled from a supplied video.
- **FR-008e**: When more than one image in a set shows a person, System MUST show the same person throughout: it MUST describe one person for the set and apply that description to every image featuring a human, and MUST NOT place a second person in any single image.
- **FR-009a**: Slide layout MUST be composed with sight of the background image, so copy is placed around the subject rather than at a fixed position, and MUST NOT cover the animal's face or the product.
- **FR-009b**: System MUST verify each rendered slide against the design guidelines and against the copy it was meant to display, recording a pass/fail verdict with specific issues for every slide.
- **FR-009c**: When a slide fails verification, System MUST attempt to re-lay it out using the reported issues as feedback, and MUST keep and report the best attempt rather than discarding the slide.
- **FR-010**: System MUST generate slides concurrently so that a multi-slide campaign is not produced strictly one slide at a time.
- **FR-011**: System MUST save every campaign into its own folder named from the topic plus a date-and-time suffix, containing the rendered slides and the campaign script.
- **FR-011a**: When a video is supplied, System MUST keep the frames sampled from it and the transcript of its audio in the campaign folder, so what the script was written from can be read back afterwards.
- **FR-012**: Users MUST be able to regenerate an individual slide from a written comment without affecting the other slides in the campaign.
- **FR-013**: System MUST publish its capabilities to AI chat clients over a locally run interface, exposing the campaign, product, image-generation, script-generation, slide-rendering, slide-revision, image-description, video-transcription and project-saving operations as callable tools.
- **FR-014**: System MUST publish the story design guidelines and the story-telling rules as readable resources to connected chat clients.
- **FR-015**: System MUST provide a programmatic entry point so the campaign workflow can be run locally from a script, without an AI chat.
- **FR-016**: System MUST report which step failed, and for which slide, when any stage of the workflow does not complete.
- **FR-017**: Rendered slides MUST be saved in a standard image format suitable for direct upload to Instagram Stories.

### Key Entities

- **Campaign**: One story-telling run. Holds the topic brief, the referenced products, the slide count, the generated script and the resulting slides; identified by its topic and creation timestamp.
- **Slide**: One story frame. Holds its position in the sequence, its narrative job (hook, tension, solution, proof, offer, call to action), its background-image prompt, its overlay text, its Instagram element notes, and the rendered image.
- **Product**: A catalogue entry. Holds a shortened name, description, image reference, price and product page URL, looked up by the SKU named in the topic brief.
- **Input Media**: An image or video supplied by the user, together with the written description derived from it.
- **Brand Rules**: The two normative documents — design guidelines (how a slide looks) and story-telling rules (what it says and in what order) — used as context during script writing and slide rendering.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from dropping images and a topic brief into the input folder to a complete, saved campaign in a single command with no manual steps in between.
- **SC-002**: A 5-slide campaign completes in under 5 minutes on a typical laptop.
- **SC-003**: 100% of generated campaigns produce the requested number of slides, or a clear report naming the slides that failed.
- **SC-004**: 100% of rendered slides keep their overlay text inside the safe content band defined by the design guidelines.
- **SC-004a**: Every rendered slide carries a recorded verification verdict, and any slide that fails names the specific problems found.
- **SC-005**: Every generated campaign script covers the mandated narrative beats in order, ending with a single call to action.
- **SC-005a**: The product page URL appears in every generated script and in none of the generated slide images.
- **SC-005a2**: Across one campaign or lifestyle set, every image showing a person shows the same person, and no image shows two.
- **SC-005b**: On every slide showing the product, the container matches the supplied photograph — same shape, colour and label artwork — with no invented brand name or logo.
- **SC-005c**: A campaign contains exactly the number of slides requested.
- **SC-006**: A connected AI chat client can discover and successfully call every published capability without additional configuration beyond starting the server.
- **SC-007**: Revising one slide leaves the other slides in the campaign byte-for-byte unchanged.

## Assumptions

- Simplicity is an explicit constraint: the implementation stays as small as it can be while meeting these requirements, favouring a thin workflow over configurable frameworks, plugin layers or abstractions added for anticipated future needs.
- All input media lives on the same machine as the application; no upload, download or remote storage is in scope for this version.
- The product catalogue is a static file shipped with the application; catalogue editing, syncing and product management are out of scope.
- Product SKUs are supplied inline in the topic brief rather than as a separate argument, in the form used by the catalogue (for example `BO-FIU150`). Naming a SKU is optional: a brief with none still produces a campaign, and product data enriches the script when a SKU is present.
- Supplying video is optional; the sample workflow runs on images only.
- Supported story length follows the story-telling rules already in the repository: three slides minimum, seven maximum.
- The system produces slide images and a script. It does not post to Instagram, and the Instagram interactive elements (stickers, polls, link) are recorded as notes for a human to apply at posting time.
- Slide layout is composed as a styled document and captured as an image, which is what allows the copy to be positioned around the subject and the brand typefaces to be used directly.
- Output is a static image per slide; animation, video export and audio in the output are out of scope.
- Copy is generated in the language of the topic brief.
- Verification is advisory: a slide that cannot be made to pass is still delivered, flagged, so a human decides rather than the run failing.
- A single user runs the application locally; no authentication, multi-tenancy or concurrent-user handling is required.
- Credentials for the external generation services are supplied through local environment configuration.
