# Live scanning and real disposal locations

## AI scanning
The API uses the configured vision provider when available. In Render, add a
private `GEMINI_API_KEY` (recommended) or `GROQ_API_KEY` environment variable.
`VISION_PROVIDER=auto` selects Gemini first, then Groq. Without either key, the
API falls back to the bundled ONNX/CLIP models, which can be less accurate on
unfamiliar waste items. Never put provider keys in frontend files or GitHub.

## Real map locations
`FACILITY_PROVIDER=overpass` searches OpenStreetMap around the browser's actual
GPS coordinates. It does not substitute bundled demo locations when live search
fails. If the browser location permission is denied, the app asks the user to
enable it rather than silently searching Mumbai.

OpenStreetMap coverage and waste-category tags vary by area. A live search may
return no results even when a local facility exists but is not mapped/tagged.
Directions use OSRM when available and also provide a Google Maps directions
link to the returned facility coordinates.
