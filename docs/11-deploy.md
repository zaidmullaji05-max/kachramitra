# 11 – Deploy: Vercel (frontend) + Render (backend) + Cloudinary (images)

This is the free-tier deployment this project is set up for:

```
Browser
  │  static HTML/CSS/JS
  ▼
Vercel  ──https──►  Render web service (FastAPI + ONNX)
                         │
                         └──optional signed upload──► Cloudinary
```

| Piece | Host | Cost | What it runs |
|---|---|---|---|
| Frontend | Vercel (Hobby) | ₹0 | `frontend/` — no build step |
| API | Render (Free web service) | ₹0 | `backend/app/main.py` via uvicorn |
| Images | Cloudinary (Free) | ₹0 | optional, opt-in sanitized scan photos |
| Database | Render's ephemeral disk | ₹0 | SQLite; resets on deploy/restart |

The repository already contains `vercel.json` and `render.yaml`; you do not need to
invent a build pipeline.

---

## 1. Put the project on GitHub

Both hosts deploy from a Git repository.

```powershell
cd "C:\Users\zaidm\OneDrive\Documents\Default Project"
git init
git add .
git commit -m "Kachra Mitra: app + deployment config"
git branch -M main
git remote add origin https://github.com/<you>/kachra-mitra.git
git push -u origin main
```

`.gitignore` already excludes `.venv/`, `__pycache__/`, `data/raw/`, `artifacts/`, and
`.env`. The files Render needs are explicitly whitelisted, so a normal `git add .` is
enough:

- `artifacts_pretrained/mobilenet_v3_large_imagenet.onnx` (22 MB) + `labels.json`
- `artifacts_clip/mobileclip2_s0_visual_fp16.onnx` (23 MB) +
  `clip_text_embeds.npz` (2.2 MB) + `clip_meta.json`

Checkpoints (`*.pt`), the raw datasets, and real training runs stay out of Git.

> Both shipped ONNX files are under GitHub's 25 MB web-upload limit (22 MB and 23 MB).
> If your host or repository has a smaller limit, switch `ONNX_PATH` to
> `artifacts_pretrained/mobilenet_v3_large_int8.onnx` (**5.5 MB**) and/or set
> `CLIP_ENABLED=false`; accuracy drops but the app still works.

> If no model is in the repo, the API still boots. `/health` says
> `classifier.ready: false` and `/classify` returns 503. Chat and the map still work.

---

## 2. Backend on Render

### Option A — Blueprint (recommended)

1. Open <https://dashboard.render.com/blueprints> → **New Blueprint Instance**.
2. Connect the GitHub repo. Render finds `render.yaml`.
3. When prompted for `CLOUDINARY_URL`, either paste the value from step 4 or leave it
   blank (image storage then stays off).
4. **Apply**. Wait for the first build (2–5 minutes).
5. Copy the service URL, e.g. `https://kachra-mitra-api.onrender.com`.
6. Check `https://kachra-mitra-api.onrender.com/health`. You want
   `"status": "ok"` and, if the model was committed, `"classifier": {"ready": true}`.

### Option B — Manual web service

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r backend/requirements.txt` |
| Start command | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |
| Plan | Free |

Add the environment variables from `render.yaml`. At minimum:

```
ONNX_PATH=artifacts_pretrained/mobilenet_v3_large_imagenet.onnx
LABELS_PATH=artifacts_pretrained/labels.json
CLIP_ENABLED=true
CLIP_MODEL_PATH=artifacts_clip/mobileclip2_s0_visual_fp16.onnx
CLIP_EMBEDS_PATH=artifacts_clip/clip_text_embeds.npz
LLM_PROVIDER=fake
FACILITY_PROVIDER=fixture
DB_PATH=/tmp/kachra-mitra.db
ALLOW_ORIGINS=*
# optional open-vocabulary identification
VISION_PROVIDER=auto
GEMINI_API_KEY=<your free key>
```

Free-tier facts you must plan around:

- The service **sleeps after ~15 minutes** of inactivity; the next request takes
  30–60 seconds. Say this before a demo, or ping `/health` a minute beforehand.
- The disk is **ephemeral**. SQLite history survives until the next deploy or restart.
  That is fine for a student demo; for persistence use Render Postgres or Turso.
- 512 MB RAM is enough for both local models (22 MB ImageNet + 23 MB fp16 CLIP, batch-1
  CPU inference). Measured end-to-end on Windows: **227 MB RSS** with both sessions loaded
  and a scan served, so a free instance has headroom. Do not install torch on Render — it
  is only needed for training or for rebuilding the models.
- If the build runs out of memory installing `onnxruntime`, make sure you are not
  accidentally installing `requirements-ml.txt`.
- A vision key is optional. Without it, `/classify` uses the two local ONNX models and
  still covers the 1,000 ImageNet objects plus all 32 taxonomy items; `/health` reports
  `vision.enabled: false`.

---

## 3. Frontend on Vercel

`vercel.json` at the repo root already sets `"outputDirectory": "frontend"`.

1. Edit **`frontend/config.js`** and put the Render URL there:

   ```js
   window.WASTE_API_BASE = "https://kachra-mitra-api.onrender.com";
   ```

   This is the one manual edit. Without it the static site calls its own Vercel domain
   and every API request 404s.

2. Commit and push that change.

3. Open <https://vercel.com/new>, import the repo.

4. Configure:

   | Setting | Value |
   |---|---|
   | Framework preset | **Other** |
   | Root directory | `./` (repo root) |
   | Build command | *(empty)* |
   | Output directory | `frontend` (from `vercel.json`) |

5. **Deploy**. Your app is at `https://<project>.vercel.app`.

6. Tighten CORS on Render: set `ALLOW_ORIGINS` to the exact Vercel origin, e.g.
   `https://kachra-mitra.vercel.app`, and save. Comma-separate multiple origins.
   Keep `*` only while testing.

### CLI alternative

```powershell
npm i -g vercel
vercel --prod
```

Vercel reads `vercel.json` and uploads only the static frontend.

### Why the frontend is not served by Render

The API also mounts the frontend at `/app/` for local use. On Render that path works
too, but Vercel gives you a global CDN, instant cache invalidation, and a cleaner URL.
Both can coexist.

---

## 4. Cloudinary (optional image storage)

The default privacy design stores **no images**. Turning Cloudinary on is a deliberate
two-variable decision.

### 4.1 Create the account

1. Sign up at <https://cloudinary.com/users/register/free> (free plan, no card).
2. Open **Dashboard → Programmable Media → API environment variable**. Copy the whole
   `cloudinary://<api_key>:<api_secret>@<cloud_name>` string.
3. Keep it secret. It is a signed-upload credential; never put it in `frontend/`.

### 4.2 Configure Render

Add to the Render service's **Environment**:

```
CLOUDINARY_URL=cloudinary://123456789012345:abcdefghijklmnopqrstuvwxyz@your-cloud
IMAGE_STORAGE=true
CLOUDINARY_FOLDER=kachra-mitra/scans
```

Save → Render redeploys. `/health` should now include `"image_storage": true`.

### 4.3 What gets uploaded

`backend/app/media.py` runs a **server-side signed upload** after classification:

- the input has already been decoded, EXIF-rotated, and re-encoded by `imaging.py`;
- a second JPEG re-encode drops EXIF/GPS and caps the file size;
- the public id is the random `scn_…` id — the original filename never leaks;
- Cloudinary applies `w=1024, h=1024, c=limit` and `q=auto:good, f=auto`;
- if Cloudinary is down, the exception is logged and the scan still succeeds with
  `image_url: null`.

The URL is stored in `scans.image_url` and shown as a thumbnail on the **Impact** tab.

### 4.4 Privacy copy changes automatically

When storage is enabled, `/history` returns `"image_storage": true` and the Impact
subtitle changes in EN/HI/MR from “Scans are stored without images” to “Scan photos are
stored in Cloudinary”. Do not enable this without updating your report/privacy notice:
the `secure_url` is a **public URL** for anyone who has it (the id is random, but it is
not access-controlled).

If you need private assets later, move to Cloudinary's `type="private"` + signed
delivery URLs; the current thumbnail flow assumes public delivery.

### 4.5 Free-plan limits

Cloudinary's free plan is credit-based (roughly 25 GB of storage/bandwidth per month
at the time of writing). A 1024 px JPEG is ~100–200 KB, so thousands of scans fit
comfortably. Check the current limits on your dashboard.

### 4.6 Delete an image

Cloudinary dashboard → **Media Library** → `kachra-mitra/scans`, or call the Admin API.
The SQLite row keeps the old URL; that is harmless, the thumbnail 404s.

---

## 4A. Admin panel

The panel is served by the same two services — Vercel serves `admin.html`, Render serves
`/admin/*` — so there is nothing extra to deploy.

1. Render dashboard → your service → **Environment** → add

   | Key | Value |
   |---|---|
   | `ADMIN_PASSWORD` | a long random passphrase (**not** `admin`, `1234`, or the project name) |
   | `ADMIN_TOKEN_TTL_HOURS` | `12` (optional) |

2. **Save** — Render redeploys automatically. If you skip this step the panel stays off
   and every `/admin/*` call returns `503 admin panel is off`.

3. Open `https://<project>.vercel.app/admin` (or `/app/admin.html` on the Render URL).

   ```powershell
   # check that the password is actually live
   curl.exe -X POST https://kachra-mitra-api.onrender.com/admin/login `
     -H "Content-Type: application/json" -d "{\"password\":\"your passphrase\"}"
   # -> {"token":"...","expires_at":...,"ttl_s":43200}
   ```

4. Generate a passphrase instead of inventing one:

   ```powershell
   [Convert]::ToBase64String((1..24 | % { Get-Random -Max 256 }))
   ```

Things that surprise people:

- **Scan history is ephemeral on the free plan.** `DB_PATH=/tmp/...` is wiped by every
  deploy and restart, so the panel resets with it. Export the CSV before you redeploy.
- **Deep links 404 on Vercel** unless `cleanUrls` is on — it is, in `vercel.json`, so
  `/admin` works and `/admin.html` also works.
- **Change the passphrase to revoke access.** Tokens are signed with it; old ones stop
  verifying immediately.
- The panel is `noindex,nofollow`, but that is not access control — the password is.
  There is also a small link to it at the bottom of the Impact tab.

---

## 5. Verify the deployment

```powershell
# backend
curl.exe https://kachra-mitra-api.onrender.com/health
curl.exe "https://kachra-mitra-api.onrender.com/facilities?lat=19.11&lng=72.84&category=ewaste"

# frontend (open in a browser)
start https://kachra-mitra.vercel.app
```

Manual checklist:

1. Scan tab → choose a photo → result sheet shows item/category/steps.
2. Chat tab → ask in Hindi → rule-card answer with hazard warning for a CFL/battery.
3. Map tab → allow location (HTTPS is required; Vercel gives you HTTPS).
4. Impact tab → scan appears; with Cloudinary on, the thumbnail loads.
5. Browser console → no CORS errors.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to fetch` on the Vercel site | API base still empty or Render is asleep | set `frontend/config.js`, wait for cold start |
| CORS error naming the Vercel origin | `ALLOW_ORIGINS` does not include it | set the exact origin on Render |
| `/classify` 503 | model files missing on Render | commit the ONNX + labels or fix `ONNX_PATH` |
| `/health` 502 / build fails | wrong build command | `pip install -r backend/requirements.txt` only |
| History disappeared | Render restarted, `/tmp` reset | expected on free; use a managed DB for persistence |
| `image_storage: false` after setting the URL | `IMAGE_STORAGE` not `true`, or URL malformed | set both, check the `cloudinary://` format |
| `classifier unavailable: model not found` | the `.onnx` file is not in the GitHub repo | see below |
| Thumbnails broken but scans work | Cloudinary upload failed | Render logs contain `Cloudinary upload failed`; check credentials |
| Map shows sample pins | `FACILITY_PROVIDER=fixture` | set `overpass` for live OSM data |
| Hindi text looks broken in logs | Windows cp1252 console | `$env:PYTHONIOENCODING="utf-8"` (not a deploy issue) |

### `classifier unavailable: model not found`

Open the repo on GitHub → `artifacts_pretrained/`. You must see **all three**:
`mobilenet_v3_large_imagenet.onnx` (22 MB), `mobilenet_v3_large_int8.onnx` (5.5 MB),
and `labels.json`. If the `.onnx` is missing, Git ignored it. Fix it once:

Then check `artifacts_clip/` for `mobileclip2_s0_visual_fp16.onnx` (23 MB),
`clip_text_embeds.npz`, and `clip_meta.json`. If they are missing, the API still works
with ImageNet alone and `/health` reports `"clip": {"enabled": false}`.

```powershell
git add -f artifacts_pretrained/mobilenet_v3_large_imagenet.onnx
git add -f artifacts_pretrained/mobilenet_v3_large_int8.onnx
git add -f artifacts_pretrained/labels.json
git commit -m "Ship the pretrained ONNX model for Render"
git push
```

`git add -f` is required only if your local `.gitignore` still contains `*.onnx`.
The current `.gitignore` whitelists these files, so a fresh clone can use plain
`git add .`.

If you uploaded the project through the GitHub website instead, use
**Add file → Upload files → choose `artifacts_pretrained/mobilenet_v3_large_imagenet.onnx`**,
then commit. The 22 MB file fits the 25 MB web limit; if it does not, upload
`mobilenet_v3_large_int8.onnx` instead and set `ONNX_PATH` to that name.
If the service still loads the old synthetic model after a deploy, the dashboard probably
still has `ONNX_PATH=artifacts_demo/...`. The app now detects that path, logs a warning,
and uses the shipped pretrained model automatically. To keep the synthetic model instead,
set `ALLOW_DEMO_MODEL=true`. `/health` shows the loaded file and architecture:

```json
"classifier": {"ready": true, "arch": "mobilenet_v3_large_imagenet",
               "model": "mobilenet_v3_large_imagenet.onnx"}
```

Render redeploys automatically (`autoDeploy: true`). Confirm with:

```powershell
curl.exe https://your-service.onrender.com/health
# "classifier": {"ready": true, "reason": null}
```

---

## 7. Cost summary

| Item | Free tier | When you would pay |
|---|---|---|
| Vercel Hobby | 100 GB bandwidth/month | heavy traffic or a team |
| Render Free | 512 MB, sleeps, ephemeral disk | always-on or persistent disk (~$7/mo) |
| Cloudinary Free | credit-based storage/bandwidth | many thousands of photos |
| Groq / Gemini | free developer tiers | higher rate limits |
| OpenStreetMap / Overpass | free, fair use | a hosted routing provider |

Total for a student demo: **₹0**, with the caveats above stated honestly.
