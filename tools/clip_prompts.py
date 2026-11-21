"""Prompt vocabulary for the MobileCLIP zero-shot waste classifier.

The ImageNet model can only answer with the 1,000 classes it was trained on. Several
important waste items are simply not in that list (battery, charger, bulb, circuit
board, chips packet, syringe), so a purely ImageNet app has holes exactly where safe
disposal matters most.

CLIP is trained to match *text* to *images*, so we can describe those items ourselves.
This module holds only the descriptions; `tools/build_clip_model.py` turns them into
text embeddings once, and `ml/clip_predict.py` compares them with a photo at runtime.
No torch, no network, no model download at runtime.

Rules for editing this file:

* keep every name in plain English (the encoder is English-only),
* do not add a prompt that describes something we would answer "not waste" for,
* prefer concrete physical descriptions ("a used AA battery") over brands.
"""
from __future__ import annotations

import re

# Extra descriptions per taxonomy item. These fill the gaps of ImageNet-1k.
EXTRA_NAMES: dict[str, list[str]] = {
    # ---- e-waste -----------------------------------------------------------
    "phone": ["smartphone", "mobile phone", "cell phone", "old cellphone", "touchscreen phone"],
    "laptop": ["laptop computer", "notebook computer", "laptop", "open laptop"],
    "monitor_tv": ["computer monitor", "television", "tv screen", "computer screen",
                   "flat screen monitor"],
    "printer": ["inkjet printer", "office printer", "scanner machine", "ink cartridge"],
    "charger_cable": ["phone charger", "usb cable", "power adapter", "charging cable",
                      "electric wire", "tangled cables"],
    "battery": ["aa battery", "lithium battery", "phone battery", "car battery",
                "dry cell battery", "used batteries"],
    "circuit_board": ["printed circuit board", "computer motherboard", "green circuit board",
                      "electronic circuit"],
    "bulb_tube_light": ["light bulb", "cfl bulb", "tube light", "fluorescent tube",
                        "led bulb", "broken light bulb"],
    "small_appliance": ["microwave oven", "toaster", "mixer grinder", "hair dryer",
                        "electric iron", "wifi router", "electric kettle"],
    # ---- recyclable --------------------------------------------------------
    "plastic_bottle": ["plastic water bottle", "cold drink bottle", "shampoo bottle",
                       "pet bottle", "empty plastic bottle"],
    "plastic_container": ["yogurt tub", "ice cream tub", "food container", "plastic bucket",
                          "plastic lunch box"],
    "plastic_film": ["plastic carry bag", "plastic bag", "bubble wrap", "shrink wrap",
                     "milk pouch", "plastic packaging film"],
    "paper": ["newspaper", "notebook page", "office paper", "envelope", "paper sheet",
              "crumpled paper"],
    "cardboard": ["shipping box", "cardboard carton", "cereal box", "corrugated box",
                  "brown cardboard box"],
    "glass_container": ["glass bottle", "glass jar", "jam jar", "beer bottle", "sauce bottle"],
    "metal_can": ["soda can", "cola can", "beverage can", "pepsi can", "coke can",
                  "aluminium can", "tin can"],
    "metal_scrap": ["metal foil", "piece of wire", "metal utensil", "iron piece",
                    "aluminium sheet", "scrap metal"],
    "tetra_pak": ["juice carton", "milk carton", "tetra pak", "drink carton"],
    "food_wrapper": ["chips packet", "snack wrapper", "candy wrapper", "plastic wrapper",
                     "biscuit packet", "empty chips packet"],
    # ---- organic -----------------------------------------------------------
    "food_waste": ["banana peel", "apple core", "fruit", "orange peel", "vegetable scraps",
                   "leftover food", "cooked rice", "bread", "rotten fruit"],
    "garden_waste": ["dry leaves", "grass clippings", "plant trimmings", "fallen leaves",
                     "twigs and leaves"],
    # ---- textile / rubber / ceramic ---------------------------------------
    "textile": ["old clothes", "shirt", "t-shirt", "jeans", "fabric", "cloth",
                "torn trousers"],
    "rubber_leather": ["old shoe", "rubber slipper", "leather sandal", "worn out sneaker",
                       "rubber tyre piece"],
    "ceramic": ["broken mug", "ceramic plate", "pottery shard", "flower pot",
                "broken ceramic cup"],
    # ---- biomedical --------------------------------------------------------
    "sanitary_waste": ["sanitary pad", "used diaper", "tampon", "baby diaper"],
    "dressing": ["bandage", "gauze pad", "face mask", "band aid", "cotton swab"],
    "syringe": ["medical syringe", "needle", "injection syringe", "syringe with needle"],
    "medicine": ["medicine bottle", "pill bottle", "tablet blister pack", "expired tablets",
                 "medicine strips"],
    # ---- hazardous ---------------------------------------------------------
    "paint_chemical": ["paint can", "chemical bottle", "pesticide container",
                       "leftover paint tin"],
    "mercury_item": ["thermometer", "cfl bulb", "mercury thermometer", "broken thermometer"],
    "aerosol": ["spray can", "deodorant can", "hair spray can", "insect repellent spray"],
    # ---- general -----------------------------------------------------------
    "mixed_trash": ["garbage", "trash", "rubbish", "mixed waste", "pile of garbage"],
}

# Phrase templates. One short generic phrase plus a few "used/broken" variants, which
# is what a waste app actually sees in the camera.
TEMPLATES: tuple[str, ...] = (
    "a photo of a {}",
    "a photo of {}",
    "a used {}",
    "a broken {}",
    "{} in the trash",
)

# Things a phone camera sees that are NOT waste. If one of these wins, the app says
# "I'm not sure this is waste" instead of inventing a disposal answer. This is the
# safety net that stops a dog from becoming "mixed trash".
NEGATIVE_PROMPTS: tuple[str, ...] = (
    "a photo of a dog",
    "a photo of a cat",
    "a photo of an animal",
    "a photo of a person",
    "a photo of a car",
    "a photo of a building",
    "a photo of a tree",
    "a photo of a plant",
    "a photo of a landscape",
    "a photo of a room",
    "a photo of a bird",
    "a photo of an insect",
    "a photo of the sky",
    "a photo of a bicycle",
    "a photo of a train",
    "a photo of a flower",
    "a photo of food on a plate",
    "a photo of a hand holding something",
    "a photo of a wall",
    "a photo of grass",
)

MAX_NAMES_PER_ITEM = 12


def clean_object_name(en: str) -> list[str]:
    """'Laptop / computer' -> ['Laptop', 'computer'] (drop parenthetical notes)."""
    s = re.sub(r"\([^)]*\)", "", en)
    return [p.strip() for p in s.split("/") if p.strip()]


def names_for_item(item) -> list[str]:
    """Every description we want to compare against, de-duplicated."""
    pool = clean_object_name(item.en) + list(EXTRA_NAMES.get(item.id, [])) + list(item.examples)
    seen: set[str] = set()
    out: list[str] = []
    for name in pool:
        name = name.strip().strip(".")
        if not name or any(ord(c) > 127 for c in name):
            continue  # the text encoder is English-only
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out[:MAX_NAMES_PER_ITEM]


def build_prompts(taxonomy) -> tuple[list[str], list[str]]:
    """Return (prompts, owners) where `owners[i]` is the taxonomy id of `prompts[i]`."""
    prompts: list[str] = []
    owners: list[str] = []
    for item in taxonomy.items.values():
        for name in names_for_item(item):
            for template in TEMPLATES:
                prompts.append(template.format(name))
                owners.append(item.id)
    return prompts, owners


def negative_prompts() -> list[str]:
    return list(NEGATIVE_PROMPTS)
