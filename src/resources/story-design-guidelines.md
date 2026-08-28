# HealthyDoggo — Instagram Story Design System

**Version:** 1.0 · **Date:** 2026-08-27
**Sources:** HealthyDoggo brandbook "Дизайн гайди" (v. 04.09.25) + UX teardown of 16 approved reference stories + the `png/` decorative element library.
**Audience:** the story-telling agent (prompt author for Nano Banana), designers, and anyone producing IG Stories / Reels covers for HealthyDoggo.

This document is normative. Where a rule says **MUST**, treat it as a hard constraint and validate the rendered output against it. Where it says **SHOULD**, deviate only with a reason.

---

## 1. Canvas, grid and safe zones

| Property | Value |
|---|---|
| Artboard | **1080 × 1920 px**, 9:16, portrait |
| Working DPI | 72 (screen); always export at 1080 px width minimum |
| Export | JPG q≥88 or PNG; sRGB |
| Side margin | **72 px** minimum (6.7% of width) for any text or CTA |
| Top reserved zone | **top 250 px** — occupied by the IG progress bar, avatar and username. **MUST NOT** contain critical text |
| Bottom reserved zone | **bottom 250 px** — occupied by the reply field / "Send message" bar. **MUST NOT** contain critical text |
| Safe content band | **y = 250 … 1670 px** (1420 px tall) |
| Sticker sweet spot | y = 1150 … 1600 px — where the thumb naturally rests |

**Layout grid.** Use a 12-column grid with 72 px outer margin and 24 px gutter for alignment discipline, but the visual language is **organic, not gridded** — blobs, cards and cutouts intentionally break the grid. The grid governs text alignment and optical spacing; it does not govern illustration placement.

**Vertical rhythm.** Base unit = 8 px. All paddings, gaps and offsets are multiples of 8 (8 / 16 / 24 / 32 / 48 / 64 / 96).

**Composition zones.** Every story divides into three functional bands:

```
┌──────────────────────────┐  250px  SYSTEM (IG UI) — leave empty
├──────────────────────────┤
│  HOOK ZONE   (250–700)   │  headline, kicker, logo lockup
├──────────────────────────┤
│  SUBJECT ZONE (700–1300) │  photo subject, packshot, hero
├──────────────────────────┤
│  ACTION ZONE (1300–1670) │  body copy, price, CTA, IG sticker
├──────────────────────────┤
│          250px  SYSTEM   │  leave empty
└──────────────────────────┘
```
One zone may be borrowed by its neighbour, but **all three MUST NOT be filled with dense content at once** — at least one zone stays visually quiet.

---

## 2. Brand foundations

### 2.1 Colour tokens

| Token | HEX | Role |
|---|---|---|
| `--grey` | `#616161` | Body text, neutral elements, contrast on light backgrounds |
| `--turquoise` | `#57CAAE` | **Primary accent.** Headlines, key words, buttons, **all CTAs** |
| `--mint` | `#CFECE5` | Backgrounds for posts/stories, plates under photos |
| `--light-green` | `#BFDF98` | Backgrounds, plates, label chips |
| `--beige` | `#ECE9E1` | Backgrounds, plates, neutral bands |
| `--brown` | `#5F3D09` | Text, small accents, "naturalness" cues |
| `--white` | `#FFFFFF` | Text, clean backgrounds, blobs (плями), space around product |
| `--soft-green` | `#F5FFE0` | Light accent blocks, text plates — creates "freshness" |
| `--pink` | `#FF8080` | **Secondary accent.** Promo, discounts, emotion. **Use sparingly** |

**Colour rules (MUST):**

1. **Max 1–2 brand colours per story + 1 accent.** Never more.
2. **Backgrounds / blobs → light tones only:** white, beige, light-green, mint, soft-green.
3. **Accent spots → rare and purposeful:** pink.
4. **Text on light background → grey or brown.** Text on accent/dark background → white.
5. **Key words → turquoise or pink.**
6. **Primary accent = turquoise. Secondary accent = pink** (discounts / emotion).
7. **CTA is ALWAYS turquoise** — the only exception is the promo/discount pattern where the whole story is pink-led (see §7.7); even then a turquoise button is preferred where a real button exists.
8. No colours outside this palette. Product packaging colours are the only exception (see rule 9).
9. **Echo rule.** A headline MAY adopt a tint sampled from the product packaging when it is close to a brand token (e.g. lime-yellow headline over the yellow *Wrinkle Wipes* jar → use `--light-green` / `--soft-green`, not the raw sampled colour). Snap to the nearest brand token; never introduce a foreign hue.

**Approved background + text pairs:**

| Background | Text |
|---|---|
| White `#FFFFFF` | grey `#616161` or brown `#5F3D09` |
| Beige `#ECE9E1` | brown `#5F3D09` |
| Soft-green `#F5FFE0` / mint `#CFECE5` | grey `#616161` or brown `#5F3D09` |
| Pink spot `#FF8080` | white `#FFFFFF` |
| Turquoise `#57CAAE` | white `#FFFFFF` |

**Forbidden (MUST NOT):**
- busy multi-coloured backgrounds;
- white text on a light background with no contrast;
- grey text on a dark or pink background.

### 2.2 Typography

| Role | Font | Weights |
|---|---|---|
| Headings H1/H2, key messages, important accents | **Bitter** (serif) | Medium, Bold, **ExtraBold** |
| Descriptions, captions, body copy | **Noto Sans** | Regular, **Semibold** |

**MUST:** only this pair. Never mix in a third typeface. Never substitute system fonts.

**Type scale (1080 × 1920 canvas):**

| Level | Font / weight | Size | Line-height | Tracking | Case |
|---|---|---|---|---|---|
| Display / hero headline | Bitter ExtraBold | 96–120 px | 1.02–1.08 | −1% | UPPERCASE |
| H1 headline | Bitter ExtraBold | 72–90 px | 1.08 | −1% | UPPERCASE |
| H2 / section heading | Bitter Bold | 56–68 px | 1.12 | 0 | UPPERCASE |
| Kicker / eyebrow | Bitter Bold | 40–48 px | 1.1 | +2% | UPPERCASE |
| Lead / subheadline | Noto Sans Semibold | 40–48 px | 1.28 | 0 | Sentence case |
| Body | Noto Sans Regular | 34–40 px | 1.38 | 0 | Sentence case |
| Caption / label chip | Noto Sans Regular–Semibold | 28–34 px | 1.3 | 0 | Sentence case |
| Micro-CTA / legal | Noto Sans Regular | 24–28 px | 1.3 | 0 | lowercase |

**Typography rules:**

- **Max 3 type sizes per story.** Four is already noise.
- **Max 7 words per headline line**; max **3 lines** per headline.
- **Total on-canvas word count target: 15–45 words.** Above ~60 words the story fails at thumb speed — split into two stories.
- **Headline case:** UPPERCASE for Bitter headings. Body copy is never all-caps.
- **Inline emphasis in body copy:** switch the emphasised word to **Noto Sans Semibold**, or recolour it turquoise / pink / light-green. Never underline, never italicise.
- **Two-colour headline:** a headline may split into a neutral part + an accent part (`НАШ` brown + `БЕСТСЕЛЕР` pink). Accent carries the meaning, neutral carries the grammar.
- **Alignment:** centre-align headlines that sit over a symmetrical composition; left-align headline + body when the story is list-like or reading-heavy. Do not mix centre and left inside the same text block.
- **Orphans:** never leave a single short word alone on the last headline line — rebalance the break.

### 2.3 Logo

- Minimum size ratio from brandbook: **169 × 85 mm** proportion; on a 1080 px story never render the full lockup below **200 px wide**.
- **Safe zone:** clear space around the lockup equal to the height of the `DOGGO` cap-height on all four sides. Nothing may enter it.
- **Allowed lockups:** `B2B HEALTHY / DOGGO`, `healthy / DOGGO` (stacked), `HEALTHY DOGGO` (inline). Full colour (turquoise `healthy` + dark `DOGGO`) or single-colour knockout (all-white on photo).
- **Forbidden:** grey/washed-out versions, italic/skewed versions, recolouring the mark, altering letter spacing, placing on a busy photo area without a plate.
- **When to include the logo:** first slide of a sequence, collab/partner slides, promo/campaign covers, Reels covers. Do **not** stamp the logo on every slide of a sequence — it steals attention from the product. Branding is carried by colour + type + paw elements, not by logo repetition.
- On photos, place the logo on a white rounded plate or use the all-white knockout over a dark region.

---

## 3. Photography rules

From the brandbook plus observed practice:

1. **Product or animal is the focal point.** One hero subject per story.
2. Photo is **clean, bright, no distracting objects** in the background.
3. Photo occupies **≈70% of the composition**.
4. **Round the corners** of any framed photo: 32–48 px radius. Full-bleed photos have no radius.
5. **Never place a photo on a busy/multicoloured background.**
6. **Never cover the product with text or elements.** Text goes into negative space (sky, wall, blurred floor, bokeh).
7. Product cutouts (transparent PNG) are preferred for composed slides; keep a soft, low-opacity drop shadow or none at all — never a hard black shadow.

**Legibility treatments (choose one, never two):**

| Treatment | When |
|---|---|
| Text in natural negative space | Photo already has a clean, low-detail area |
| Linear gradient scrim, black 0 → 55%, over bottom 35% | Full-bleed photo, text at the bottom |
| Rounded plate (white / beige / mint / pink), 24–32 px radius, 32–40 px padding | Photo is busy everywhere |
| Text stroke: 6–10 px outline in white (for pink/brown text) or in `--brown` (for white text) | Headline must sit over mid-tone photo |
| Blur the photo (Gaussian 20–40 px) and use it as backdrop, with the sharp version as a card on top | UGC photo, quiz/poll slides |

**UGC / low-quality photos MUST NOT be full-bleed.** Frame them as a rounded card on a brand-colour background (see archetype §7.9).

---

## 4. Blobs (плями), plates and containers

The organic white/coloured blob is HealthyDoggo's signature shape. Rules:

- **Shape:** irregular, 5–8 lobes, no straight edges, no perfect circles. Reuse the blob shapes from the brandbook "Плями" sheet or the Figma element library.
- **Roles:** (a) background plate under a photo; (b) text plate; (c) full-bleed section band; (d) decorative spot behind a step number.
- **Fill:** white, beige, mint, light-green, soft-green. Pink blobs only for promo/price/emotion.
- **Text padding inside a blob:** ≥ 40 px on all sides; ≥ 56 px on the lobed sides.
- **Never** put a blob over the product's face/label.
- **Bleed:** blobs and coloured bands SHOULD bleed off at least one canvas edge — it makes the composition feel continuous rather than boxed.

**Rounded containers (the geometric counterpart to blobs):**

| Component | Radius | Fill | Text |
|---|---|---|---|
| Pill / chip (label, kicker, tag) | fully rounded (`r = h/2`) | light-green, mint, soft-green, beige, white, pink | brown / grey / white |
| Rounded band (headline plate) | 40–64 px | turquoise, pink, beige, white | white / brown |
| Card (photo frame, product card) | 32–48 px | white, or photo | — |
| Price badge | fully rounded | pink `#FF8080` | white, Bitter Bold |
| Discount badge (corner) | 8–12 px | pink `#FF8080` | white, Noto Sans Semibold, 24 px |

**Layered lockup pattern (used repeatedly and recommended):** a small kicker pill overlapping a larger headline blob/band beneath it, offset −16…−24 px vertically and horizontally staggered. Creates depth without shadows.

---

## 5. Decorative elements

### 5.1 Quantitative rules (from brandbook, hard limits)

1. **Decorative elements occupy ≤ 30% of the composition.**
2. **No decorative element may be larger than the product.**
3. Paws, lines, waves etc. are **a light accent only** — never the subject.
4. **Max 3 distinct decorative elements per story**, max 5 instances total.
5. **Never over-graphic the slide.**

### 5.2 Qualitative rules

- **Every decorative element must do a job.** Allowed jobs: (a) direct the eye (arrows), (b) mark emphasis (emphasis strokes, circles, underlines), (c) terminate a text block (waves, vines), (d) carry meaning (icons: paw, tooth, natural).
- **Stroke weight** for hand-drawn line elements: 6–10 px on a 1080 canvas. Keep the weight consistent across all elements in one story.
- **Recolour, don't use as-is.** The library ships dark-grey/brown outlines. Recolour to a brand token appropriate to the background: white on photos, brown/grey on light plates, turquoise or pink for accent.
- **Rotation:** decorative elements may be rotated freely; text and cards rotate only within **±5°**.
- **Never place a decorative element over a face, a product label, or a CTA.**
- **Pairing:** arrows always point **at something** — a CTA, a link sticker, a product, a price. An arrow pointing at nothing is a defect.
- **Emphasis strokes** (2–4 short radiating lines) go at the **outer corner** of the thing being emphasised, never centred on it.

### 5.3 Emoji rules

Observed usage is deliberate and sparse.

- **Max 1–2 emoji per story.** Zero is acceptable and often better.
- Emoji **MUST** be semantically tied to the copy (🐶 dog topic, ✨ result/benefit, 🌱 natural, 🎁 gift, 🙏 request).
- Place emoji **inline at the end of a line** (never mid-sentence, never as a bullet), or **inside a chat-bubble element** as a reaction.
- **Never** use emoji as decoration on headlines in Bitter ExtraBold — the serif headline carries its own weight.
- Avoid emoji whose colour clashes with the palette (bright reds, purples, neon). Prefer the muted / natural set.
- Native IG sticker emoji (poll, quiz, question, link) are UI, not emoji — they're governed by §6.

---

## 6. Instagram native stickers

Reference stories use native stickers heavily and correctly. Rules:

| Sticker | Placement | Notes |
|---|---|---|
| Poll (2 options) | Lower third, y ≈ 1250–1550, left- or centre-aligned | Keep options ≤ 3 words each |
| Quiz (3–4 options) | Lower third, centred | Only one correct answer; options ≤ 3 words |
| Question box | Upper third or middle, y ≈ 380–560 | Used to *simulate* an inbound DM — see archetype §7.3 |
| Link | Upper-middle, y ≈ 420–620, centred or right | Label lowercase, 1–2 words (`замовити`, `детальніше`) |
| Countdown / date | Never more than one time element per story | |

- **MUST NOT** overlap a sticker with a face or the product label.
- **MUST NOT** place two interactive stickers on one story.
- Leave **≥ 48 px** clear space around any sticker.
- Point a hand-drawn arrow or emphasis strokes at the sticker when it is the story's single goal (link/CTA slides).
- Reserve at least the bottom 250 px empty below the sticker so it isn't crowded by the reply bar.

---

## 7. Slide archetypes

Nine reusable templates, all derived from approved stories. The agent SHOULD pick an archetype first, then fill it.

### 7.1 HOOK COVER (opens a sequence)
> *Reference: pug "ТОП-3 ПРОБЛЕМИ У СОБАК ВОСЕНИ"*

- Full-bleed photo, dark gradient scrim over bottom 35%.
- Headline in white Bitter ExtraBold uppercase, 2 lines, bottom-anchored (y ≈ 1400–1560).
- **One word of the headline sits inside a mint pill** (`ТОП-3`) — the numeric/promise token.
- Subheadline in Noto Sans Semibold white, one line, below.
- Decoration: 3 light-green emphasis strokes above the animal's head; a white wavy line above the headline and a second below the subheadline, framing the text block.
- Optional: a topic emoji inside a white circular chat bubble, placed mid-right, overlapping the photo.

### 7.2 TEXT / RULES SLIDE (no photo)
> *Reference: "А ЦУЦИКУ МОЖНА?" — 5 safety rules*

- Background: mint with a subtle tonal blob.
- Header: turquoise blob at the top, white Bitter ExtraBold centred, ≤ 2 lines.
- Sub-header: white rounded band bleeding off both edges, brown Bitter Bold uppercase, left-aligned.
- Body: **3–5 list items maximum**, each opening with a **paw-arm element bleeding in from the left edge** as the bullet.
- Each item: bold uppercase brown lead-word + regular brown body.
- Vertical gap between items: 48–64 px. Never let items touch.

### 7.3 DM ANSWER / SOCIAL PROOF
> *Reference: "Порадьте вітаміни для імунітету" → Aller-Immune vs Multivitamin*

- Background: blurred lifestyle photo.
- Top: white pill styled as an incoming question (Noto Sans, dark text, + 🙏), with small dark emphasis strokes at its top-right corner.
- Middle: white centred answer copy, key word recoloured light-green.
- Two hand-drawn curved arrows fan down-left and down-right toward the two options.
- Option names: pink Bitter ExtraBold with a white outline stroke, split left / right.
- Between them: a small pink organic blob with white `АБО`.
- Bottom: the two product cutouts side by side, bleeding off the bottom edge.

### 7.4 PRODUCT HERO / BESTSELLER
> *Reference: "НАШ БЕСТСЕЛЕР — Лососева олія"*

- Background: beige with white blobs top and bottom (no photo).
- Headline: two-colour Bitter ExtraBold uppercase — neutral word brown + key word pink.
- Product cutout centred at y ≈ 450–1000.
- One hand-drawn brown accent element beside the packshot (e.g. `Curly-Scale-Flake`).
- Product name in a pink rounded band, white Bitter uppercase, ≤ 2 lines.
- Supporting claim in brown Noto Sans below, opening with an em-dash.
- Bottom-left: a dog cutout bleeding off the corner.
- Bottom-right: a **turquoise hand-drawn ellipse** enclosing a short claim, rotated ~−6° — reads as the dog's aside.

### 7.5 BENEFIT / SINGLE PRODUCT ON PHOTO
> *Reference: "WRINKLE WIPES — серветки для складочок"*

- Full-bleed lifestyle photo with the product in-hand.
- Product name at the top in an oversized Bitter ExtraBold tinted to the packaging colour (snapped to a brand token).
- Ukrainian descriptor line directly beneath in white Bitter/Noto Semibold + one emoji.
- Benefit copy in white Noto Sans, 2–3 centred lines, in the lower third.
- One hand-drawn wave/vine element at the bottom-right as a closing flourish.

### 7.6 PRODUCT SET / BUNDLE
> *Reference: 5-product care bundle, 2190 ₴*

- Light background (white/soft-green) with one large pale blob.
- 4–6 product cutouts staggered along a **top-left → bottom-right diagonal**; alternate horizontal offsets; allow slight overlaps.
- Each product gets a **light-green rounded label chip**, 1–2 lines, brown text, adjacent to it (above or below, alternating).
- **Price badge last, bottom-right**: pink pill, white Bitter Bold, with a short turquoise hand-drawn underline stroke beneath it.
- The eye must be able to complete the diagonal without backtracking.

### 7.7 PROMO / DISCOUNT / CAMPAIGN
> *References: "БЛАГОДІЙНИЙ GARAGE SALE", "ОБИРАЙ … healthydoggo.ua/znyzhky/"*

- Full-bleed photo, top region darkened.
- Optional co-branding lockup at the very top: `[HealthyDoggo logo] × [partner logo]`, white knockout, or both logos inside one white rounded card.
- Headline: pink Bitter ExtraBold uppercase with white outline stroke, 2 lines, oversized (may bleed slightly past the margin).
- Supporting line in white Noto Sans.
- **Date / URL badge:** pink pill, white bold text.
- A pink hand-drawn arrow leads from the badge to the next action (`дивіться далі`, a URL, a product row).
- Decoration: white hand-drawn heart outlines (1–2, different sizes) + white sparkle strokes. This is the only archetype where hearts are used.
- Optional: fanned deck of white product cards at the bottom, rotated ±4°, each with a pink corner discount badge, title, new price and struck-through old price.
- Step-in-sequence variant: a mint irregular brush spot at the top-left holding the step number.

### 7.8 COMPARISON / EDUCATION
> *Reference: "Яка різниця між паличками з кавового та оливкового дерева?"*

- Blurred photo backdrop, ≥ 80% covered by shapes.
- Top: white blob panel bleeding off both sides, brown Bitter ExtraBold question, centred, ≤ 3 lines.
- Two full-width organic colour bands stacked vertically: band A `--light-green`, band B `--beige`.
- Each band: a product cutout on **alternating sides** (A left, B right), heading in brown Bitter ExtraBold with white outline, and 1–2 short body paragraphs with **bold inline keywords**.
- Never more than two compared items on one story.

### 7.9 ENGAGEMENT (poll / quiz)
> *References: "ЧИ ПОМІЧАЄШ ОЗНАКИ СТАРІННЯ…", "ЗНАЄШ ЩО НА ФОТО?", "ЯК ДОПОМАГАЄШ СВОЇЙ СОБАЦІ?"*

Three sub-variants:

- **9a — Photo-led.** Full-bleed portrait; headline in pink Bitter ExtraBold with white outline, top-left, 2–3 lines, placed in the photo's negative space; pink emphasis strokes at the corner; native poll sticker in the lower third, aligned away from the subject's face.
- **9b — Card-on-blur.** Blurred version of the same photo as the backdrop; the sharp photo as a rounded card rotated −4°, with an offset white rounded rectangle behind it (stacked-card depth); below it, a layered lockup — small soft-green kicker pill (`ЗНАЄШ`) overlapping a large brown outlined headline (`ЩО НА ФОТО?`); quiz sticker beneath.
- **9c — Brand-background.** Mint background with a pale blob; UGC photo as a rounded card rotated +2° filling the top ~65%; a turquoise rounded band overlapping the card's bottom edge carrying a white Bitter ExtraBold question; sticker below, overlapping the band.

**Additional archetype — COLLAGE / MOSAIC** *(reference: soap-bar collage)*: an asymmetric tile grid — 3 small tiles across the top, 2 down the left, one dominant hero tile occupying the bottom-right ~55%. Zero or minimal gutter. **All overlay text lives on the hero tile only:** white Noto Sans copy top-left, two white paw icons as a divider, a light-green label chip bottom-right with a brown hand-drawn arrow hooking from the product down to the chip.

---

## 8. Story sequence (narrative) rules

A story-telling set is **3–7 slides**. Recommended arc:

1. **Hook** (§7.1) — problem, promise or question. Must be readable in 1 second.
2. **Context / agitation** — why it matters. Often §7.2 or §7.8.
3. **Solution** — the product (§7.4 / §7.5).
4. **Proof** — comparison, UGC, DM screenshot (§7.3 / §7.8 / collage).
5. **Offer** — set, price, discount (§7.6 / §7.7).
6. **CTA** — one action only, link sticker (§7.7 minimal variant).

Rules:
- **One idea per slide.** If a slide needs two headlines, it's two slides.
- **One CTA per sequence**, on the last slide. Intermediate slides may carry "дивіться далі" micro-cues.
- **Vary the archetypes** — never three consecutive full-bleed photo slides or three consecutive text slides. Alternate photo-led ↔ brand-background.
- **Keep colour continuity:** pick one accent for the whole sequence (turquoise for educational, pink for promo) and hold it.
- Number multi-step sequences with a brush-spot step indicator at the top-left when the order matters.

---

## 9. Decorative element library reference

Location: `png/` (194 transparent PNGs, mostly 413 × 413, RGBA). Delivered as dark-grey / brown outline art — **recolour before use**.

### 9.1 Arrows — attention direction

Two visual families; **do not mix them in one story**.

- **Thin sketch family** (uniform ~4 px stroke, technical/neat): `Arrow-Angled`, `Arrow-Angled-Line`, `Arrow-Angled-Dashed-`, `Arrow-Straight-Diagonal`, `Arrow-Straight-Dashed-Curvy-Head-Long-8`, `Arrow-Spiral-Down`, `Arrow-Spiral-Down-2`, `Arrow-Spiral-Up`, `Arrow-Double-Head-Spiral`, `Arrow-Wiggle-Up`, `Arrow-Wiggle-Down`, `Arrow-Wiggle-Left-Curve-3`, `Arrow-Hand`, `Arrow-Hand-Zigzag`, `Arrow-Thick`, `Arrow-Thick-4`, `Arrow-Thick-5`, `Arrow-Thick-Curve`, `Arrow-Thick-Ribbon`, `Arrow-Thick-Zigzag-1`.
- **Bold brush family** (`arrow 1` … `arrow 17`, tapered marker stroke, energetic): use for promo, CTA and emotional slides. `arrow 1`, `arrow 8`, `arrow 11` = curled hook; `arrow 3`, `arrow 16` = long sweeping curve; `arrow 4` = vertical up; `arrow 9`, `arrow 14` = U-turn / redirect; `arrow 12`, `arrow 13` = zigzag energy; `arrow 5`, `arrow 15` = angular elbow.

**Usage:** exactly **one arrow per slide** in the vast majority of cases (two only in the fan-out comparison of §7.3). The arrow must terminate within 80 px of its target.

### 9.2 Emphasis, highlight and annotation

| File(s) | Use |
|---|---|
| `Highlight`, `Highlight-Bling`, `Highlight-Star-Sparkle`, `Highlight-Ribbon-Line` | Radiating emphasis strokes — place at the outer corner of a headline, sticker or subject's head |
| `Line-Highlight-Eclipse--…`, `Line-Highlight-Eclipse-Cross-2--…` | Hand-drawn ellipse circling a claim (see §7.4) |
| `Line-Highlight-Scribble-Rectangle-1/-2--…` | Hand-drawn box around a word or price |
| `Line-Highlight-Scribble-Underline-4/-6--…`, `Line-Highlight-Hatch-Underline-3--…`, `Line-Highlight-Ellipse-Hatch-Underline-3--…`, `Line-Highlight-Double-Underline-2--…` | Underline a key word or a price badge (turquoise underline under a pink price is the house pattern) |
| `Annoation-Brackets-Square-Left`, `Brackets-Square-Right`, `Line-Braces-Curly-Left`, `Braces-Curly-Right`, `Line-Parentheses-Round-Left/-Right`, `Summarize-Bracket-4` | Bracket a group of items; always use as a matched left/right pair |
| `Censorship-Horizontal`, `-4`, `-5`, `Censorship-Vertical-1` | Hatched bars — redaction / "before" masking. Rare |
| `Rectangle-Top/-Bottom/-Left-1-Non-Filled-Line` | Hatched-edge frames for callouts |

### 9.3 Speech and thought bubbles

`Chat-Bubble-*` — 19 variants across four shapes (Circle / Oval / Horizontal / Square / Vertical / Arrow-Point) × three edge treatments (**Shadow** = hatched offset edge, **Dash** = dashed outline, **Plain**) and two sizes (regular / Small).

**Use for:** hosting an emoji reaction, a customer quote, a dog's "thought", a short interjection.
**Rules:** one bubble per slide; the tail must point at the speaker; recolour the fill to white or a light brand token; text inside is Noto Sans, ≤ 8 words. `-Thought-` variants (with trailing dots) are for the dog's inner monologue only.

### 9.4 Sparkles, stars and energy

`Star-Wink`, `Star-Wink-1`, `Star-Wink-Sparkle-Filled`, `Stars-Plus-Wink`, `Winks-Plus`, `Pop-Sparkle`, `Diamond-Sparkle-Filled`, `Explode-Sparkle-Filled`, `Flash-Sparkle`, `Crown`, `Rainbow`.

Use for "result / after / wow" moments. **Max 2 sparkle elements per slide.** Never on educational or medical-claim slides — sparkle undermines credibility.

### 9.5 Waves, vines and dividers

`Wave-Curly`, `Wave-Curly-Line-2`, `Line-Wavy-1`, `Line-Wavy-2`, `Ribbon-Vine`, `Ribbon-Vine-Line-1-`, `Abstract-Ribbon-Vine-Line-3`, `Sprinkle-Curly-Line-1`, `Sprinkle-Curly-Line-2`, `Spring-Curly-Twist`, `Wind`, `Wind-Spiral-Line-2`, `Curly-Scale-Flake`, `Abstract--Streamline`, `Streamline`, `Triangle--Streamline`, `Line-Octagon`, `Line-Asterisk`.

Use as **terminators**: close a text block, sit beside a packshot, or frame a headline top-and-bottom. Keep them ≤ 220 px wide. `Curly-Scale-Flake` is the house "burst beside the bottle" accent.

### 9.6 Reaction and semantic icons

`Line-Heart`, `Line-Heart-Shadow`, `Line-Like-Thumb-Up`, `Line-Hand-Ok`, `Line-Hand-Ok-1--…`, `Lines-High-Five`, `Line-Smiley-Happy--…`, `Lines-Smiley-Laugh-1--…`, `Lines-Smiley-Surprise`, `Line-Alert-Surprise--…`, `Line-Check-Circle`, `Line-Cross-Circle--…`, `Line-Eye-Shadow`, `Line-Idea-Lightbulb--…`, `Line-Idea-Lightbulb-Dark`, `Line-Perfect-Score-10--…`, `Line-Star`, `Line-Star-Shadow--…`, `Line-Bubble-Point`, `Lines-Pin`, `Lines-Pin-Circle--…`, `Lines-Mail-Inbox-Open`, `Lines-External-Link`, `Lines-Divide`, `Lines-Coin-Dollar`, `Lines-Note-Dollar--…`, `Increase-Up`, `Decrease-Up`, `Date`, `Time`, `Group` (brown scissors — grooming), `Bullet`, `Bullet-Point-Right`, `Bullet-Two-Way`, `Bullet-Two-Way-1`, `ullet-Point-Spiral`.

**`Line-Check-Circle` (turquoise) + `Line-Cross-Circle` (pink)** is the standard correct/incorrect pair for "do / don't" slides.

### 9.7 Paw elements — the brand signature

| File | Description | Use |
|---|---|---|
| `Paws mini 1 - filled` | Large solid paw, 4 toes + pad | Divider, watermark accent, list bullet |
| `Paws mini 2 - filled` | Small solid paw | Secondary/scatter accent |
| `Paws mini 3 - with heart` | Solid paw with heart-shaped pad | Emotional slides, loyalty, thank-you |
| `Paws mini 4 - with hear` | Outline heart enclosing a paw | Same, lighter weight |
| `Paws mini 5 - non filled` | Outline paw | Light accent on busy backgrounds |
| `paw - {brown, aquamarine, green, grey, pink, light yellow, white, white-gray, broun-filled} - {filled, non filled}` | **Paw-arm / leg elements** (845 × 2518 px tall) — a paw at the end of a long limb, already in brand colours | The house bullet and edge element: let the limb **bleed in from the canvas edge** (left, right or top) with only the paw and part of the limb visible. Pink and turquoise limbs work as a decorative "row of paws" band |
| `ukr brand` | Circular "UKRAINIAN BRAND" badge, blue/yellow heart-handshake | Trust badge, bottom corner, ≤ 140 px. Do not recolour |

**Paw usage rules:** paws are an accent, not wallpaper. Max **4 paw instances** per story, or one paw-arm bullet per list item. Scattered paw trails are allowed as a background texture only at ≤ 15% opacity.

### 9.8 Product-category pictograms

Brown/grey line icons, mostly on a circular white plate — use for benefit grids, ingredient callouts and "how to use" steps.

| File | Meaning |
|---|---|
| `bath`, `shower`, `shower-1`, `shower 2`, `foam`, `soup` (sponge), `towel`, `brush`, `whip`, `cream`, `toothpaste`, `spray` | Grooming & bath category |
| `dentic`, `dentic_w` | Dental care / teeth cleaning |
| `eat` | Feeding bowl / food |
| `lacto`, `micro`, `natural`, `natural_paw`, `Ca` | Ingredient & composition claims (probiotics, microbiome, natural, calcium) |
| `medical_paw`, `happy`, `time1`, `Time`, `Date` | Health, mood, duration, schedule |
| `no`, `no coffee` | Free-from claims (grain-free, caffeine-free) — crossed-circle style |
| `box_paw`, `truck_paw` | Packaging and delivery |
| `water`, `water2` | Hydration / moisture |

**Rules:** use **3–6 pictograms max** in one grid, all at the same size and stroke weight, all in the same colour (brown on light, white on accent). Label each with ≤ 3 words in Noto Sans 28–32 px. Never mix pictograms with sketchy decorative elements on the same slide.

---

## 10. Do / Don't checklist

### Do
- One idea, one focal point, one CTA per slide.
- Keep the product unobstructed and dominant.
- Use 1–2 brand colours + one accent.
- Bleed shapes off at least one edge.
- Give text blocks generous padding inside plates.
- Point arrows at real targets.
- Round photo corners (32–48 px) on framed photos.
- Alternate archetypes across a sequence.
- Keep everything critical inside y = 250…1670.

### Don't
- ❌ Photo on a busy multicoloured background.
- ❌ Fonts other than Bitter + Noto Sans.
- ❌ Too much graphic — decoration above 30% of the composition.
- ❌ Cover the product with text or elements.
- ❌ Overload with text (> ~60 words on canvas).
- ❌ White text on a light background; grey text on dark or pink.
- ❌ More than one interactive IG sticker per story.
- ❌ Two decorative element families (thin sketch + bold brush) in one story.
- ❌ Emoji as bullets, or more than two emoji per story.
- ❌ Logo stamped on every slide of a sequence.
- ❌ Hard drop shadows, gradients other than the legibility scrim, or 3D effects.
- ❌ Rotating text or cards beyond ±5°.

---

## 11. QA checklist (run before export)

1. Canvas is exactly 1080 × 1920.
2. Nothing critical in the top or bottom 250 px.
3. Side margins ≥ 72 px on all text.
4. Fonts: Bitter (headings) + Noto Sans (body) only.
5. ≤ 3 type sizes; headline ≤ 3 lines; ≤ ~60 words total.
6. Palette: only brand tokens; ≤ 2 colours + 1 accent.
7. Text/background contrast passes an approved pair from §2.1.
8. CTA (if present) is turquoise; exactly one CTA.
9. Decoration ≤ 30% of the area; ≤ 3 distinct elements; no element larger than the product.
10. No element covers a face, a product label, or a CTA.
11. Every arrow points at a real target.
12. ≤ 2 emoji; ≤ 1 interactive sticker; ≥ 48 px clearance around the sticker.
13. Product is the largest and sharpest thing on the slide.
14. Logo (if present) has its safe zone clear and is in an approved lockup.
15. The slide reads in ≤ 2 seconds at thumbnail size — squint-test it.

---

## 12. Prompting notes for image generation (Nano Banana)

When generating or editing a story image, encode the rules explicitly rather than relying on style words:

- State the canvas: *"vertical 9:16 poster, 1080×1920"*.
- Name exact HEX values for every colour used.
- Name the fonts and weights, and specify **uppercase** for Bitter headings.
- Describe layout by **zone**: what sits in the hook zone, subject zone, action zone.
- Describe the shapes explicitly: *"irregular organic white blob with 6 soft lobes, bleeding off the left edge"* — not "a shape".
- Give the decorative elements by **role and count**: *"one hand-drawn turquoise curved arrow, 8 px stroke, pointing from the price badge down to the link sticker"*.
- Always include a negative constraint list: *"no additional text, no extra graphics, no drop shadows, no gradients, do not cover the product"*.
- Prefer **compositing over generation** for logos, product packshots and library elements — generate the background/scene, then place the real PNG assets. Never let the model redraw the logo or product packaging.
- **Verification pass:** after generation, check the output against §11 and issue a corrective edit naming the specific violated rule.

