"""
Facility search: category-aware, cached, provider-abstracted.

FACILITY_PROVIDER=fixture  -> sample data, works offline (default; great for the demo)
FACILITY_PROVIDER=overpass -> live OpenStreetMap data (free, no API key)

The Overpass→category mapping is a heuristic: OSM tagging in India is patchy. That is why
the response carries `source` and the UI shows "sample data" / "OpenStreetMap" honestly.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import httpx

from . import db
from .config import ROOT, Settings
from .schemas import DirectionsResponse, Facility

log = logging.getLogger("waste.facilities")

FIXTURE_PATH = ROOT / "backend" / "fixtures" / "facilities.json"

# one query, then we classify by tags — fewer round-trips than one query per category
OVERPASS_QUERY = """
[out:json][timeout:25];
(
  nwr["amenity"="recycling"](around:{r},{lat},{lng});
  nwr["amenity"="waste_transfer_station"](around:{r},{lat},{lng});
  nwr["amenity"="waste_disposal"](around:{r},{lat},{lng});
  nwr["landuse"="landfill"](around:{r},{lat},{lng});
  nwr["shop"="scrap_yard"](around:{r},{lat},{lng});
  nwr["shop"="electronics"](around:{r},{lat},{lng});
  nwr["craft"="electronics_repair"](around:{r},{lat},{lng});
);
out center tags;
"""

YES = {"yes", "true", "1", "only"}


def google_directions_url(dest_lat: float, dest_lng: float,
                          origin_lat: float | None = None,
                          origin_lng: float | None = None) -> str:
    """A Google Maps directions link. With an origin, the route is already drawn."""
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&destination={dest_lat},{dest_lng}&travelmode=driving"
    )
    if origin_lat is not None and origin_lng is not None:
        url += f"&origin={origin_lat},{origin_lng}"
    return url


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def categories_for(tags: dict[str, str]) -> set[str]:
    """Map an OSM tag set to the waste categories this place plausibly accepts."""
    cats: set[str] = set()
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    craft = tags.get("craft", "")
    landuse = tags.get("landuse", "")

    if amenity in ("recycling", "waste_transfer_station", "waste_disposal"):
        cats.update({"recyclable", "general"})
    if landuse == "landfill" or amenity == "waste_transfer_station":
        cats.add("general")

    if tags.get("recycling:ewaste") in YES or tags.get("recycling:batteries") in YES:
        cats.add("ewaste")
    if shop in ("electronics", "computer", "mobile_phone", "second_hand") or craft == "electronics_repair":
        cats.add("ewaste")
    if tags.get("recycling:organic") in YES or tags.get("recycling:green_waste") in YES:
        cats.add("organic")
    if tags.get("recycling:hazardous") in YES or tags.get("hazardous") in YES:
        cats.add("hazardous")
    if tags.get("recycling:medical") in YES or tags.get("healthcare") == "waste":
        cats.add("biomedical")
    return cats


def _address(tags: dict[str, str]) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:suburb") or tags.get("addr:city"),
        tags.get("addr:postcode"),
    ]
    joined = ", ".join(p for p in parts if p)
    return joined or None


class FacilityService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.fixtures: list[dict[str, Any]] = []
        if FIXTURE_PATH.exists():
            try:
                self.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.exception("bad fixtures file %s", FIXTURE_PATH)
        log.info("facility provider=%s (%d fixtures)", settings.facility_provider, len(self.fixtures))

    # ------------------------------------------------------------------ public
    async def search(self, lat: float, lng: float, category: str, radius_m: int = 5000,
                     limit: int = 20, refresh: bool = False) -> tuple[list[Facility], str, bool, str | None]:
        provider = (self.settings.facility_provider or "auto").strip().lower()
        # Only an explicit fixture mode shows the bundled sample points. "auto" and
        # "overpass" ask OpenStreetMap for places around the user's real coordinates.
        if provider == "fixture":
            return self._from_fixtures(lat, lng, category, limit)

        d = radius_m / 111_000.0
        if not refresh:
            cached = db.cached_facilities(self.settings, category, lat, lng, d, d,
                                          self.settings.facility_cache_days)
            if cached:
                return self._rank(cached, lat, lng, limit)[:limit], "cache", False, None

        try:
            fetched = await self._overpass(lat, lng, radius_m)
            rows = [f for f in fetched if category in f["_cats"]]
            if rows:
                db.cache_facilities(self.settings, rows, db.now_iso())
                ranked = self._rank(rows, lat, lng, limit)[:limit]
                note = "Live OpenStreetMap places near you. Directions open in Google Maps."
                return ranked, "overpass", False, note
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.warning("overpass failed: %s", e)
            stale = db.cached_facilities(self.settings, category, lat, lng, d * 4, d * 4, 3650)
            if stale:
                return (
                    self._rank(stale, lat, lng, limit)[:limit],
                    "cache",
                    True,
                    "Live search failed, so these are cached places. Directions still open in Google Maps.",
                )

        if provider == "auto":
            near = self._nearby_fixtures(lat, lng, category, limit)
            if near:
                return (
                    near,
                    "fixture",
                    True,
                    "No live places in this category nearby. These sample points are within 30 km.",
                )
        return (
            [],
            "overpass",
            False,
            "No mapped collection points nearby. Use Open in Google Maps for live directions.",
        )

    async def get_by_id(self, facility_id: str) -> dict[str, Any] | None:
        for f in self.fixtures:
            if f["id"] == facility_id:
                return f
        with db.connect(self.settings) as con:
            row = con.execute("SELECT * FROM facilities WHERE id = ?", (facility_id,)).fetchone()
        return dict(row) if row else None

    async def directions(self, facility: dict[str, Any], lat: float | None, lng: float | None) -> DirectionsResponse:
        flat, flng = float(facility["lat"]), float(facility["lng"])
        url = google_directions_url(flat, flng, lat, lng)
        if lat is None or lng is None:
            return DirectionsResponse(facility_id=facility["id"], google_maps_url=url)

        osrm = f"{self.settings.osrm_url}/route/v1/driving/{lng},{lat};{flng},{flat}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(osrm, params={"overview": "false", "steps": "true"})
                r.raise_for_status()
                data = r.json()
            route = data["routes"][0]
            steps = []
            for s in (route.get("legs") or [{}])[0].get("steps", []):
                name = s.get("name") or ""
                kind = (s.get("maneuver") or {}).get("type", "")
                modifier = (s.get("maneuver") or {}).get("modifier", "")
                text = " ".join(x for x in [kind.replace("_", " "), modifier, name] if x).strip()
                if text:
                    steps.append(text[0].upper() + text[1:])
            return DirectionsResponse(
                facility_id=facility["id"],
                distance_m=round(float(route.get("distance", 0)), 1),
                duration_s=round(float(route.get("duration", 0)), 1),
                steps=steps[:12],
                google_maps_url=url,
                provider="osrm",
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            log.info("osrm failed (%s), returning google-maps link only", e)
            return DirectionsResponse(facility_id=facility["id"], google_maps_url=url)

    # ------------------------------------------------------------------ internals
    def _nearby_fixtures(self, lat, lng, category, limit, max_m: int = 30_000):
        """Sample points only count when they are actually near the user."""
        ranked = self._from_fixtures(lat, lng, category, limit)[0]
        return [f for f in ranked if (f.distance_m or 10**9) <= max_m]

    def _from_fixtures(self, lat, lng, category, limit):
        rows = [f for f in self.fixtures if category in f.get("categories", [f.get("category")])]
        if not rows:  # demo data is a fixed city; never show an empty map in a demo
            rows = list(self.fixtures)
        note = "Sample facility data for the demo - switch FACILITY_PROVIDER=overpass for live OSM data."
        return self._rank(rows, lat, lng, limit)[:limit], "fixture", True, note

    def _rank(self, rows: list[dict[str, Any]], lat: float, lng: float, limit: int) -> list[Facility]:
        out = []
        for r in rows:
            try:
                flat, flng = float(r["lat"]), float(r["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append(
                Facility(
                    id=str(r["id"]),
                    name=str(r.get("name") or "Unnamed collection point"),
                    category=str(r.get("category") or category_of_row(r)),
                    lat=flat,
                    lng=flng,
                    address=r.get("address"),
                    phone=r.get("phone"),
                    hours=r.get("hours"),
                    website=r.get("website"),
                    distance_m=int(haversine_m(lat, lng, flat, flng)),
                    source=str(r.get("source") or "osm"),
                )
            )
        out.sort(key=lambda f: f.distance_m or 10**9)
        return out

    async def _overpass(self, lat: float, lng: float, radius_m: int) -> list[dict[str, Any]]:
        q = OVERPASS_QUERY.format(r=int(radius_m), lat=lat, lng=lng)
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(self.settings.overpass_url, data={"data": q},
                                  headers={"User-Agent": "waste-assistant/0.1 (student project)"})
            r.raise_for_status()
            data = r.json()

        rows = []
        for el in data.get("elements", []):
            tags = el.get("tags") or {}
            center = el.get("center") or {}
            elat = el.get("lat", center.get("lat"))
            elng = el.get("lon", center.get("lon"))
            if elat is None or elng is None or not tags.get("name"):
                continue
            cats = categories_for(tags)
            if not cats:
                continue
            main = next((c for c in ("ewaste", "hazardous", "biomedical", "organic", "recyclable", "general")
                         if c in cats), "recyclable")
            rows.append({
                "id": f"osm:{el.get('type')}/{el.get('id')}",
                "name": tags["name"],
                "category": main,
                "lat": float(elat),
                "lng": float(elng),
                "address": _address(tags),
                "phone": tags.get("phone") or tags.get("contact:phone"),
                "hours": tags.get("opening_hours"),
                "website": tags.get("website") or tags.get("contact:website"),
                "source": "osm",
                "_cats": cats,
            })
        return rows


def category_of_row(row: dict[str, Any]) -> str:
    cats = row.get("categories")
    if isinstance(cats, list) and cats:
        return str(cats[0])
    return "recyclable"


def fixture_path() -> Path:
    return FIXTURE_PATH
