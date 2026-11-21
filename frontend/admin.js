/* Kachra Mitra — admin panel. Plain JS, no build step.
 *
 * Flow: password -> POST /admin/login -> signed token in localStorage -> every read
 * carries `X-Admin-Token`. A 401 at any point drops the token and shows the login form
 * again, so a stale tab never silently shows old numbers as if they were live.
 */
(() => {
  "use strict";

  const OVERRIDE = localStorage.getItem("waste.apiBase");
  const DEPLOYED = (window.WASTE_API_BASE || "").trim().replace(/\/$/, "");
  const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  const SERVED_BY_API = LOCAL_HOST && /^\/(app|admin)/.test(location.pathname);
  const API = (OVERRIDE || (SERVED_BY_API ? location.origin : DEPLOYED) || location.origin)
    .replace(/\/$/, "");

  const TOKEN_KEY = "waste.adminToken";
  const state = { token: localStorage.getItem(TOKEN_KEY) || "", scansOffset: 0, fbOffset: 0, view: "scans" };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ---------------------------------------------------------------- helpers
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function pct(value, digits = 1) {
    return (Number(value || 0) * 100).toFixed(digits) + "%";
  }

  function when(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return esc(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + " min ago";
    if (diff < 86400) return Math.floor(diff / 3600) + " h ago";
    if (diff < 7 * 86400) return Math.floor(diff / 86400) + " d ago";
    return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
  }

  function catPill(cat) {
    const label = String(cat || "general");
    return `<span class="pill ${esc(label)}">${esc(label)}</span>`;
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (state.token) headers["X-Admin-Token"] = state.token;
    const res = await fetch(API + path, { ...options, headers });
    if (res.status === 401) {
      logout(true);
      throw new Error("Session expired — sign in again.");
    }
    if (!res.ok) {
      let detail = "HTTP " + res.status;
      try {
        const body = await res.json();
        detail = typeof body.detail === "string" ? body.detail : detail;
      } catch { /* not json */ }
      throw new Error(detail);
    }
    return res;
  }

  // ---------------------------------------------------------------- auth
  function showLogin(message = "") {
    $("#login-view").classList.remove("hidden");
    $("#dash-view").classList.add("hidden");
    $("#btn-export").classList.add("hidden");
    $("#btn-refresh").classList.add("hidden");
    $("#btn-logout").classList.add("hidden");
    $("#login-error").classList.toggle("hidden", !message);
    $("#login-error").textContent = message;
    $("#login-hint").textContent = "API: " + API;
  }

  function logout(expired = false) {
    state.token = "";
    localStorage.removeItem(TOKEN_KEY);
    showLogin(expired ? "Your session expired. Sign in again." : "");
  }

  async function login(event) {
    event.preventDefault();
    const btn = $("#login-btn");
    const password = $("#password").value;
    btn.disabled = true;
    $("#login-error").classList.add("hidden");
    try {
      const res = await fetch(API + "/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Login failed");
      state.token = body.token;
      localStorage.setItem(TOKEN_KEY, body.token);
      $("#password").value = "";
      await start();
    } catch (err) {
      $("#login-error").textContent = err.message || "Login failed";
      $("#login-error").classList.remove("hidden");
    } finally {
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------- render
  function renderStats(s) {
    $("#kpi-total").textContent = s.total_scans;
    $("#kpi-today").textContent = s.today;
    $("#kpi-yesterday").textContent = `yesterday: ${s.yesterday}`;
    $("#kpi-uncertain").textContent = s.uncertain;
    $("#kpi-uncertain-rate").textContent = pct(s.uncertain_rate) + " of scans";
    $("#kpi-corrections").textContent = s.feedback.corrections;
    $("#kpi-feedback").textContent = `${s.feedback.total} feedback rows`;
    $("#kpi-confidence").textContent = pct(s.avg_confidence, 0);
    $("#kpi-devices").textContent = s.devices;
    $("#kpi-images").textContent = s.with_images ? `${s.with_images} with photo` : "photos off";

    // trend
    const max = Math.max(1, ...s.trend.map((d) => d.n));
    $("#trend").innerHTML = s.trend.map((d) => {
      const h = Math.round((d.n / max) * 100);
      const title = `${d.day}: ${d.n} scan${d.n === 1 ? "" : "s"}`;
      return `<div class="bar ${d.n ? "" : "zero"}" style="height:${Math.max(4, h)}%" title="${esc(title)}"></div>`;
    }).join("");
    const first = s.trend[0]?.day.slice(5) || "";
    const last = s.trend[s.trend.length - 1]?.day.slice(5) || "";
    $("#trend-labels").innerHTML = `<span>${esc(first)}</span><span>${esc(last)}</span>`;

    // category mix
    const totalCat = s.by_category.reduce((sum, c) => sum + c.count, 0) || 1;
    $("#cat-mix").innerHTML = s.by_category.length
      ? s.by_category.map((c) => {
        const share = Math.round((c.count / totalCat) * 100);
        return `<div class="mix-row">
          <span>${esc(c.category)}</span>
          <div class="mix-track"><div class="mix-fill ${esc(c.category)}" style="width:${share}%"></div></div>
          <span class="num">${c.count}</span>
        </div>`;
      }).join("")
      : `<p class="muted small">No scans yet.</p>`;

    // top items
    $("#top-items").innerHTML = s.top_items.length
      ? s.top_items.map((i) => `<tr>
          <td>${esc(i.item)}</td>
          <td>${catPill(i.category)}</td>
          <td class="num">${i.count}</td>
          <td class="num">${pct(i.avg_confidence, 0)}</td>
          <td class="num">${i.uncertain}</td>
        </tr>`).join("")
      : `<tr><td colspan="5" class="empty">No scans recorded yet — run one from the app.</td></tr>`;
  }

  function renderScans(data) {
    $("#scans-count").textContent = `${data.total} result${data.total === 1 ? "" : "s"}`;
    $("#scans-body").innerHTML = data.scans.length
      ? data.scans.map((s) => `<tr>
          <td title="${esc(s.created_at)}">${when(s.created_at)}</td>
          <td>${esc(s.item)}${s.uncertain ? ' <span class="pill warn">unsure</span>' : ""}</td>
          <td>${catPill(s.category)}</td>
          <td class="num">${pct(s.confidence, 0)}</td>
          <td class="mono">${esc(s.device_id || "–")}</td>
          <td>${s.image_url ? `<a href="${esc(s.image_url)}" target="_blank" rel="noopener">open</a>` : '<span class="muted">–</span>'}</td>
        </tr>`).join("")
      : `<tr><td colspan="6" class="empty">Nothing here yet.</td></tr>`;

    const from = data.total ? data.offset + 1 : 0;
    const to = Math.min(data.offset + data.limit, data.total);
    $("#scans-page").textContent = `${from}–${to} of ${data.total}`;
    $("#scans-prev").disabled = data.offset <= 0;
    $("#scans-next").disabled = data.offset + data.limit >= data.total;
  }

  function renderFeedback(data) {
    $("#feedback-body").innerHTML = data.feedback.length
      ? data.feedback.map((f) => `<tr>
          <td title="${esc(f.created_at)}">${when(f.created_at)}</td>
          <td>${f.predicted_item ? esc(f.predicted_item) : '<span class="muted">–</span>'}</td>
          <td>${f.correct_item ? esc(f.correct_item) : '<span class="muted">–</span>'}
            ${f.agrees ? '<span class="pill ok">agreed</span>' : f.correct_item ? '<span class="pill warn">fixed</span>' : ""}</td>
          <td class="small">${f.comment ? esc(f.comment) : '<span class="muted">–</span>'}</td>
          <td class="mono">${esc(f.scan_id || "–")}</td>
        </tr>`).join("")
      : `<tr><td colspan="5" class="empty">No feedback yet. Use 👎 in the app to send one.</td></tr>`;

    const from = data.total ? data.offset + 1 : 0;
    const to = Math.min(data.offset + data.limit, data.total);
    $("#fb-page").textContent = `${from}–${to} of ${data.total}`;
    $("#fb-prev").disabled = data.offset <= 0;
    $("#fb-next").disabled = data.offset + data.limit >= data.total;
  }

  function renderModel(m) {
    const card = (title, rows) => `<div class="model-card">
      <h3>${esc(title)}</h3>
      <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v ?? "–")}</dd>`).join("")}</dl>
    </div>`;

    const yes = (b) => (b ? "yes" : "no");
    $("#model-cards").innerHTML = [
      card("Service", [
        ["version", m.version],
        ["images", yes(m.image_storage)],
        ["facilities", m.facilities_provider]
      ]),
      card("Classifier", [
        ["ready", yes(m.classifier.ready)],
        ["arch", m.classifier.arch],
        ["model", m.classifier.model],
        ["threshold", m.confidence_threshold],
        ["reason", m.classifier.reason]
      ]),
      card("CLIP head", [
        ["enabled", yes(m.clip.enabled)],
        ["model", m.clip.model],
        ["reason", m.clip.reason]
      ]),
      card("Vision + LLM", [
        ["vision", yes(m.vision.enabled)],
        ["provider", m.vision.provider],
        ["model", m.vision.model],
        ["llm", m.llm]
      ]),
      card("Taxonomy", [
        ["categories", m.taxonomy.categories],
        ["items", m.taxonomy.items]
      ])
    ].join("");
  }

  // ---------------------------------------------------------------- loaders
  async function loadStats() {
    const res = await api("/admin/stats?days=14");
    renderStats(await res.json());
  }

  async function loadScans() {
    const params = new URLSearchParams({ limit: "25", offset: String(state.scansOffset) });
    const category = $("#filter-category").value;
    const q = $("#filter-q").value.trim();
    if (category) params.set("category", category);
    if (q) params.set("q", q);
    const res = await api("/admin/scans?" + params.toString());
    renderScans(await res.json());
  }

  async function loadFeedback() {
    const params = new URLSearchParams({ limit: "25", offset: String(state.fbOffset) });
    const res = await api("/admin/feedback?" + params.toString());
    renderFeedback(await res.json());
  }

  async function loadModel() {
    const res = await api("/admin/model");
    renderModel(await res.json());
  }

  async function loadAll() {
    try {
      await Promise.all([loadStats(), loadScans(), loadFeedback(), loadModel()]);
    } catch (err) {
      if (state.token) console.error(err);
    }
  }

  // ---------------------------------------------------------------- start
  async function start() {
    if (!state.token) { showLogin(); return; }
    try {
      await api("/admin/session");
    } catch {
      return; // api() already switched to the login view
    }
    $("#login-view").classList.add("hidden");
    $("#dash-view").classList.remove("hidden");
    $("#btn-export").classList.remove("hidden");
    $("#btn-refresh").classList.remove("hidden");
    $("#btn-logout").classList.remove("hidden");
    await loadAll();
  }

  function showView(name) {
    state.view = name;
    $$(".admin-tab").forEach((b) => {
      const on = b.dataset.view === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    ["scans", "feedback", "model"].forEach((v) => {
      $("#view-" + v).classList.toggle("hidden", v !== name);
    });
  }

  // ---------------------------------------------------------------- events
  $("#login-form").addEventListener("submit", login);
  $("#btn-logout").addEventListener("click", () => logout(false));
  $("#btn-refresh").addEventListener("click", loadAll);

  $("#btn-export").addEventListener("click", async () => {
    try {
      const res = await api("/admin/export.csv");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "kachra-mitra-scans.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.message || "Export failed");
    }
  });

  $$(".admin-tab").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

  $("#filter-category").addEventListener("change", () => { state.scansOffset = 0; loadScans(); });
  let qTimer;
  $("#filter-q").addEventListener("input", () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.scansOffset = 0; loadScans(); }, 300);
  });
  $("#scans-prev").addEventListener("click", () => { state.scansOffset = Math.max(0, state.scansOffset - 25); loadScans(); });
  $("#scans-next").addEventListener("click", () => { state.scansOffset += 25; loadScans(); });
  $("#fb-prev").addEventListener("click", () => { state.fbOffset = Math.max(0, state.fbOffset - 25); loadFeedback(); });
  $("#fb-next").addEventListener("click", () => { state.fbOffset += 25; loadFeedback(); });

  start();
})();
