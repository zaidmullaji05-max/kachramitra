# 06 — Frontend (plain HTML/CSS/JS + Leaflet)

## 1. Why no framework

The whole app is four screens and one API. A React/Vite build would add a toolchain, a
lockfile, a dev server, a build step, and a `node_modules` directory — for a student project
that has to run on a lab PC and deploy on a free tier.

Plain files mean:

- **zero build**: edit `frontend/app.js`, refresh
- **zero install**: the backend serves `frontend/` at `/app`
- **easy to read**: one HTML file, one CSS file, one JS file
- **no supply chain** beyond Leaflet (one CDN script)

If the project grows past ~2 000 lines of JS, move to Vite + React. Until then this is
the honest choice.

```
frontend/
├─ index.html   4 tabs, lens stage + result sheet, ARIA labels
├─ styles.css   design tokens, dark lens stage, bottom sheet, floating nav, map
└─ app.js       state, API calls, i18n, Leaflet, rendering (~1 050 lines)
```

## 2. Run it

The backend mounts the folder automatically if it exists at import time:

```powershell
uvicorn backend.app.main:app --reload --port 8000
# app:  http://127.0.0.1:8000/app/
```

> The mount is evaluated **once** when the module is imported. If you create `frontend/`
> while the server is running, restart uvicorn.

### Pointing at another API

Served from the same origin, `app.js` uses `location.origin`. If you host the frontend
separately (GitHub Pages, Netlify), set the API base once in the browser console:

```js
localStorage.setItem("waste.apiBase", "https://your-backend.onrender.com");
location.reload();
```

`waste.apiBase` is read at boot. CORS is controlled by `ALLOW_ORIGINS` on the backend.

## 3. The four tabs

### Scan

The scan tab is built as a camera-style **lens stage**, not a form:

- full-bleed dark stage with a viewfinder frame, animated scan line, corner brackets and
  an "AI scan" pill; the empty state has a pulsing recycle orb and one-line instructions
- shutter, gallery and camera controls float over the stage; the shutter stays disabled
  until a photo is chosen
- the selected photo replaces the empty state (`object-fit: contain`) with a remove button
  in the top-right corner
- a Google-style description bar under the stage takes an optional text hint, plus a
  collapsible barcode field that scrolls itself clear of the tab bar when opened
- the result arrives in a bottom sheet with a drag handle: item + category badge,
  confidence ring, hazard warnings, colour-coded bin card, numbered steps, "avoid" list,
  rule chips, and (when uncertain) the alternative top-2 item
- tapping the sheet handle collapses it to just the item, category and confidence
- actions: find a drop-off (pre-fills the map category), ask in chat (pre-fills a question
  with the scan as context), scan another
- feedback: 👍 sends the prediction back as correct; 👎 opens an item picker built from
  `/taxonomy` so the correction is a real item id, not free text
- layout: one column on phones; at ≥980 px the stage is a sticky left column and the
  result sheet scrolls in the right column

### Chat

- the card is sized to the viewport with an internal message scroller, so the composer
  always sits above the floating tab bar instead of sliding under it
- message list with the bot's markdown-lite rendering (bold, bullets, numbered steps)
- hazard warnings rendered as red blocks under the answer — they come from the server
- sources as links, and a collapsible "How I answered" showing `tool_trace`
- facilities returned by the agent are shown as cards with a Google Maps directions link
- suggestion chips for the four questions people actually ask; the chip is translated and
  the *question it sends* is translated too (EN / HI / MR)
- attach a photo: sent as `image_base64` so the agent can call `classify_image`
- "New chat" resets the session (`POST /chat/reset`)

### Map

- Leaflet + OpenStreetMap tiles, no key
- category selector, "use my location", distance-sorted list under the map
- marker popups with address, hours and directions
- **honesty note**: when the API returns `source: "fixture"` the UI shows a yellow
  "sample data" banner; when `stale` it says results are cached. A blank map never looks
  like "there is no e-waste in your city" — the helpline text appears instead.

### Impact

- lifetime scan count, eco points, number of categories
- horizontal bars per category
- recent scans with localized item names and timestamps
- explicit copy: images are not stored, only item + category

## 4. i18n

Three dictionaries (`en`, `hi`, `mr`) in `app.js`, one `data-i18n` attribute per static
string. The choice is stored in `localStorage.waste.lang` and sent as `lang` on every
`/classify` and `/chat` call.

What is translated:

- every UI label, button, error, empty state and category name
- item **names** (via `/taxonomy`, re-rendered when the language changes)
- hazard warnings and chat answers (server-side, in the requested language when available)

What is **not** translated yet:

- disposal step text from `label_map.yaml` is English only
- the fixture facility names/addresses are English
- server messages that come from a third party (OSM tags, barcode product names)

The result card says so explicitly when the language is Hindi or Marathi:
*"Disposal steps are shown in English; ask in the Chat tab for a translation."*
That is better than silently shipping half-translated instructions, and it gives a clear
next task for anyone extending the project (add `steps_hi` / `steps_mr` to the YAML).

## 5. Accessibility and mobile behaviour

- semantic landmarks (`header`, `main`, `nav`), one `h1` per tab
- every icon-only button has `aria-label`; language buttons use `aria-pressed`
- form inputs have labels (some visually hidden) and visible focus rings
- `aria-live` on the result and chat areas, `role="alert"` on errors
- colour is never the only signal: hazard blocks also say "⛔" / "⚠️"
- bottom tab bar respects `env(safe-area-inset-bottom)` on iOS
- `prefers-reduced-motion` disables the fade/transition animations
- tap targets are ≥ 40 px

## 6. State (and what is deliberately not stored)

In memory: current file, last result, chat session id, map instance, taxonomy cache.

In `localStorage`: language, device id, chat session id. **No images, no chat transcripts,
no location history.**

The device id is a random string used only to group `/history` rows. There is no login,
no cookie, no analytics, no third-party font or script except Leaflet and OSM tiles.

The server stores no image bytes by default. If the operator enables
`IMAGE_STORAGE=true` + `CLOUDINARY_URL`, the backend uploads the sanitized JPEG and
`/history` returns an `image_url`, which the Impact tab renders as a 44 px thumbnail.
The subtitle switches from "stored without images" to the Cloudinary wording in all
three languages, driven by the `image_storage` flag in `/history`.

## 6.1 Deployment config (`frontend/config.js`)

The frontend has no build step, so the API location is a plain file:

```js
window.WASTE_API_BASE = "https://kachra-mitra-api.onrender.com";
```

Leave it empty for local use at `http://127.0.0.1:8000/app/`. A per-browser override
(`localStorage.waste.apiBase`) still wins for experiments. `vercel.json` serves this
folder, and `render.yaml` deploys the API — see `docs/11-deploy.md`.

## 7. Manual test checklist

Run this before a demo (it takes ~5 minutes):

- [ ] `/app/` loads with no console errors
- [ ] upload a photo → result card with item, category, steps, confidence
- [ ] take-photo input opens the camera on a phone
- [ ] a blurry/ambiguous photo shows the low-confidence banner and alternatives
- [ ] a battery photo (or a chat about one) shows the red battery warning
- [ ] switch to Hindi → all chrome translates, item name translates, result re-renders
- [ ] chat a rule question → answer + sources + tool trace
- [ ] "New chat" clears the conversation
- [ ] map tab: pins appear, list is distance-sorted, "sample data" banner is visible
- [ ] change category → pins and list update
- [ ] deny location → explicit demo-area message, not a blank screen
- [ ] Impact tab shows the scan you just made and the eco points
- [ ] 👍 feedback returns "thanks"; 👎 picker lists items and submits
- [ ] narrow the window to 360 px → one column, tab bar intact, nothing clipped

## 8. Known frontend limitations

| Limitation | Why | Fix |
|---|---|---|
| Leaflet + tiles need network | CDN + OSM | bundle Leaflet locally, self-host tiles |
| No offline cache | scope | service worker + cache-first for the shell |
| Location is city-level at best | browser geolocation | fine for 5 km facility search |
| Chat history is per-tab | in-memory sessions | persistence needs accounts |
| No image preview compression before upload | simplicity | canvas-resize to 1024 px client-side |
| Hindi/Marathi step text missing | data, not code | add translations to the YAML |
