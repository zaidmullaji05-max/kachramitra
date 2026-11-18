# 04 — Backend (FastAPI)

## 1. What exists

```
backend/
├─ app/
│  ├─ main.py         routes, lifespan, CORS, rate limit, static mount
│  ├─ config.py       Settings (env / backend/.env) — one place for every knob
│  ├─ schemas.py      the API contract (pydantic v2)
│  ├─ classifier.py   model selection + taxonomy enrichment + text-hint fusion
│  ├─ vision.py       optional Gemini/Groq open-vocabulary identification
│  ├─ imaging.py      validate / EXIF-strip / downscale uploads (never saved)
│  ├─ facilities.py   Overpass + fixture providers, SQLite cache, OSRM directions
│  ├─ llm.py          Groq / Gemini behind one OpenAI-compatible interface
│  ├─ chat.py         prompt + single-shot answer + deterministic rule fallback
│  ├─ safety.py       hard-coded hazard warnings, PII redaction, refusals
│  ├─ taxonomy.py     cached access to tools/taxonomy.py
│  ├─ hints.py        Open Food Facts barcode lookup (best-effort)
│  └─ db.py           SQLite: scans, feedback, facility cache
├─ fixtures/facilities.json   sample map data (clearly labelled "demo data")
├─ tests/                    27 tests, no keys required
├─ requirements.txt
└─ .env.example
```

## 2. Run it

```powershell
# from the project root, with the venv active
pip install -r requirements-ml.txt -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env      # optional; defaults work

# model (needed for /classify; everything else works without it)
python ml/export_onnx.py
python ml/calibrate.py --split val      # makes the 0.60 confidence gate meaningful

uvicorn backend.app.main:app --reload --port 8000
# docs:  http://127.0.0.1:8000/docs
# tip:   uvicorn app.main:app --reload  (from inside backend/) also works
```

Eleven tests, no keys, no model:

```powershell
cd backend
python -m pytest tests -q
```

## 3. Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | honest capability flags (is the model loaded? which LLM? which map source?) |
| GET | `/taxonomy` | 6 categories + 32 items with Hindi/Marathi names, colours, icons |
| POST | `/classify` | multipart: `file`, `text_hint?`, `barcode?`, `lang`, `device_id?` |
| POST | `/chat` | `{message, lang, context{scan_id,item,category,confidence,lat,lng}}` |
| GET | `/facilities` | `lat,lng,category,radius_m,limit,refresh` |
| GET | `/facilities/{id}/directions` | OSRM route + Google Maps deep link |
| GET | `/history` | `device_id` → scans, totals, category breakdown, eco points |
| POST | `/feedback` | correction for the active-learning queue |

### Example: classify

```powershell
curl.exe -X POST http://127.0.0.1:8000/classify `
  -F "file=@C:\photos\bottle.jpg" -F "lang=hi" -F "text_hint=प्लास्टिक बोतल"
```

```json
{
  "item": "plastic_bottle",
  "item_display": "प्लास्टिक की बोतल",
  "category": "recyclable",
  "category_display": "पुनर्चक्रण योग्य (सूखा कचरा)",
  "confidence": 0.93,
  "top_k": [{"item": "plastic_bottle", "name": "Plastic bottle", "category": "recyclable", "p": 0.93}],
  "uncertain": false,
  "source": "model",
  "hazards": [],
  "disposal": {"bin": "Blue bin — dry waste ...", "steps": ["..."], "do_not": ["..."],
               "rule_refs": ["Solid Waste Management Rules, 2016"]},
  "facility_category": "recyclable",
  "follow_up": null,
  "hint_matches": ["plastic_bottle"],
  "barcode_hint": null,
  "scan_id": "scn_9f2c...",
  "eco_points": 5
}
```

### Example: chat

```powershell
curl.exe -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"message\":\"ट्यूबलाइट फूट गई है, क्या करूँ?\",\"lang\":\"hi\",\"context\":{\"item\":\"bulb_tube_light\",\"category\":\"ewaste\"}}"
```

Returns `answer`, `warnings[]` (danger for mercury), `sources[]`, `facilities[]`, `tool_trace[]`.

### Example: facilities

```powershell
curl.exe "http://127.0.0.1:8000/facilities?lat=19.11&lng=72.84&category=ewaste&radius_m=5000"
```

`source` tells the truth: `fixture` | `cache` | `overpass`. The UI must show "sample data" when it is `fixture`.

## 4. Decisions worth defending

**The API starts even when the model or LLM is missing.** `/health` reports the truth,
`/classify` returns 503 with the exact command to run, `/chat` falls back to rule cards.
A demo that crashes because an API key expired is a failed demo; a demo that says "AI
helper is busy, here are the rules" is fine.

**No images are stored. Ever.** `decode_upload` re-encodes the image (which drops EXIF,
including GPS), caps it at 1024 px, and the bytes are only held in memory for one request.
Only `item / category / confidence` goes to SQLite. This is both a privacy decision and
what makes `/history` cheap.

**Confidence gate, not a threshold on vibes.** `uncertain = confidence < 0.60 OR
(top1 − top2) < 0.15`. The second condition catches "0.55 vs 0.53" — the model is
guessing between two similar items and the UI should ask "is it A or B?".

**Text-hint fusion.** The classifier is image-only. If the user typed "old nokia charger"
and the image was ambiguous **and** the hint matches exactly one item, the hint wins
(`source: "text_hint"`, confidence floored at 0.72 on the model path / 0.80 on the vision
path). One rule, easy to explain, measurably better on blurry photos.

**Vision is optional and stays inside the taxonomy.** With `GEMINI_API_KEY` or
`GROQ_API_KEY` the API asks a vision model to choose one id from the 32-item list. The
model only returns `{item, confidence, alternatives, reason}`; `classifier.py` then builds
the same taxonomy card as the ONNX path. Without a key, `/classify` uses the local
pretrained ImageNet model. A vision failure logs a warning and falls back — it never
returns 500.

**Facility provider is an interface, not a vendor.** `fixture` for offline demos,
`overpass` for live OSM, `google` slots in later. Cache is SQLite with a 30-day TTL and a
bounding-box query — no PostGIS needed at this scale.

**Hazard warnings are server-side constants.** They are appended by `safety.py` and the
LLM cannot remove them. Battery/mercury/sharps text is not something to let a language
model paraphrase.

**Rate limiting is in-memory.** 30 req/min/IP, fine for one process. Redis when you have
more than one; noted in docs/01.

## 5. OSM → category mapping (and its limits)

| OSM tags | Mapped category |
|---|---|
| `amenity=recycling`, `waste_transfer_station`, `waste_disposal` | recyclable + general |
| `recycling:ewaste=yes`, `recycling:batteries=yes` | ewaste |
| `shop=electronics`, `craft=electronics_repair` | ewaste (take-back counters — may not accept waste) |
| `recycling:organic=yes` | organic |
| `recycling:hazardous=yes`, `hazardous=yes` | hazardous |
| `recycling:medical=yes` | biomedical |
| `landuse=landfill` | general |

This is a heuristic, and Indian OSM coverage is thin outside metros. Therefore:
**seed a curated JSON for your own city** (`backend/fixtures/`) and show the helpline when
the result set is empty. Do not let a blank map look like "there is no e-waste near you".

## 6. Demo-mode matrix

| Config | `/classify` | `/chat` | `/facilities` |
|---|---|---|---|
| no model, `LLM_PROVIDER=fake`, `FACILITY_PROVIDER=fixture` | 503 with reason | rule card | sample data |
| model exported, fake LLM, fixture | full result | rule card | sample data |
| model + Groq/Gemini key + overpass | full result | grounded chat | live OSM |
| upstream LLM 429/timeout | — | automatic rule fallback, `tool_trace=["llm_failed","rules"]` | — |

## 7. What step 5 adds

`chat.py` currently does one LLM call. Step 5 replaces the body of `answer()` with the
tool-calling agent loop:

- tools: `classify_image`, `find_facilities`, `search_rules`, `get_item_guide`
- a BM25 knowledge base over the actual rule text (SWM 2016, E-Waste 2022, Battery 2022)
- stricter guardrails: pre-filter, post-filter, citation enforcement
- multi-turn memory keyed by `session_id`
- language detection + reply-language enforcement

The prompt, the fallback, `safety.py` and the response schema are already in their final
shape so step 5 is additive, not a rewrite.
