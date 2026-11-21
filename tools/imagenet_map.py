"""Map ImageNet class names onto the Kachra Mitra waste taxonomy.

The pretrained model knows 1,000 everyday object classes. This module decides which
of our 32 disposal items each class belongs to. Anything unmapped returns ``None`` so
the runtime can say "not sure" instead of confidently calling a dog "mixed trash".

Keep this file boring: explicit names first, then a few conservative rules. Review
`artifacts_pretrained/mapping_report.md` after regenerating.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- explicit
EXPLICIT: dict[str, str] = {
    # ---- e-waste -----------------------------------------------------------
    "laptop": "laptop",
    "desktop computer": "laptop",
    "hand-held computer": "laptop",
    "computer keyboard": "laptop",
    "mouse": "laptop",
    "joystick": "laptop",
    "monitor": "monitor_tv",
    "screen": "monitor_tv",
    "television": "monitor_tv",
    "home theater": "monitor_tv",
    "projector": "monitor_tv",
    "printer": "printer",
    "photocopier": "printer",
    "cellular telephone": "phone",
    "dial telephone": "phone",
    "pay-phone": "phone",
    "iPod": "small_appliance",
    "cassette player": "small_appliance",
    "CD player": "small_appliance",
    "tape player": "small_appliance",
    "radio": "small_appliance",
    "loudspeaker": "small_appliance",
    "microphone": "small_appliance",
    "modem": "small_appliance",
    "hard disc": "small_appliance",
    "remote control": "small_appliance",
    "electric fan": "small_appliance",
    "hand blower": "small_appliance",
    "iron": "small_appliance",
    "microwave": "small_appliance",
    "toaster": "small_appliance",
    "refrigerator": "small_appliance",
    "washer": "small_appliance",
    "dishwasher": "small_appliance",
    "vacuum": "small_appliance",
    "space heater": "small_appliance",
    "stove": "small_appliance",
    "rotisserie": "small_appliance",
    "waffle iron": "small_appliance",
    "Crock Pot": "small_appliance",
    "coffeepot": "small_appliance",
    "espresso maker": "small_appliance",
    "sewing machine": "small_appliance",
    "power drill": "small_appliance",
    "torch": "small_appliance",
    "table lamp": "small_appliance",
    "spotlight": "small_appliance",
    "switch": "small_appliance",
    "digital clock": "small_appliance",
    "analog clock": "small_appliance",
    "wall clock": "small_appliance",
    "digital watch": "small_appliance",
    "stopwatch": "small_appliance",
    "scale": "small_appliance",
    "oscilloscope": "small_appliance",
    "binoculars": "small_appliance",
    "cash machine": "monitor_tv",
    "vending machine": "monitor_tv",
    "traffic light": "small_appliance",
    # ---- recyclable --------------------------------------------------------
    "water bottle": "plastic_bottle",
    "pop bottle": "plastic_bottle",
    "beer bottle": "glass_container",
    "wine bottle": "glass_container",
    "beer glass": "glass_container",
    "goblet": "glass_container",
    "pitcher": "glass_container",
    "beaker": "glass_container",
    "measuring cup": "glass_container",
    "bottlecap": "metal_scrap",
    "milk can": "metal_scrap",
    "can opener": "metal_scrap",
    "barrel": "metal_scrap",
    "rain barrel": "plastic_container",
    "bucket": "plastic_container",
    "water jug": "plastic_container",
    "soap dispenser": "plastic_container",
    "lotion": "plastic_container",
    "sunscreen": "plastic_container",
    "perfume": "glass_container",
    "face powder": "plastic_container",
    "lipstick": "plastic_container",
    "carton": "tetra_pak",
    "packet": "food_wrapper",
    "plastic bag": "plastic_film",
    "balloon": "plastic_film",
    "envelope": "paper",
    "paper towel": "paper",
    "toilet tissue": "paper",
    "notebook": "paper",
    "comic book": "paper",
    "menu": "paper",
    "book jacket": "paper",
    "crossword puzzle": "paper",
    "file": "paper",
    "binder": "paper",
    "crate": "cardboard",
    "pencil box": "plastic_container",
    "street sign": "metal_scrap",
    # ---- glass / ceramic / metal ------------------------------------------
    "vase": "ceramic",
    "plate": "ceramic",
    "soup bowl": "ceramic",
    "mixing bowl": "ceramic",
    "cup": "ceramic",
    "coffee mug": "ceramic",
    "pot": "ceramic",
    "toilet seat": "ceramic",
    "washbasin": "ceramic",
    "bathtub": "ceramic",
    "frying pan": "metal_scrap",
    "wok": "metal_scrap",
    "Dutch oven": "metal_scrap",
    "caldron": "metal_scrap",
    "teapot": "metal_scrap",
    "ladle": "metal_scrap",
    "strainer": "metal_scrap",
    "screw": "metal_scrap",
    "nail": "metal_scrap",
    "chain": "metal_scrap",
    "brass": "metal_scrap",
    "hammer": "metal_scrap",
    "screwdriver": "metal_scrap",
    "hatchet": "metal_scrap",
    "cleaver": "metal_scrap",
    "shovel": "metal_scrap",
    "padlock": "metal_scrap",
    "combination lock": "metal_scrap",
    "safe": "metal_scrap",
    "radiator": "metal_scrap",
    "lawn mower": "metal_scrap",
    "chain saw": "metal_scrap",
    "shopping cart": "metal_scrap",
    "typewriter keyboard": "metal_scrap",
    # ---- textile / leather -------------------------------------------------
    "jean": "textile",
    "jersey": "textile",
    "sweatshirt": "textile",
    "cardigan": "textile",
    "kimono": "textile",
    "apron": "textile",
    "bib": "textile",
    "bikini": "textile",
    "maillot": "textile",
    "maillot tank suit": "textile",
    "miniskirt": "textile",
    "overskirt": "textile",
    "pajama": "textile",
    "poncho": "textile",
    "sarong": "textile",
    "suit": "textile",
    "swimming trunks": "textile",
    "trench coat": "textile",
    "vestment": "textile",
    "gown": "textile",
    "hoopskirt": "textile",
    "fur coat": "textile",
    "feather boa": "textile",
    "lab coat": "textile",
    "military uniform": "textile",
    "bulletproof vest": "textile",
    "brassiere": "textile",
    "bathing cap": "textile",
    "shower cap": "textile",
    "sock": "textile",
    "Christmas stocking": "textile",
    "teddy": "textile",
    "pillow": "textile",
    "quilt": "textile",
    "bath towel": "textile",
    "dishrag": "textile",
    "handkerchief": "textile",
    "prayer rug": "textile",
    "backpack": "textile",
    "purse": "textile",
    "wallet": "textile",
    "mailbag": "textile",
    "sleeping bag": "textile",
    "wool": "textile",
    "velvet": "textile",
    # ---- rubber / leather --------------------------------------------------
    "clog": "rubber_leather",
    "cowboy boot": "rubber_leather",
    "Loafer": "rubber_leather",
    "running shoe": "rubber_leather",
    "sandal": "rubber_leather",
    "shoe shop": "rubber_leather",
    # ---- biomedical --------------------------------------------------------
    "Band Aid": "dressing",
    "diaper": "sanitary_waste",
    "syringe": "syringe",
    "stethoscope": "medicine",
    "medicine chest": "medicine",
    "pill bottle": "medicine",
    "Petri dish": "dressing",
    "swab": "dressing",
    # ---- hazardous ---------------------------------------------------------
    "hair spray": "aerosol",
    "oil filter": "paint_chemical",
    "barometer": "mercury_item",
    # ---- general -----------------------------------------------------------
    "ashcan": "mixed_trash",
    "broom": "mixed_trash",
    "plunger": "mixed_trash",
    "candle": "mixed_trash",
    "matchstick": "mixed_trash",
    "lighter": "mixed_trash",
    "umbrella": "mixed_trash",
    "shopping basket": "mixed_trash",
    "hamper": "mixed_trash",
    "pencil sharpener": "mixed_trash",
    "rubber eraser": "mixed_trash",
    "ballpoint": "mixed_trash",
    "fountain pen": "mixed_trash",
    "rule": "mixed_trash",
    "wooden spoon": "mixed_trash",
    "spatula": "mixed_trash",
    "tray": "mixed_trash",
    "sunglasses": "mixed_trash",
    "sunglass": "mixed_trash",
    "lens cap": "mixed_trash",
    "magnetic compass": "mixed_trash",
    "wig": "mixed_trash",
    "hair slide": "mixed_trash",
    "gasmask": "mixed_trash",
    "potter's wheel": "mixed_trash",
}

# ImageNet indices are stable, so the messy food/nature block is easier by index.
FOOD_IDS = set(range(924, 970)) - {958, 968}  # 968 is "cup"
GARDEN_IDS = {958, 984, 985, 986, 988, 989, 990, 991, 992, 993, 994, 995, 996, 997, 987}


def item_for(idx: int, name: str) -> str | None:
    """Return a taxonomy item id, or None when the class is not a waste object."""
    if idx in FOOD_IDS:
        return "food_waste"
    if idx in GARDEN_IDS:
        return "garden_waste"

    n = name.lower().strip()
    if name in EXPLICIT:
        return EXPLICIT[name]

    # Conservative suffix rules for classes not named explicitly.
    if re.search(r"\b(shirt|sweater|trousers|trouser|dress|skirt|scarf|glove|mitten|hat|cap|sock|towel|blanket|curtain|rug|mat)\b", n):
        return "textile"
    if re.search(r"\b(shoe|boot|sandal|slipper)\b", n):
        return "rubber_leather"
    if re.search(r"\b(bottle|jar)\b", n):
        return "glass_container"
    if re.search(r"\b(bag)\b", n):
        return "plastic_film"
    if re.search(r"\b(can|tin)\b", n):
        return "metal_scrap"
    if re.search(r"\b(box)\b", n):
        return "cardboard"
    if re.search(r"\b(computer|keyboard|laptop|monitor|printer|telephone|phone|tablet)\b", n):
        return "laptop"
    if re.search(r"\b(camera|clock|watch|radio|speaker|headphone|lamp)\b", n):
        return "small_appliance"
    if re.search(r"\b(knife|blade|axe|tool|wrench|pliers)\b", n):
        return "metal_scrap"
    return None
