# 07 — Maps and facility search

## 1. What the map is for

After a scan, the user knows **what** the item is and **how** to dispose of it. The last
mile is **where**: a dry-waste collection point, an e-waste take-back counter, a compost
site. The map answers that with the nearest few points for the item's category.

It is a *search* tool, not a directory of verified facilities. The UI says so.

## 2. Providers

| `FACILITY_PROVIDER` | Source | Key | Use |
|---|---|---|---|
| `fixture` (default) | `backend/fixtures/facilities.json` | none | offline demo, deterministic screenshots |
| `overpass` | OpenStreetMap via Overpass API | none | real data where OSM is mapped |

The provider is an interface: `FacilityService.search()` returns
`(facilities, source, stale, note)`. Google Places can slot in later behind the same call;
it would need a key and billing, which is why it is not the default.

## 3. The Overpass query

One request, several tags, then classification in Python — cheaper than one request per
category:

```overpassql
[out:json][timeout:25];
(
  nwr["amenity"="recycling"](around:5000,19.11,72.84);
  nwr["amenity"="waste_transfer_station"](around:5000,19.11,72.84);
  nwr["amenity"="waste_disposal"](around:5000,19.11,72.84);
  nwr["landuse"="landfill"](around:5000,19.11,72.84);
  nwr["shop"="scrap_yard"](around:5000,19.11,72.84);
  nwr["shop"="electronics"](around:5000,19.11,72.84);
  nwr["craft"="electronics_repair"](around:5000,19.11,72.84);
);
out center tags;
```

The response is filtered to elements with a `name` and at least one recognised tag, then
converted to a `Facility` with a haversine distance.

## 4. Tag → category mapping

| OSM tags | Categories |
|---|---|
| `amenity=recycling` / `waste_transfer_station` / `waste_disposal` | recyclable + general |
| `landuse=landfill`, `amenity=waste_transfer_station` | general |
| `recycling:ewaste=yes`, `recycling:batteries=yes` | ewaste |
| `shop=electronics`, `shop=computer`, `shop=mobile_phone`, `craft=electronics_repair` | ewaste |
| `recycling:organic=yes`, `recycling:green_waste=yes` | organic |
| `recycling:hazardous=yes`, `hazardous=yes` | hazardous |
| `recycling:medical=yes`, `healthcare=waste` | biomedical |

`shop=electronics` is a **take-back counter guess**. A phone shop may accept an old phone
and may not; the UI shows the tags as they are and never promises acceptance. This is the
honest limit of crowd-sourced mapping.

## 5. Caching

- results are stored in SQLite (`facilities` table) with `fetched_at`
- a bounding-box query (`lat ± dlat`, `lng ± dlng`) with a 30-day TTL
- `refresh=true` skips the cache
- if Overpass fails, the service returns **stale cache up to 10 years old** with
  `stale: true` and a note; the UI renders the note
- `FACILITY_CACHE_DAYS` controls the TTL

No PostGIS, no Redis, no tile server. At city scale this is enough.

## 6. Directions

Two layers, because routing is the part most likely to fail:

1. **OSRM demo server** (`router.project-osrm.org`) for distance, duration and turn-by-turn
   steps. Free, no key, best-effort; the public instance rate-limits.
2. **Google Maps deep link** built locally:
   `https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>&travelmode=driving`.
   Always works, opens the user's maps app.

If OSRM fails, the API returns the deep link with `provider: "none"` and empty steps. The
button still works.

## 7. India-specific reality check

- OSM coverage is good in Mumbai, Delhi, Bengaluru, Pune, Chennai, Hyderabad; thin elsewhere.
- Municipal "dry waste collection centres" are often **not mapped at all**.
- Kabadiwalas are informal and almost never in OSM; the app should not pretend otherwise.
- Brand take-back counters change; a `shop=electronics` pin is a lead, not a guarantee.

Therefore:

1. **Seed your own city.** Copy `fixtures/facilities.json`, replace the ten sample rows
   with real, verified points (name, address, phone, hours, category), keep `source` as
   `fixture` or `curated`. Ten accurate points beat 200 scraped guesses.
2. **Show the source.** `fixture` → yellow banner; `overpass` → "OpenStreetMap"; `cache` →
   "cached".
3. **Never show an empty screen.** If the result set is empty, say so and show the
   municipal helpline text.
4. **Verify before a demo.** Call the numbers, check the hours. A wrong address is worse
   than no address.

## 8. API

```powershell
curl.exe "http://127.0.0.1:8000/facilities?lat=19.11&lng=72.84&category=ewaste&radius_m=5000&limit=10"
```

```json
{
  "results": [
    {
      "id": "fixture:ewaste-01",
      "name": "Sample E-Waste Collection Centre (demo data)",
      "category": "ewaste",
      "lat": 19.1197, "lng": 72.8468,
      "address": "Midc Road, Andheri East, Mumbai 400093",
      "phone": "022-0000-0001",
      "hours": "Mo-Sa 10:00-18:00",
      "distance_m": 1293,
      "source": "fixture"
    }
  ],
  "source": "fixture",
  "stale": true,
  "note": "Sample facility data for the demo - switch FACILITY_PROVIDER=overpass for live OSM data."
}
```

`GET /facilities/{id}/directions?lat=..&lng=..` returns OSRM steps plus the Google Maps
URL.

## 9. Attribution and licences

- OpenStreetMap data: © OpenStreetMap contributors, **ODbL**. The map attribution is in
  the Leaflet tile layer and must stay visible.
- Overpass API: public instance, be polite (one query per search, 30 s timeout, cache).
- Leaflet: BSD-2-Clause.
- OSRM demo server: best-effort, not for production traffic. Self-host or switch to a paid
  router before launch.
