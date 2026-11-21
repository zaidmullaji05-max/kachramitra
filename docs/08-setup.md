# 08 — Setup and running (Windows first, Linux notes at the end)

Everything below is the path that was actually executed on this machine.

## 1. Prerequisites

| Need | Notes |
|---|---|
| Python 3.10+ | tested on **3.14.7**; 3.12 is the safest for deployment |
| ~2 GB disk | torch is the big one (CPU wheel ~130 MB) |
| 8 GB RAM | CPU training of MobileNetV3-Small is fine on 4 GB |
| Internet | first install + optional Overpass/LLM; the app runs offline after setup |
| Node | **not required** (no frontend build) |

Check:

```powershell
py -3.14 --version
```

## 2. Create the venv and install

```powershell
cd "C:\Users\zaidm\OneDrive\Documents\Default Project"
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1

# to run the app (backend + pretrained ONNX inference)
pip install -r backend/requirements.txt

# optional: only if you want to retrain or rebuild the ONNX model
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-ml.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 3. Ten-minute demo (no datasets, no API keys)

The repository ships both models (`artifacts_pretrained/` + `artifacts_clip/`), so you can
start the app immediately — there is no training step and no `requirements-ml.txt` install:

```powershell
uvicorn backend.app.main:app --reload --port 8000
```

Open **http://127.0.0.1:8000/app/**. `/docs` is the interactive API.
`http://127.0.0.1:8000/health` should show `"classifier": {"ready": true}` and
`"clip": {"enabled": true, "model": "mobileclip2_s0_visual_fp16.onnx"}`.

Optional third tier — a cloud model that can *name* objects neither local model knows:

```powershell
$env:GEMINI_API_KEY="your-free-key"    # aistudio.google.com
$env:VISION_PROVIDER="auto"
uvicorn backend.app.main:app --reload --port 8000
```

### Rebuild the pretrained models

```powershell
pip install -r requirements-ml.txt
python tools/build_imagenet_model.py --out artifacts_pretrained
python tools/build_clip_model.py --check-images path/to/test/photos
```

`build_imagenet_model.py` downloads torchvision's MobileNetV3-Large ImageNet weights,
merges the ONNX weights into one file, writes `labels.json`, and regenerates
`mapping_report.md`.

`build_clip_model.py` downloads MobileCLIP2-S0 (~215 MB, once), encodes the 1,165 prompts
from `tools/clip_prompts.py`, exports the image tower as fp16 ONNX, and prints a parity
report. It exits non-zero when the ONNX output drifts from PyTorch, so a bad export cannot
ship.

### Synthetic pipeline demo (training test only)

```powershell
# 1) synthetic images + manifest
python tools/make_demo_data.py
python tools/build_manifest.py --raw-dir data/raw_demo --out data/demo/manifest.csv

# 2) train (CPU, ~15 s)
python ml/train.py --manifest data/demo/manifest.csv --epochs 4 --freeze-epochs 1 `
  --batch 16 --out artifacts_demo --workers 0

# 3) evaluate + export + calibrate
python ml/evaluate.py --manifest data/demo/manifest.csv --ckpt artifacts_demo/model_best.pt --split test
python ml/export_onnx.py --ckpt artifacts_demo/model_best.pt --out artifacts_demo
python ml/calibrate.py --ckpt artifacts_demo/model_best.pt `
  --manifest data/demo/manifest.csv --split val --out artifacts_demo

# 4) point the API at the demo artifacts and start it
$env:ONNX_PATH="artifacts_demo/waste_model_int8.onnx"
$env:LABELS_PATH="artifacts_demo/labels.json"
uvicorn backend.app.main:app --reload --port 8000
```

> The `artifacts_demo` model is trained on coloured rectangles. It proves the
> train/export pipeline works; it does **not** recognise real waste. Do not show its
> accuracy as a result.

### No model at all

The API still starts. `/classify` returns 503 with the exact command to fix it, `/chat`
answers from rule cards, `/facilities` returns sample data. That is intentional.

## 4. Real data

### Folder layout

```
data/raw/
├─ trashnet/            ImageFolder: cardboard/ glass/ metal/ paper/ plastic/ trash/
├─ taco/                COCO annotations.json + images
├─ garbage12/           ImageFolder with 12 classes
├─ realwaste/           ImageFolder with 9 classes
└─ wild/                your own phone photos, one folder per item id
```

### Configure and build

1. Open `data/label_map.yaml`.
2. For each source, add the dataset's label → item id under `sources:`.
   Example:

   ```yaml
   sources:
     trashnet:
       cardboard: cardboard
       glass: glass_container
       metal: metal_scrap
       paper: paper
       plastic: plastic_bottle
       trash: mixed_trash
   ```

3. Run the builder:

```powershell
# TACO is COCO-format; the rest are folders
python tools/build_manifest.py `
  --raw-dir data/raw `
  --coco taco=data/raw/taco/annotations.json `
  --out data/manifest.csv `
  --wild-sources wild:0.5
```

4. Split/merge checks: the builder de-duplicates with a DCT perceptual hash **before**
   a grouped stratified split, so near-identical photos cannot leak across train/test.
   Review `data/report.md`; it prints per-class counts and the kept/skipped reasons.

5. Train for real:

```powershell
python ml/train.py --manifest data/manifest.csv --epochs 18 --freeze-epochs 3 `
  --batch 32 --out artifacts --workers 2
python ml/evaluate.py --ckpt artifacts/model_best.pt --split test --out artifacts/eval
python ml/evaluate.py --ckpt artifacts/model_best.pt --split wild --out artifacts/eval_wild
python ml/export_onnx.py --ckpt artifacts/model_best.pt --out artifacts
python ml/calibrate.py --ckpt artifacts/model_best.pt --split val --out artifacts
```

6. Point the API at `artifacts/`:

```powershell
Copy-Item backend/.env.example backend/.env
# edit ONNX_PATH=artifacts/waste_model_int8.onnx
#      LABELS_PATH=artifacts/labels.json
uvicorn backend.app.main:app --port 8000
```

## 5. Environment variables

Copy `backend/.env.example` to `backend/.env`. Every value has a working default.

| Variable | Default | What it does |
|---|---|---|
| `ONNX_PATH` | `artifacts_pretrained/mobilenet_v3_large_imagenet.onnx` | shipped pretrained model |
| `LABELS_PATH` | `artifacts_pretrained/labels.json` | ImageNet class → waste item map |
| `CLIP_ENABLED` | `true` | zero-shot head; `false` runs ImageNet alone |
| `CLIP_MODEL_PATH` | `artifacts_clip/mobileclip2_s0_visual_fp16.onnx` | CLIP image tower |
| `CLIP_EMBEDS_PATH` | `artifacts_clip/clip_text_embeds.npz` | 32-item + negative prompt vectors |
| `CLASSIFIER_ENABLED` | `true` | set `false` to force demo mode |
| `ALLOW_DEMO_MODEL` | `false` | keep the synthetic `artifacts_demo` model instead of auto-upgrading to the pretrained one |
| `CONFIDENCE_THRESHOLD` | `0.60` | below this → `uncertain` |
| `CONFIDENCE_MARGIN` | `0.15` | top1−top2 below this → `uncertain` |
| `DB_PATH` | `backend/data/app.db` | SQLite (scans, feedback, facility cache) |
| `LLM_PROVIDER` | `fake` | `fake` / `groq` / `gemini` |
| `GROQ_API_KEY` | empty | free key from console.groq.com; also enables vision |
| `GEMINI_API_KEY` | empty | free key from aistudio.google.com; also enables vision |
| `LLM_MODEL` | provider default | e.g. `llama-3.3-70b-versatile` |
| `LLM_TIMEOUT_S` | `20` | hard timeout per LLM call |
| `VISION_PROVIDER` | `auto` | `auto` / `gemini` / `groq` / `off` |
| `VISION_MODEL` | provider default | `gemini-2.5-flash` or `meta-llama/llama-4-scout-…` |
| `VISION_TIMEOUT_S` | `30` | hard timeout per vision call |
| `FACILITY_PROVIDER` | `fixture` | `fixture` / `overpass` |
| `OVERPASS_URL` | public instance | swap if rate-limited |
| `OSRM_URL` | public instance | routing |
| `FACILITY_CACHE_DAYS` | `30` | cache TTL |
| `ALLOW_ORIGINS` | `*` | CORS; tighten in production |
| `RATE_LIMIT_PER_MIN` | `30` | per IP, in-memory |
| `MAX_UPLOAD_MB` | `8` | upload guard |
| `IMAGE_STORAGE` | `false` | opt in to Cloudinary scan-image storage |
| `CLOUDINARY_URL` | empty | `cloudinary://key:secret@cloud_name`; required with `IMAGE_STORAGE` |
| `CLOUDINARY_FOLDER` | `kachra-mitra/scans` | Cloudinary folder |
| `CLOUDINARY_TIMEOUT_S` | `15` | upload timeout; failures never break `/classify` |
| `ADMIN_PASSWORD` | empty | admin panel passphrase; **empty keeps `/admin/*` returning 503** |
| `ADMIN_TOKEN_TTL_HOURS` | `12` | how long a sign-in lasts |

For Vercel + Render + Cloudinary, including CORS and free-tier caveats, see
`docs/11-deploy.md`.

### Admin panel (optional)

```powershell
$env:ADMIN_PASSWORD="a long random passphrase"
python -m uvicorn backend.app.main:app --reload --port 8000
start http://127.0.0.1:8000/app/admin.html
```

The panel reads the same SQLite file as `/history`, so local scans appear immediately.
No password set means the routes answer `503` — the feature fails closed.

### Turn on the real agent (free)

```powershell
# Groq
$env:LLM_PROVIDER="groq"; $env:GROQ_API_KEY="gsk_..."
# or Gemini
$env:LLM_PROVIDER="gemini"; $env:GEMINI_API_KEY="AIza..."

# live map data
$env:FACILITY_PROVIDER="overpass"
```

Restart uvicorn after changing env vars (Settings is cached).

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `UnicodeEncodeError: charmap` | Windows console is cp1252 | `$env:PYTHONIOENCODING="utf-8"` |
| `ModuleNotFoundError: onnxruntime` | backend deps not installed | `pip install -r backend/requirements.txt` |
| `/classify` 503 | model/labels missing | run `tools/build_imagenet_model.py`, check `ONNX_PATH` |
| `/health` shows `"clip": {"enabled": false}` | CLIP files missing or broken | run `tools/build_clip_model.py`; `reason` says what failed |
| `/app` 404 | folder created after import | restart uvicorn |
| Frontend cannot reach API | opened as `file://` or CORS | use `/app/`, or set `localStorage.waste.apiBase` |
| Map pins missing | Overpass timeout / no OSM data | switch to `fixture`, or widen radius |
| Geolocation blocked | browser needs HTTPS (or localhost) | run on `127.0.0.1` or deploy with HTTPS |
| `Exit code 1` but output looks fine | PowerShell + native stderr | check `$LASTEXITCODE` |
| Slow pip | ~80 kB/s on this network | use the CPU torch index, don't reinstall torch |

## 7. Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

The Python code is platform-neutral. Only the console encoding notes are Windows-specific.
