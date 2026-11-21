# 09 — Testing, CI, deployment, and a 4-week plan

## 1. Test pyramid for this project

| Layer | What it proves | Where | Runs in CI |
|---|---|---|---|
| Data pipeline | manifest splits, dedupe, labels resolve | `tools/build_manifest.py` + `data/report.md` | yes (demo data) |
| Model | train/eval/export scripts execute, ONNX parity | `ml/*.py` smoke run | optional |
| Retrieval | the right rule passage is found | `test_knowledge_retrieval` | yes |
| API | routes, validation, fallback, hazards, DB | `backend/tests/test_api.py` | yes |
| Agent | tool loop, image path, refusal | API tests + fake provider | yes |
| Frontend | real clicks, camera/upload, map, i18n | manual checklist (`docs/06`) | manual |
| Safety | hazards always attached, banned advice blocked | `test_chat_rule_fallback_with_hazard` | yes |

The important rule: **the suite must pass with no API key and no trained model.** Otherwise
it will be skipped exactly when it matters (the night before the demo).

## 2. Run the tests

```powershell
# from the project root
$env:PYTHONIOENCODING="utf-8"

# without a model — classify tests assert the 503 path
cd backend
..\.venv\Scripts\python.exe -m pytest tests -q
```

With the shipped pretrained model, the full classify path also runs:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
# 41 passed
```

What the tests cover:

1. `/health` reports capability flags honestly
2. `/taxonomy` serves all six categories
3. `/facilities` fixture data is sorted and category-correct
4. `/facilities` rejects an unknown category
5. `/classify` rejects a non-image with 400 even when the model is down
6. `/classify` full path + scan persisted to history
7. Hindi chat without context matches a tube light and injects the mercury warning
8. Chat refusal (medical advice) never calls the LLM
9. `/history` + `/feedback` round-trip through SQLite
10. Schema validation: empty message 422, unsupported language 422
11. Knowledge retrieval finds the battery-safety passage
12. Image path in fake-LLM mode still runs `classify_image`
13. ImageNet class→item mapping and probability aggregation
14. Laptop/notebook disambiguation and unknown-object abstention
15. Vision JSON parsing, provider resolution, and vision→taxonomy conversion
16. CLIP prompt builder: every item has ASCII descriptions, no duplicates
17. CLIP zero-shot: the best-matching item wins, "not waste" photos are rejected
18. Fusion: a confident CLIP reading corrects ImageNet, agreement raises confidence,
    and "neither model found waste" abstains instead of guessing

```powershell
# API smoke, no browser
curl.exe http://127.0.0.1:8000/health
curl.exe "http://127.0.0.1:8000/facilities?lat=19.11&lng=72.84&category=ewaste"
curl.exe -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" `
  -d "{\"message\":\"Where does a broken CFL go?\",\"lang\":\"en\"}"
```

## 3. CI (GitHub Actions)

`.github/workflows/ci.yml` installs only the backend deps (no torch), builds the demo
manifest, compiles every Python file, and runs the suite. That is deliberately fast (< 1 min)
so it can run on every push.

```yaml
- uses: actions/setup-python@v5
  with: { python-version: "3.12" }
- run: pip install -r backend/requirements.txt
- run: python tools/make_demo_data.py
- run: python tools/build_manifest.py --raw-dir data/raw_demo --out data/demo/manifest.csv
- run: python -m compileall -q backend ml tools
- run: PYTHONIOENCODING=utf-8 python -m pytest backend/tests -q
  env:
    ONNX_PATH: artifacts_missing.onnx
    LLM_PROVIDER: fake
    FACILITY_PROVIDER: fixture
```

Add a second, optional job later for training on a small fixture; do not make every push
download torch.

## 4. Docker

```powershell
docker build -t kachra-mitra .
docker run --rm -p 8000:8000 `
  -e LLM_PROVIDER=fake `
  -e FACILITY_PROVIDER=fixture `
  kachra-mitra
# http://127.0.0.1:8000/app/
```

The image installs **backend requirements only** — no torch, no training data. Inference is
ONNX Runtime, so the image stays around 350–450 MB. The shipped pretrained model is
22 MB fp32 (5.5 MB int8).

To ship a real model:

```powershell
python ml/export_onnx.py --ckpt artifacts/model_best.pt --out artifacts
docker build -t kachra-mitra .
```

`artifacts_pretrained/`, `artifacts_demo/` and `artifacts/` are all copied by `COPY . .`;
the default `ONNX_PATH` points at the pretrained model. If none exists, the API still
boots and `/health` says the classifier is disabled.

## 5. Free deployment options (2026)

| Host | Free tier | Good | Watch out |
|---|---|---|---|
| **Render** (web service, Docker) | 512 MB, sleeps after ~15 min | easiest Docker deploy | cold start 30–60 s; ephemeral disk |
| **Hugging Face Spaces** (Docker) | 2 vCPU, 16 GB, always on | generous, good for demos | public by default; no private env unless configured |
| **Fly.io** | small free allowance | global, fast | card required, config learning curve |
| **Koyeb** | small free instance | Docker, simple | sleeps/cold starts on free |
| **Railway** | trial credits | very easy | not permanently free |
| **PythonAnywhere** | free tier | simple WSGI | no Docker, ONNX Runtime may be awkward |
| **Vercel/Netlify** | static only | great for the frontend | backend must live elsewhere |

The exact Vercel + Render + Cloudinary setup is in `docs/11-deploy.md` (blueprints,
`frontend/config.js`, CORS, ephemeral SQLite, image-storage privacy).

Recommended for a student demo: **Hugging Face Spaces (Docker)** or **Render**. Both accept
the Dockerfile unchanged.

### Production env for the host

```
LLM_PROVIDER=groq
GROQ_API_KEY=<secret>
FACILITY_PROVIDER=overpass
ALLOW_ORIGINS=https://your-frontend.example
RATE_LIMIT_PER_MIN=20
ONNX_PATH=artifacts_pretrained/mobilenet_v3_large_imagenet.onnx
LABELS_PATH=artifacts_pretrained/labels.json
DB_PATH=/data/app.db
```

Optional open-vocabulary identification on the host:

```
VISION_PROVIDER=auto
GEMINI_API_KEY=<secret>
```

Notes:

- **Never put API keys in `app.js`.** The backend is the only place they live.
- Free hosts have **ephemeral disks**; SQLite resets on redeploy. Mount a volume or accept
  it for a demo. Document it rather than pretending history is durable.
- Set `ALLOW_ORIGINS` to the actual frontend origin. `*` is for local development.
- Serve over HTTPS so browser geolocation works.
- Overpass and OSRM public instances rate-limit; the app degrades to fixture/cached data.

### Cost (₹, realistic)

| Item | Cost |
|---|---|
| Python, FastAPI, ONNX Runtime, Leaflet, OSM, Overpass | ₹0 |
| LLM (Groq/Gemini free tier) | ₹0 within limits |
| Hosting (HF Spaces / Render free) | ₹0 |
| Domain (optional) | ~₹800/year |
| Datasets | ₹0 (research licences; check each) |

## 6. Four-week build plan

### Week 1 — data and model

| Day | Task | Done when |
|---|---|---|
| 1 | Repo, venv, label map, taxonomy | `python tools/build_manifest.py` runs |
| 2 | Download TrashNet + TACO + Garbage-12, map labels | `data/report.md` shows counts per item |
| 3 | Dedupe + split, first training run | `artifacts/model_best.pt` exists |
| 4 | Evaluate: confusion matrix, per-class F1 | weak classes identified |
| 5 | Calibrate, export int8, parity check | `artifacts/*.onnx` + `calibration.json` |
| 6 | Collect 100–200 **wild** phone photos in your city | `wild` split evaluated |
| 7 | Buffer + write `docs/02`, `docs/03` | numbers are real, not toy |

### Week 2 — backend and agent

| Day | Task | Done when |
|---|---|---|
| 8 | FastAPI skeleton, schemas, config | `/health` responds |
| 9 | `/classify` + imaging + SQLite | curl returns a card |
| 10 | `/facilities` fixture + Overpass | sorted distances |
| 11 | Knowledge markdown + BM25 | retrieval queries work |
| 12 | Tools + agent loop | fake mode answers, image path works |
| 13 | Guardrails, refusals, PII, tests | `pytest` green, 0 keys |
| 14 | Buffer + `docs/04`, `docs/05` | — |

### Week 3 — frontend and maps

| Day | Task | Done when |
|---|---|---|
| 15 | HTML shell, tabs, CSS | `/app/` loads on a phone |
| 16 | Camera/upload + result card | real photo → card |
| 17 | Chat UI + warnings + sources | conversation works |
| 18 | Leaflet map + facility list | pins + distance sort |
| 19 | EN/HI/MR i18n | every static string switches |
| 20 | History + eco points + feedback | impact tab updates |
| 21 | Accessibility + mobile polish | 360 px checklist passes |

### Week 4 — evaluation, deployment, demo

| Day | Task | Done when |
|---|---|---|
| 22 | Test on 20 unseen items, log failures | error table |
| 23 | Fix top 3 failures (data or UI) | before/after numbers |
| 24 | Docker + deploy | public URL works |
| 25 | README, screenshots, demo video (2 min) | links in README |
| 26 | Viva slides: architecture, metrics, limits | 10 slides |
| 27 | Rehearse demo with **no internet** | fixture mode works |
| 28 | Buffer | — |

The plan assumes ~3 focused hours/day. The three tasks that always take longer than
expected: dataset mapping, wild-photo collection, and deployment cold starts. Start them
early.

## 7. Demo-day checklist

- [ ] `pytest` green on the laptop you will use
- [ ] demo artifacts present, `/health` shows `classifier.ready: true`
- [ ] `FACILITY_PROVIDER=fixture` so the map works without internet
- [ ] `LLM_PROVIDER=fake` fallback tested (then switch to the real key if Wi-Fi holds)
- [ ] three photos ready: a bottle, a battery, something ambiguous
- [ ] one Hindi question and one Marathi question ready
- [ ] screenshots in the slides, in case the live demo fails
- [ ] laptop charged, phone hotspot as backup
- [ ] you can explain **one** number honestly (e.g. macro-F1 on the wild split) and one
      limitation you did not solve
