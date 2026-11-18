# 10 — Ethics, privacy, and limitations

This is the chapter to read before writing a single claim in a report, a slide, or a demo
script. The project is useful *because* it is honest about what it does not know.

## 1. Claims you can make — and cannot

| You **can** say | You **cannot** say |
|---|---|
| "The pipeline serves a pretrained ImageNet ONNX model and maps it to 32 waste items." | "It recognises any waste item with 95% accuracy." |
| "Macro-F1 on the held-out test split was X." | "It works in every Indian city." |
| "It explains the SWM 2016 three-stream rule and links the source." | "It gives legal advice." |
| "It finds nearby collection points from OpenStreetMap." | "Every listed point accepts your item." |
| "It warns about battery, mercury and sharps hazards." | "It makes disposal safe." |
| "It runs with zero API keys and zero cloud cost." | "It is production-ready for a municipality." |

The shipped `artifacts_pretrained/` model is **pretrained ImageNet MobileNetV3-Large**,
not a waste-specific model. It recognises 1,000 everyday objects; 287 of those classes are
mapped to 27 of our 32 waste items, and everything else returns "not sure". The separate
`artifacts_demo/` model is trained on synthetic coloured rectangles: its ~0.97 accuracy is
a **pipeline test**, not a waste-classification result. Never put either number on a poster
as "waste accuracy".

## 2. Model limitations (the honest list)

1. **Domain shift.** TrashNet/TACO photos are studio-lit objects on clean backgrounds.
   Real kitchens are cluttered, wet, partly hidden, and photographed at night. Expect a
   large drop; measure it on the `wild` split.
2. **Indian items are under-represented.** Milk pouches, sachets, idli batter packets,
   coconut shells, e-waste chargers, agarbatti boxes, medical blister packs — global
   datasets barely contain them. Collect them yourself.
3. **Coverage, not open set.** The ImageNet model knows 1,000 object classes and only 287
   are mapped to a waste item. A shoe, a toy, or a dead rat stays unmapped and returns
   "not sure". A vision-LLM key extends this to arbitrary photos; a proper open-set
   classifier trained on your own `other` class is future work.
4. **Single-object assumption.** A photo of a full dustbin is not one item. The UI asks for
   one item per photo, but users will ignore that.
5. **Category ≠ disposal.** "Plastic bottle" is recyclable in one city and refuse-derived
   fuel in another. The app gives the general rule and says to verify locally.
6. **Calibration is data-dependent.** The demo's temperature (0.05) hit the grid edge on
   34 validation images. A real fit needs ≥ 200. Recalibrate after every retrain.
7. **No temporal or user adaptation.** It does not learn from your corrections in-session.
   Feedback goes to a queue for the next training round.

## 3. Dataset ethics and licences

- **Check every licence before you publish a model trained on it.** TrashNet is research
  use; TACO is CC BY 4.0 with attribution; Garbage-12 and RealWaste have their own terms.
  A student report is fine; a commercial app may not be.
- **Do not redistribute the raw images** in the repo. `.gitignore` excludes `data/raw/`.
- **Wild photos:** photograph objects, not people, not house numbers, not licence plates.
  Get consent if a photo is taken in someone else's home.
- **Attribution:** if you use TACO, credit the TACO authors and the original image licences.
- **Bias:** datasets skew urban, middle-class, and English-labelled. A model that works on
  a campus may fail in a village with different packaging. Say this out loud.

## 4. Privacy

The design is privacy-first by construction:

| Data | Stored? | Where |
|---|---|---|
| The uploaded image | **No by default** | memory only, for one request |
| The uploaded image (opt-in) | Cloudinary only | set `IMAGE_STORAGE=true` + `CLOUDINARY_URL`; sanitized JPEG, public URL |
| EXIF / GPS | **No** | stripped by re-encoding in `imaging.py` |
| Item + category + confidence | Yes | SQLite, keyed by a random device id |
| Chat message / answer | **No** (in-memory session only) | server RAM, 30 min TTL |
| Precise location | **No** | passed to the facility query, never persisted |
| Phone / email in feedback | Redacted before insert | `safety.redact` |

Still be explicit about third parties:

- **LLM providers** (if enabled) receive the chat text and, when attached, the image
  base64. Their retention policies apply. With `LLM_PROVIDER=fake` nothing leaves the server.
- **OpenStreetMap / Overpass** receives the search coordinates (rounded by the query radius,
  but still a location).
- **OSM tiles** are loaded by the browser from `tile.openstreetmap.org`; the tile server
  sees the user's IP and the map area viewed.
- **Barcode lookup** sends the code to Open Food Facts.
- **Cloudinary** (only when `IMAGE_STORAGE=true`) receives the sanitized scan image and
  hosts it at a public `secure_url`. The URL is random but not access-controlled; disable
  the feature for sensitive photos.

For a real deployment: add a privacy notice, a retention period for the SQLite rows, and a
way to delete a device id (`DELETE /history?device_id=...` is not implemented yet — a known
gap).

The `device_id` is a random string in `localStorage`, not a fingerprint. It groups a
browser's scans; it does not identify a person.

## 5. Safety

Hazardous waste is the part where a wrong answer can hurt someone.

- **Battery:** swollen/leaking cells can catch fire. The warning is a server-side constant:
  tape terminals, isolate, do not charge, call the helpline. The LLM cannot remove it.
- **Mercury (CFL/tube light):** do not break, crush, or vacuum. Ventilate, gloves, sealed
  container, authorised recycler.
- **Sharps:** never recap or bend; puncture-proof container; biomedical collection point.
- **Domestic hazardous:** original sealed container, hazardous collection, never the drain.
- **Refusals:** medical/legal advice and anything explosive is refused with a pointer to a
  doctor, lawyer, or emergency services (112).

What the app **cannot** do:

- It cannot verify that a facility will accept the item, is open, or is authorised.
- It cannot assess whether a specific battery is safe to move.
- It cannot replace the municipal helpline, a doctor, or a fire extinguisher.

The rule for the project: **when in doubt, escalate to a human authority.** A helpful
answer is not worth a burn or a poisoning.

## 6. Language and accessibility

- The UI is fully translated into Hindi and Marathi; the **disposal steps are English** in
  the current taxonomy. The result card says so. Do not claim full translation.
- Machine translation of rule text is risky: a mistranslated "do not" is dangerous. Prefer
  human-reviewed translations in `label_map.yaml` (`steps_hi`, `steps_mr`) over an LLM.
- Devanagari tokenization is handled in the BM25 index, so Hindi queries retrieve English
  passages. Cross-language retrieval is basic, not semantic.
- Accessibility: semantic landmarks, labels, focus rings, 40 px targets, reduced-motion
  support. It has not been tested with a screen reader end-to-end; that is a known gap.
- Low literacy: icons + short sentences help, but the app still assumes reading. A
  voice-first flow is future work.

## 7. Fairness and the informal sector

- **Do not demonise kabadiwalas.** They are the de facto recycling system in most Indian
  cities and recover far more material than formal schemes. The app says "hand to a
  kabadiwala / MRF" for clean recyclables. The warning is about *unsafe informal e-waste
  processing* (acid baths, open burning), not about the people.
- **Formalisation matters.** Encourage authorised recyclers and brand take-back, but
  acknowledge that they are often farther away and less convenient. A map that only shows
  formal facilities can be useless in a low-income area.
- **Digital divide.** The app needs a smartphone, data, and English/Hindi/Marathi literacy.
  It cannot substitute for door-to-door collection or municipal infrastructure.
- **Feedback bias.** Corrections come from users who bother to tap 👍/👎 — usually the
  engaged, educated minority. Do not treat the feedback queue as a representative sample.

## 8. Environmental honesty

- **Eco points are motivational, not measured.** 10 points for a battery does not mean
  10 units of CO₂ avoided. Do not present them as offsets or credits.
- **No CO₂ numbers** appear in the app because there is no defensible per-item factor in
  the data. If you add one, cite the source and the assumptions.
- **Recycling is not the first option.** Reduce and reuse come first. The app should not
  make people feel that buying more plastic is fine as long as they recycle it.
- **Wrong disposal has a cost.** One battery in a truck can cause a fire; one wet bag can
  spoil a bale. The app emphasises that, rather than "just recycle everything".

## 9. Legal

- The knowledge documents are **summaries**, not the gazetted text. Rules are amended;
  verify on CPCB / MoEFCC / state pollution control board sites.
- Local bin colours, collection days, and facility acceptance are municipal bye-laws. The
  app says "verify with your municipal corporation" for a reason.
- Nothing in the app is legal, medical, or financial advice.
- OpenStreetMap data is ODbL; keep the attribution. Leaflet is BSD-2-Clause. Dataset
  licences are listed in `docs/02`.

## 10. Failure modes and mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| Model confidently wrong | wrong bin | confidence + margin gate, alternatives, feedback |
| LLM hallucinates a facility | user goes nowhere | tools only, "never invent a facility" prompt, UI labels source |
| LLM gives unsafe advice | injury | server-side hazard warnings, banned-phrase post-filter, refusal pre-filter |
| Overpass down | empty map | stale cache, fixture fallback, helpline text |
| API key expires | chat degrades | rule-card fallback, `tool_trace` says `llm_failed` |
| Database lost on redeploy | history resets | documented; volume for production |
| Model file missing | no classify | 503 with the fix command; rest of app works |
| Hindi step text missing | half-translated card | explicit note in the UI |

## 11. Open problems (good final-slide material)

1. Open-set recognition: a calibrated "none of these" class.
2. Multi-object scenes: detect and label several items in one photo.
3. Human-reviewed Hindi/Marathi disposal steps.
4. Offline mobile app with the 1.7 MB model on-device (TFLite/ONNX Mobile).
5. Verified, city-specific facility data with opening hours and acceptance rules.
6. A real CO₂/landfill-diversion model with cited factors.
7. Screen-reader and low-literacy user testing.
8. A deletion and retention policy for `/history`.

## 12. One-paragraph ethics statement (use this)

> Kachra Mitra is a decision-support tool, not an authority. It classifies a photo into a
> small, fixed taxonomy and explains the general Indian disposal rule, then points to
> nearby collection options. It stores no images by default (an operator can opt into
> sanitized Cloudinary storage), does not give legal or medical
> advice, and cannot guarantee that a facility will accept an item. Hazard warnings for
> batteries, mercury, and sharps are generated server-side and cannot be overridden by the
> language model. Accuracy is measured on a held-out split and a wild-photo split, and the
> limitations — closed-set labels, urban dataset bias, and English-only step text — are
> documented rather than hidden.
