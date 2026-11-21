/* Deployment config — edit this one line when the frontend and API are on different hosts.
 *
 *   Local (same server)        : leave it ""
 *   Vercel frontend + Render API: window.WASTE_API_BASE = "https://kachra-mitra-api.onrender.com";
 *
 * A per-browser override also exists for quick experiments:
 *   localStorage.setItem("waste.apiBase", "http://127.0.0.1:8000")
 */
window.WASTE_API_BASE = "https://kachra-mitra-api.onrender.com";

// Neon Managed Better Auth — public endpoint only (never put DB credentials here).
window.WASTE_NEON_AUTH_URL = "https://ep-green-scene-bijgdygu.neonauth.c-5.ap-southeast-1.aws.neon.tech/neondb/auth";
window.neonAuthReady = new Promise((resolve) => {
  if (window.KMNeonAuth) return resolve(window.KMNeonAuth);
  window.addEventListener("kachra-neon-auth-ready", () => resolve(window.KMNeonAuth), { once: true });
  window.addEventListener("kachra-neon-auth-error", (event) => resolve({ error: event.detail || "Neon Auth SDK failed to load" }), { once: true });
});
