# 02 — Dataset Plan

## 1. Decide the label space first

Mixing datasets only works if you pick one canonical taxonomy **before** you download a
gigabyte of images. Ours has **6 top-level categories** and **~35 item labels**, defined
in [`data/label_map.yaml`](../data/label_map.yaml) (machine-readable, single source of truth).

```text
ewaste      phones, chargers, batteries, circuit boards, bulbs/tubes, small appliances
recyclable  plastic bottles/containers/film, paper, cardboard, glass, metal, tetra-pak, textile
general     multi-layer wrappers, ceramics, rubber/leather, composite items, mixed trash
organic     food waste, garden waste
hazardous   paint, chemicals, aerosols, mercury items  (flag, can co-exist with a category)
biomedical  syringes, expired medicine, dressings, sanitary waste
```

Two design rules that save you pain later:

1. **Category ≠ item.** The model predicts the *item* (fine-grained); the category is
   looked up from the taxonomy. This lets you rename/merge items without retraining.
2. **Flags are orthogonal.** A CFL tube is `category: ewaste` + `flags: [hazardous]`.
   Do not create a "hazardous-ewaste" class — you will never have enough images.

---

## 2. Public datasets worth your time

| Dataset | Size | Labels | License / access | Why you want it | Gotcha |
|---|---|---|---|---|---|
| **TrashNet** (Thung & Yang, 2016) | 2,527 images | 6: glass, paper, cardboard, plastic, metal, trash | Public repo, check `LICENSE`; academic use is standard | The default baseline; clean, uniform 512px studio photos | Very clean backgrounds → optimistic accuracy. Never your only source |
| **TACO** (Trash Annotations in Context) | 1,500 images / 4,784 boxes | 60 litter categories, COCO JSON | CC BY 4.0 (annotations); images from Open Images/Flickr | Real clutter, outdoors, Indian-relevant litter | Multi-label per image; needs a "primary label" rule (largest/most central box) |
| **Garbage Classification (12 classes)** — Kaggle, Mostafa Abla | ~15,150 images | battery, biological, cardboard, clothes, glass (brown/green/white), metal, paper, plastic, shoes, trash | Kaggle license **varies — verify** | Only popular set with **battery** and **organic** in one place; bridges 3 → 6 categories | Glass is split by colour; remap. Duplicate/near-duplicate images exist |
| **RealWaste** (UCI ML Repo, 2023) | 4,752 images | cardboard, food organics, glass, metal, misc trash, paper, plastic, textile, vegetable organics | CC BY 4.0 | Real landfill photos (not studio); has organic + textile | 524×524, some blur; good "wild-ish" test material |
| **ZeroWaste** (CVPR 2022, Bashkirova et al.) | ~4,150 images (4,800 annotated) | 11 classes, detection + segmentation masks | CC BY 4.0 (research) | Truly cluttered recycling-plant scenes | Domain is industrial; use for robustness eval, not training only |
| **Open Images V7** (subset) | download only what you need | boxable classes: Mobile phone, Laptop, Television, Computer monitor, Microwave oven, Light bulb, Printer, Remote control, Keyboard, Mouse, Camera, Headphones, Tablet computer | CC BY 4.0 images / annotations | Cheap way to get thousands of **e-waste** photos with boxes | Not "waste" photos — devices in use. Crop the box → waste-ish. Verify class IDs at download |
| **COCO 2017** (subset) | ~5k of 118k | bottle, wine glass, cup, cell phone, laptop, keyboard, mouse, tv, microwave, toaster, book | CC BY 4.0 | Free, clean, well-annotated object crops | Same "in use, not discarded" bias |
| **Roboflow Universe** searches: "e-waste", "waste segregation india", "biomedical waste", "hazardous waste" | 300–5,000 each | YOLO/COCO export | Per-project (often CC BY 4.0) | Fastest source for **biomedical** and **hazardous**, which nobody else has | Quality varies wildly — always eyeball 30 random images before training |
| **Kaggle e-waste sets** (several) | 1k–10k | 6–10 e-waste subclasses | varies | Extra e-waste volume | Often scraped duplicates of Open Images; check for leakage |
| **Open Food Facts** (barcode, not images) | 3M+ products | packaging material, brand, quantity | ODbL | Barcode → packaging → recyclability hint | Crowd-sourced; confidence flags needed |

Skip: datasets that are just TrashNet re-uploads with renamed folders (you will find 20 of them).

---

## 3. Target label mapping (the merge table)

Full machine-readable version: `data/label_map.yaml`. The important rows:

| Source | Source label | → item id | → category | Note |
|---|---|---|---|---|
| trashnet | cardboard | `cardboard` | recyclable | |
| trashnet | paper | `paper` | recyclable | includes newspaper |
| trashnet | glass | `glass_container` | recyclable | |
| trashnet | plastic | `plastic_bottle` | recyclable | mostly bottles |
| trashnet | metal | `metal_scrap` | recyclable | |
| trashnet | trash | `mixed_trash` | general | heterogeneous — keep small |
| taco | Aluminium foil, Metal can, Pop tab, Scrap metal | `metal_can` / `metal_scrap` | recyclable | foil → `metal_scrap` |
| taco | Plastic bottle, Plastic film, Clear plastic bottle | `plastic_bottle` / `plastic_film` | recyclable | |
| taco | Glass bottle, Glass jar, Broken glass | `glass_container` | recyclable | broken glass → `flags:[sharps]` |
| taco | Cigarette, Styrofoam piece, Paper cup, Plastic straw | `mixed_trash` | general | |
| taco | Battery, Light bulb | `battery`, `bulb_tube_light` | ewaste | bulb also `hazardous` |
| taco | Food waste, Organic | `food_waste` | organic | |
| garbage12 | battery | `battery` | ewaste | + `hazardous` |
| garbage12 | biological | `food_waste` | organic | |
| garbage12 | clothes, shoes | `textile` | recyclable | reuse/donation first |
| garbage12 | brown/green/white-glass | `glass_container` | recyclable | colour info dropped |
| garbage12 | trash | `mixed_trash` | general | |
| realwaste | Misc. Trash | `mixed_trash` | general | |
| realwaste | Textile Trash | `textile` | recyclable | |
| realwaste | Food Organics, Vegetable Organics | `food_waste` | organic | |
| openimages | Mobile phone, Tablet, Laptop, Keyboard, Mouse, Printer, Computer monitor, Television | `phone`, `laptop`, `circuit_board`(from PCB crops), `monitor_tv` | ewaste | crop the box, add clutter |
| openimages | Light bulb | `bulb_tube_light` | ewaste | |
| openimages | Microwave oven, Toaster, Hair dryer | `small_appliance` | ewaste | |
| roboflow/indian | syringe, IV bottle, bandage, medicine strip, sanitary pad | `syringe`, `medicine`, `dressing`, `sanitary_waste` | biomedical | |
| roboflow/indian | paint can, pesticide bottle, aerosol, thermometer | `paint_chemical`, `aerosol`, `mercury_item` | hazardous | |

Deliberate merges: all glass colours → `glass_container`; all paper → `paper`;
energy bulbs *and* tube lights → `bulb_tube_light`; CFL/mercury thermometer →
`mercury_item` with `flags:[hazardous]`.

Deliberate splits: `battery` is its own item (not "e-waste generic") because Indian
Battery Waste Rules 2022 require separate handling and users search for it by name.

---

## 4. Merge pipeline (5 stages)

```text
raw/<source>/...                → 1. ingest    → manifest rows (path, source, original_label, license, sha256)
                                → 2. map       → canonical item + category + flags (via label_map.yaml)
                                → 3. clean     → decode check, min 200px, dedupe, drop faces/plates
                                → 4. split     → group-aware stratified 70/15/15
                                → 5. report    → counts per class, imbalance, leakage check
```

**Stage 1 — ingest.** Keep the raw archives untouched. One directory per source.
Build `data/manifest.csv`:

```csv
path,source,original_label,item,category,flags,license,sha256,phash,split
raw/trashnet/glass/glass1.jpg,trashnet,glass,glass_container,recyclable,,unknown,9f2c...,a1b2...,train
```

**Stage 2 — map.** Any source label not present in `label_map.yaml` **must fail loudly**
(`KeyError`), not silently become `general`. Silent fallback-to-general is how you end up
with a model that calls everything trash.

**Stage 3 — clean.**
- Reject images that don't decode, are < 200 px on the short side, or are grayscale+blank.
- **Deduplicate** with perceptual hash (DCT-based 64-bit pHash, implemented in
  `tools/build_manifest.py` — numpy only, no extra dependency), drop if
  Hamming distance ≤ 5 to an already-kept image. TrashNet re-uploads will otherwise
  put the same photo in train and test → 99% "accuracy" that collapses in the demo.
- **Cluster** near-duplicates (same bucket, distance ≤ 10) and treat the cluster as one
  group for splitting.
- Drop images with readable faces, licence plates, or house numbers (privacy + label noise).
- Cap per item: if `plastic_bottle` has 4,000 and `battery` has 300, downsample the big
  one to ~2.5× the median class size, or use class weights (do both if severe).

**Stage 4 — split.** 70 / 15 / 15, stratified by `item`, grouped by `phash` cluster
**and** by source-directory prefix (so one product's photo series never spans splits).
Keep an extra untouched `data/test_wild/` set: TACO + ZeroWaste + your own phone photos.
Report **two** numbers: in-domain test and wild test. The gap is the honest metric.

**Stage 5 — report.** Write `data/report.md` + `counts.csv`: per-class counts,
per-split counts, imbalance ratio, duplicate count, licence summary. Check it into git
(it's your evidence for the report/viva).

### Class-balance targets

| Category | Min viable | Comfortable | Rationale |
|---|---|---|---|
| recyclable | 2,500 | 6,000 | Largest, most visually diverse |
| ewaste | 1,000 | 2,500 | Safety-critical → needs recall |
| general | 800 | 2,000 | Easy to over-collect; keep hard examples |
| organic | 700 | 1,500 | Colour/texture overlaps with food packaging |
| hazardous | 250 | 800 | Scarce; pair with text/barcode hint |
| biomedical | 200 | 500 | Scarce & sensitive; augment + hint |
| **total** | **~5,500** | **~13,000** | Trainable in < 30 min on a free Colab T4 |

Per-item minimum: **80 images**, else merge the item upward until it clears 80.

---

## 5. Collecting local Indian waste images (the part that wins marks)

Public datasets are ~80% Western studio photos. Your demo will be judged on Indian
real-world photos. Plan for **600–1,000 self-collected images**.

**Who/what to shoot**

| Category | Where | Target |
|---|---|---|
| recyclable | your home/colony dry-waste bin, kirana packaging, milk packets, tetra-paks, cold-drink bottles | 300 |
| ewaste | old chargers, dead earbuds, remote, CFL, phone back covers, a friendly repair shop's scrap box (ask first) | 200 |
| general | chocolate wrappers, chip packets, broken bucket, ceramic shard, toothpaste tube | 200 |
| organic | kitchen peels, garden leaves, cooked food | 150 |
| hazardous | paint tin, mosquito-repellent refill, thermometer, bulb | 80 |
| biomedical | **do not collect physically** — use a pharmacy's return bin (photograph the bin/signage) or public datasets only | 40 or 0 |

**Capture protocol (write this into your report — it is methodology)**

1. 3 phones minimum (different sensors/colour processing), auto mode, flash off.
2. 4 conditions: indoor tube light, indoor warm light, outdoor shade, outdoor sun.
3. 3 distances: ~15 cm (macro), ~40 cm, ~80 cm; plus 2 angles each.
4. 2 backgrounds: plain floor/table + cluttered real bin/floor.
5. Include **occlusion** (partially covered), **multiple items**, and **in-hand** shots —
   these cause most real failures.
6. ≥ 20% "hard" negatives: clean recyclable next to dirty one, similar shapes
   (bottle vs bulb vs tube), transparent plastic.
7. Consent: ask before photographing anyone's bin/shop; no faces, no house numbers,
   no vehicle plates. Strip EXIF GPS. Record a one-line consent note per session.
8. Name files `in_<city>_<device>_<item>_<nn>.jpg`; log date/lighting/background in a CSV.

**Annotation.** Use **Label Studio** (free, local Docker) or **CVAT**. Label the *item*
(one per image), plus optional `flags` and a `quality` field (`good | blurry | occluded`).
QA: 10% double-annotated, target Cohen's κ ≥ 0.80 on item label; adjudicate disagreements.

**Active learning loop (cheap, impressive).** Log low-confidence scans (no images stored
by default — add an explicit "Help improve this" opt-in that uploads the image). Every
2 weeks, review ~50 opt-in images, correct labels, add to the training set. One slide of
this in your report is worth a lot.

**Barcode/text path (cheap accuracy win).** `GET https://world.openfoodfacts.org/api/v2/product/<ean>.json`
gives packaging material + categories for packaged food/drink. Use it as a *hint* that
raises classifier confidence, never as ground truth (crowd-sourced). Also cheap: if the
user types "old Nokia charger", pass the text to the LLM as a prior in the fusion step.

---

## 6. Licensing & attribution (do this from day one)

- Keep `data/SOURCES.md`: dataset name, URL, licence, date downloaded, what you changed.
- CC BY 4.0 (TACO, RealWaste, Open Images) → you **must** credit and indicate changes in
  your report and any public demo ("Model trained on TACO, RealWaste, Open Images V7 —
  see SOURCES.md").
- Kaggle sets: licence is per-dataset and sometimes "Unknown". If you cannot find a
  licence, use it for coursework but **do not redistribute the images or the trained
  weights publicly** without checking; prefer CC-licensed alternatives for a public demo.
- Do not scrape Google Images. It violates ToS and gives you near-duplicates + no licence.
- Keep a `NOT_FOR_COMMERCIAL_USE.md` note if any source is academic-only.

---

## 7. Metrics that matter (define now, measure in step 3)

| Metric | Why | Target |
|---|---|---|
| **Macro-F1** (6 categories) | Primary headline number; robust to imbalance | ≥ 0.80 |
| Per-class **recall** for `ewaste` + `hazardous` | Safety-critical misses | ≥ 0.90 |
| **Confusion matrix** (item + category) | Find the bottle↔bulb↔tube confusions | inspect before every release |
| **Top-2 accuracy** | The chat agent can ask "is it A or B?" | ≥ 0.92 |
| **Risk–coverage curve** | Accuracy vs abstain rate at thresholds 0.4–0.9 | choose the 0.60 operating point from it |
| **ECE** (calibration error) | Confidence shown to users must be honest | ≤ 0.08 |
| **Wild-set F1** | The real-world number | ≥ 0.65 in v1, and always reported next to in-domain |
| Inference latency (CPU) | UX | p95 ≤ 40 ms/model call at 224px int8 |

Report in-domain **and** wild. A slide that says "0.94 clean / 0.68 real-world, and here's
why" scores better than an unexplained 0.94.

---

## 8. Problem cases to design for explicitly

| Case | Handling |
|---|---|
| Multi-item photo (bin, pile) | classify the largest/most central object; UI hints "one item per photo" |
| Transparent plastic | strongest failure mode; oversample; add `plastic_film` vs `glass_container` hard pairs |
| Dirty/wet recyclable | still recyclable — do not let the model learn "dirty = general" |
| Composite (chips packet = plastic+foil) | `general`; explain multi-layer packaging in the answer |
| Broken CFL / swollen battery | hazard path, never a plain label |
| Unknown item | abstain + vision-LLM + one question; never guess with high confidence |

---

## 9. Do-this-now checklist

- [ ] Create `data/raw/` and download TrashNet + TACO + Garbage-12 + RealWaste.
- [ ] Copy `data/label_map.yaml`, extend with any extra labels you actually downloaded.
- [ ] Write `data/SOURCES.md` with licences.
- [ ] Shoot 60 photos per category on your own phone this week (fastest signal on domain gap).
- [ ] Run the merge pipeline in step 3 and print `counts.csv` — do not train before this looks sane.
- [ ] Freeze a `test_wild/` folder and never touch it until the final evaluation.
