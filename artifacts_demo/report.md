# Evaluation — `test`

- arch: `mobilenet_v3_small` · level: `item` · images: **34**
- **accuracy**: 0.9706
- **macro-F1**: 0.9538
- weighted-F1: 0.9688
- top-2 accuracy: 1.0000
- ECE (15 bins): 0.6236
- abstain < 0.60: coverage 0.029 → accuracy on answered 1.0000

## Per-class

| class | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| mixed_trash | 3 | 1.000 | 0.667 | 0.800 |
| plastic_bottle | 6 | 0.857 | 1.000 | 0.923 |
| cardboard | 7 | 1.000 | 1.000 | 1.000 |
| glass_container | 6 | 1.000 | 1.000 | 1.000 |
| metal_scrap | 6 | 1.000 | 1.000 | 1.000 |
| paper | 6 | 1.000 | 1.000 | 1.000 |

## Calibration

| bin | n | mean conf | accuracy |
|---|---:|---:|---:|
| 0.20–0.27 | 8 | 0.248 | 1.000 |
| 0.27–0.33 | 16 | 0.297 | 0.938 |
| 0.33–0.40 | 3 | 0.393 | 1.000 |
| 0.47–0.53 | 3 | 0.498 | 1.000 |
| 0.53–0.60 | 3 | 0.574 | 1.000 |
| 0.67–0.73 | 1 | 0.671 | 1.000 |

## Risk–coverage

| coverage | accuracy |
|---:|---:|
| 0.1 | 1.000 |
| 0.2 | 1.000 |
| 0.3 | 1.000 |
| 0.4 | 1.000 |
| 0.5 | 1.000 |
| 0.6 | 1.000 |
| 0.7 | 1.000 |
| 0.8 | 0.963 |
| 0.9 | 0.967 |
| 1.0 | 0.971 |

## Read this before you present

- `mixed_trash` F1 0.800 (recall 0.667, n=3) — check `errors.csv` for what it is confused with.
- `plastic_bottle` F1 0.923 (recall 1.000, n=6) — check `errors.csv` for what it is confused with.
- `cardboard` F1 1.000 (recall 1.000, n=7) — check `errors.csv` for what it is confused with.
- Compare with `--split wild`: the gap is your real-world performance loss.
