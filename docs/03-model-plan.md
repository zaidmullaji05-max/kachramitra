# 03 — Model Plan (and the code that implements it)

## 0. The decision, up front

**Ship a pretrained ImageNet MobileNetV3-Large mapped onto the 32 waste items, fused with
a zero-shot MobileCLIP2-S0 head, with a vision-LLM as an optional third tier. The rest of
this document is the recipe for training a dataset-specific model once you have real
labelled images.**

```
photo → MobileNetV3-Large (ImageNet, 1,000 classes)  → p_item over 27 mapped items
      → MobileCLIP2-S0 (zero-shot, 32 items)         → p_item + "not waste" score
           → fuse: 0.4 × ImageNet + 0.6 × CLIP
                ├─ waste + confident → answer + disposal + map
                └─ else → optional vision-LLM → one follow-up question
                          → still unsure → abstain ("can't identify, retake photo")
```

### What actually ships (`artifacts_pretrained/`)

| File | Size | Purpose |
|---|---|---|
| `mobilenet_v3_large_imagenet.onnx` | 22 MB | fp32, default `ONNX_PATH` |
| `mobilenet_v3_large_int8.onnx` | 5.5 MB | smaller/faster alternative |
| `labels.json` | 70 KB | 1,000 ImageNet class names → 32 waste ids |
| `mapping_report.md` | small | coverage: **287/1000 classes mapped**, 27/32 items covered |

`tools/imagenet_map.py` owns the mapping. Classes that are not waste objects (dogs,
cars, buildings) stay unmapped, so the API answers "not sure" instead of forcing them
into a bin. `ml/imagenet_predict.py` sums the probabilities of all classes that map to
the same item and includes a laptop/notebook confusion guard.

Rebuild it with:

```powershell
pip install -r requirements-ml.txt
python tools/build_imagenet_model.py --out artifacts_pretrained
```

### What also ships (`artifacts_clip/`) — the open-vocabulary head

ImageNet-1k has **no class** for a battery, a phone charger, a light bulb, a circuit
board, a chips packet or a syringe, even though those are the items where a wrong bin is
most dangerous. CLIP fixes that by matching the photo against *sentences* instead of a
fixed list of classes.

| File | Size | Purpose |
|---|---|---|
| `mobileclip2_s0_visual_fp16.onnx` | 23 MB | MobileCLIP2-S0 image tower, fp16 |
| `clip_text_embeds.npz` | 2.2 MB | 1,165 prompt embeddings (32 items + 20 negatives) |
| `clip_meta.json` | 1 KB | 256px input, mean/std, logit scale |

How it works:

1. `tools/clip_prompts.py` lists ~29 English descriptions per item ("a used AA battery",
   "a broken light bulb") plus 20 "not waste" descriptions (dog, cat, person, car, room).
2. `tools/build_clip_model.py` encodes them **once** with the text tower and exports only
   the image tower. Runtime therefore needs no torch and no download.
3. `ml/clip_predict.py` embeds the photo, takes the best cosine similarity per item,
   appends the negative prompts as one extra class, and softmaxes with the model's own
   logit scale (≈64).
4. `ml/clip_predict.fuse()` merges both models. If the negative class wins **and**
   ImageNet has no confident item, the app abstains instead of guessing.

**Why fp16 and not int8:** dynamic int8 quantization of this backbone destroys the
embedding — cosine similarity against PyTorch measured −0.04 to +0.13, i.e. noise. fp16
keeps cosine at **0.99998** for half the size of fp32. `build_clip_model.py
--check-images DIR` fails loudly if ONNX drifts from PyTorch, so a bad export cannot ship.

Measured on the project's test photos (`/health` reports the same models):

| Photo | Before (ImageNet only) | After (ImageNet + CLIP) |
|---|---|---|
| laptop | `laptop` 0.71 | `laptop` 0.86 |
| plastic bottle | `plastic_bottle` 0.67 | `plastic_bottle` 0.75 |
| soda can | `plastic_bottle` 0.67 ❌ | `metal_can` 0.55 ✅ |
| banana | `food_waste` 0.95 | `food_waste` 0.997 |
| t-shirt | `textile` 0.90 | `textile` 0.99 |
| chips wrapper | `food_wrapper` 0.68 | `food_wrapper` 0.78 |
| dog (not waste) | `mixed_trash` 0.05 | `mixed_trash` 0.05, refused ✅ |

### Optional vision fallback

Set `GEMINI_API_KEY` (free tier at aistudio.google.com) or `GROQ_API_KEY` and the API
will ask a vision model to name objects that neither local model knows. The vision model
never writes disposal advice; `data/label_map.yaml` still owns the bin, steps, hazards and
rule references. Without a key this path is off and the two local ONNX models are the
identifiers.

Everything else in this document justifies the dataset-specific training plan.

---

## 1. The three options, compared honestly

| | **(A) CNN + transfer learning**<br>MobileNetV3-Small | **(B) Object detection**<br>YOLOv8n / YOLOv8n-seg | **(C) Vision-LLM**<br>Gemini Flash / GPT-4o-mini |
|---|---|---|---|
| **Task fit** | One object per photo → one label. Exactly your UI. | Where are the objects? Needs boxes. | Any question about the image. |
| **Training data needed** | 80+ per class (with transfer learning) | 300+ *boxes* per class, per source style | 0 training images (prompt only) |
| **Labelling effort** | folder names only | draw boxes + classes, 5–10× slower | none |
| **CPU latency** | **~10–30 ms** | ~80–200 ms | 800–3000 ms (network) |
| **Model size** | **3–6 MB (int8: ~2 MB)** | 6–12 MB | 0 on device |
| **On-device / offline** | **yes (TFLite)** | yes, but bigger | no |
| **Accuracy, in-domain** | 0.90–0.96 on 6 classes | 0.90+ mAP50 with enough boxes | 0.75–0.90, unmeasured |
| **Calibrated confidence** | **yes** (softmax, fixable with temperature scaling) | yes (mAP/conf) | no — "very confident and wrong" is common |
| **Cost / 1,000 scans** | ₹0 after training | ₹0 after training | ₹0 (free tier) → ₹150–900 (paid) |
| **Explainability for your report** | confusion matrix, per-class recall | mAP, PR curve | none |
| **Fails how** | confidently on out-of-distribution items | misses small/occluded items | hallucinates, invents rules |
| **Verdict** | ✅ **primary model** | only if multi-item photos matter | ✅ **fallback + chat brain** |

### Why not YOLO for v1

YOLO answers "where", and your product asks "what". Detection also multiplies labelling
cost by 5–10× — you would spend week 2 drawing boxes instead of building the app.
The exception: if your demo photo is a **pile** in a bin. Then the honest fix is
`YOLOv8n` (11 classes, COCO-style) → crop each box → feed crops to the classifier.
That is a v2 feature; keep the classifier interface `image → label` so you can add it
without rewriting the API.

### Why not a vision-LLM as the primary

1. **No calibration.** You need a number you can threshold on; LLM self-reported
   confidence is not it.
2. **Latency + network dependency.** 1–3 s per scan and it breaks offline.
3. **Cost.** Fine at 100 scans/day on a free tier, not fine at 10k/day.
4. **Non-determinism.** Same photo, different label, twice — impossible to evaluate.
5. **It's genuinely better at the long tail** — "is this a compostable cutlery set?" —
   which is why it stays as the fallback. Best of both.

---

## 2. Training recipe (and why each choice)

| Setting | Value | Why |
|---|---|---|
| Architecture | `mobilenet_v3_small` (1.5 M params) | Best accuracy/latency trade-off for CPU + TFLite; EfficientNet-B0 only pays off above ~10k images |
| Pretraining | ImageNet (`weights=DEFAULT`) | With 80 images/class this is the whole ballgame |
| Input | 224×224 | Native for ImageNet weights; 320 if small objects fail |
| Freeze backbone | first 2 epochs | A random head produces huge gradients that wreck pretrained filters |
| Optimizer | AdamW, head `3e-4`, backbone `3e-5` | Discriminative LR: fine-tune gently, train the head fast |
| Schedule | 200-step warmup → cosine | Warmup avoids the early loss spike; cosine converges cleanly in 20–30 epochs |
| Weight decay | 0.01 | Mild; heavy WD hurts small datasets |
| Loss | CrossEntropy + class weights + label smoothing 0.1 | Weights for imbalance; smoothing for noisy web labels |
| Batch | 32 (48–64 on a T4) | Fits 4 GB comfortably |
| Epochs | 25, early stop on **val macro-F1**, patience 6 | Accuracy is misleading when classes are imbalanced |
| Augmentation | RandomResizedCrop(0.55–1.0), hflip, rotation ±12°, ColorJitter, translate 6%, **RandomErasing 0.25** | Simulates real usage: distance, angle, lighting, occlusion. No vertical flip (unnatural), no blur (kills texture cues) |
| Eval | resize 256 → centre-crop 224 | Standard; keep it identical in the API |

**Do not touch** the train/val/test split logic to "get a better number". The whole
point of the grouped split is that your reported number is believable.

---

## 3. Realistic expectations

| Setup | In-domain test macro-F1 | Wild test (TACO + your photos) |
|---|---|---|
| 6 categories, TrashNet + garbage12 only | 0.88–0.95 | 0.55–0.70 |
| 6 categories + RealWaste + Open Images e-waste + your 600 photos | 0.90–0.96 | **0.70–0.80** |
| 32 items, ~10k images | 0.80–0.90 | 0.60–0.75 |
| 32 items with < 80 images per item | 0.60–0.75 | do not trust it |

If your in-domain number is > 0.98, you have a leak (duplicates across splits) — rerun
the dedupe and check `report.md`.

**Fallback rule:** if item-level macro-F1 < 0.70 after 30 epochs, retrain at
`--level category` (6 classes) and let the chat agent name the specific item. A reliable
category + a conversational follow-up beats a flaky 32-way guess.

---

## 4. Run it

```powershell
# 0) once
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-ml.txt

# 1) build the manifest (after putting datasets in data/raw/<source>/<label>/)
python tools/build_manifest.py --wild-sources taco:0.3
#    -> data/manifest.csv, data/report.md, data/counts.csv

# 2) train
python ml/train.py --level item --arch mobilenet_v3_small --epochs 25
#    -> artifacts/model_best.pt, artifacts/train_log.csv

# 3) evaluate (always both)
python ml/evaluate.py --split test
python ml/evaluate.py --split wild

# 4) export + verify
python ml/export_onnx.py
#    -> artifacts/waste_model.onnx, waste_model_int8.onnx, labels.json

# 4b) calibrate confidence (one number, fixes an over/under-confident 0.60 gate)
python ml/calibrate.py --split val
#    -> artifacts/calibration.json  (picked up automatically by predict.py / the API)

# 5) try one photo
python ml/predict.py --image data/test_wild/my_bottle.jpg --lang hi
```

### Why calibrate?

A model trained with label smoothing + class weights is often **under-confident**: it gets
the item right but says 0.26, so the 0.60 gate abstains on everything. Temperature scaling
divides the logits by one fitted number `T`. It **cannot change which class wins**, so
accuracy is untouched; ECE and coverage improve.

On the synthetic smoke-test model: ECE 0.66 → 0.02, coverage@0.60 2.9% → 100% at identical
accuracy. (That T was fitted on only 34 val images and hit the grid edge — the script warns
about exactly this. Use ≥ 200 val images for a real T.)

Sanity rule: if `accuracy` changes after calibration, something is wrong — the script
refuses to write in that case.

### On Google Colab (free T4, ~15 min for 25 epochs)

```python
!pip install -q imagehash scikit-learn matplotlib onnx onnxruntime
from google.colab import drive; drive.mount('/content/drive')
%cd /content/drive/MyDrive/waste-assistant
!python ml/train.py --arch mobilenet_v3_small --batch 64 --workers 4 --epochs 30
```

Check `torch.cuda.is_available()` is `True`; the script picks the device automatically.
`--workers 4` on Colab, `0` on Windows.

---

## 5. Export

### ONNX (done, verified by `ml/export_onnx.py`)

| File | Size (MobileNetV3-Small) | Use |
|---|---|---|
| `waste_model.onnx` (fp32) | ~6 MB | server, max accuracy |
| `waste_model_int8.onnx` | ~2 MB | server CPU (2–3× faster), default in the API |
| `labels.json` | ~20 KB | class names + Hindi/Marathi + disposal text for the API |

The export script re-runs 8 random inputs through PyTorch and onnxruntime and prints
`max|Δlogit|` + argmax agreement. If agreement is not 100%, **keep fp32** — that is
quantisation damage, not a bug in your model.

The shipped pretrained model is exported by `tools/build_imagenet_model.py`, not
`ml/export_onnx.py`; the latter is for a fine-tuned classification head. The pretrained
builder also merges torch's external `.onnx.data` sidecar into one 22 MB file, which keeps
GitHub web uploads under the 25 MB limit.

### TFLite (optional, for offline mobile)

ONNX → TFLite is a conversion chain, not a one-liner on Windows. Use **Colab/Linux**:

```bash
pip install onnx2tf onnx onnxruntime
onnx2tf -i artifacts/waste_model.onnx -o artifacts/tflite -oiqt -nuo
# -> artifacts/tflite/waste_model_float32.tflite (+float16/int8 variants)
```

Alternative (official PyTorch → LiteRT path): `pip install ai-edge-torch` and
`ai_edge_torch.convert(model, (sample_input,))`. Either way, validate:

```python
import numpy as np, tensorflow as tf
itp = tf.lite.Interpreter(model_path="artifacts/tflite/waste_model_float32.tflite")
itp.allocate_tensors(); i, o = itp.get_input_details()[0], itp.get_output_details()[0]
itp.set_tensor(i["index"], x.astype(np.float32)); itp.invoke()
print(itp.get_tensor(o["index"]).argmax(-1))
```

Compare 50 predictions against the ONNX model before shipping. On-device you then have
three tiers: **TFLite in the browser (TF.js, offline)** → **server ONNX** → **vision-LLM**.

---

## 6. What the code does (module map)

| File | Responsibility |
|---|---|
| `tools/build_manifest.py` | ingest folder-per-class or COCO JSON → map via `label_map.yaml` → decode check → sha256 + phash dedupe → grouped stratified split → `manifest.csv` + `report.md` |
| `ml/train.py` | transfer learning, class weights, freeze→unfreeze, AMP, cosine, early stop on macro-F1, checkpoint |
| `ml/evaluate.py` | accuracy, macro/weighted F1, top-2, per-class P/R/F1, confusion matrix PNG+CSV, ECE, risk–coverage, abstain metrics, **safety recall for ewaste/hazardous**, `errors.csv` |
| `ml/export_onnx.py` | fp32 export → checker → int8 quantise → numerical parity → `labels.json` |
| `ml/calibrate.py` | fits one temperature on the val split; writes `calibration.json` (ECE + coverage before/after) |
| `ml/predict.py` | `OnnxClassifier` (imported by the API) + CLI; confidence gate + follow-up question |

Design notes worth knowing:

- **Dedupe before split.** TrashNet re-uploads are everywhere; without phash grouping the
  same photo lands in train and test and you report a fake 0.98.
- **Group = duplicate cluster.** Entire clusters go to one split, so near-duplicates
  cannot leak.
- **`--wild-sources taco:0.3`** holds out 30% of TACO as an untouched, realistic test set.
  Report `--split test` *and* `--split wild`. The gap is your honest limitation slide.
- **Only 3 things are saved** in the checkpoint: weights, class names, preprocessing
  config. That makes the ONNX + `labels.json` pair self-sufficient.

---

## 7. Failure modes → fix

| Symptom | Likely cause | Fix |
|---|---|---|
| train acc 0.99, val 0.55 | leak or too few images | check `report.md` duplicate count; more data; stronger aug |
| val F1 stuck at ~0.4 for 5 epochs | backbone frozen too long / LR too high | `--freeze-epochs 0`, `--lr 1e-4` |
| `bottle` ↔ `bulb_tube_light` confusion | shape similarity, few bulb images | collect 100 bulb photos; `--balanced`; add `--img-size 320` |
| everything → `mixed_trash` | class imbalance + label noise in "trash" | cap `mixed_trash` at median class size; `--balanced` |
| int8 accuracy collapses | aggressive quantisation | ship fp32, or quantise per-channel / use QDQ static quantisation |
| good on val, bad in the demo | studio vs real backgrounds | add your phone photos; that's what `--split wild` measures |

---

## 8. Checklist before moving to the backend

- [ ] `data/report.md` shows every class ≥ 80 images and no `mixed_trash` blow-up.
- [ ] `--split test` macro-F1 reported, and `--split wild` reported next to it.
- [ ] `ewaste` recall ≥ 0.90 (safety) — if not, collect more e-waste and retrain.
- [ ] `errors.csv` read for the top 3 confusions; you can explain each one in the viva.
- [ ] `artifacts/waste_model_int8.onnx` argmax agreement = 100% vs PyTorch.
- [ ] `labels.json` contains Hindi and Marathi names (checked: `grep '"name_hi"' artifacts/labels.json`).
- [ ] `ml/predict.py` on 5 real photos gives sensible answers in < 50 ms.
