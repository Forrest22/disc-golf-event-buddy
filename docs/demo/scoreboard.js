// scoreboard.js -- all shared scoreboard logic for live and static builds.
// The embedding page provides either:
//   - fetchAndRender() call (live), or
//   - renderScores(SCORES) + hide loading (static)
// via the inline <script> block that runs after this file loads.

// -- Cookie helpers ------------------------------------------------
const Cookies = {
  get(name, fallback = null) {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    if (!match) return fallback;
    try {
      return JSON.parse(decodeURIComponent(match[1]));
    } catch {
      return fallback;
    }
  },
};

// -- Settings from cookies (set on landing page) -------------------
const SCROLL_PX_S = Cookies.get("scrollSpeed", 60);
const POLL_MS = Cookies.get("pollInterval", 30) * 1000;
const DIVISION_FILTER = new Set(Cookies.get("divisionFilter", []));
const PAUSE_AFTER_MOUSE_MS = 3000;
const SCROLL_DELAY_MS = 2000;

// -- Apply saved theme before paint (avoids flash) -----------------
if (Cookies.get("theme", "dark") === "light") {
  document.documentElement.classList.add("light");
}

// -- DOM refs ------------------------------------------------------
const track = document.getElementById("scroll-track");
const viewport = document.getElementById("scroll-viewport");
const loading = document.getElementById("loading");
const pausedBadge = document.getElementById("paused-badge");

// -- Scroll state --------------------------------------------------
let scrollY = 0;
let paused = false;
let lastMouseMove = 0;
let lastRender = null;
let totalHeight = 0;
let vpHeight = 0;
let scrollStartTime = null;

// -- Theme toggle --------------------------------------------------
function updateThemeBtn() {
  const light = document.documentElement.classList.contains("light");
  const btn = document.getElementById("theme-btn");
  if (btn) btn.textContent = light ? "\uD83C\uDF19 Dark" : "\u2600\uFE0F Light";
}
updateThemeBtn();

document.getElementById("theme-btn").addEventListener("click", () => {
  const nowLight = document.documentElement.classList.toggle("light");
  const val = nowLight ? "light" : "dark";
  document.cookie = `theme=${encodeURIComponent(JSON.stringify(val))};path=/;max-age=31536000`;
  updateThemeBtn();
});

// -- Render scores into the scroll track ---------------------------
function renderScores(data) {
  document.getElementById("event-name").textContent =
    data.event_name || "PDGA Event";
  document.getElementById("event-round").textContent = data.event_round || "";

  track.innerHTML = "";

  const divisions = (data.divisions || []).filter(
    (div) => DIVISION_FILTER.size === 0 || DIVISION_FILTER.has(div.code),
  );

  divisions.forEach((div) => {
    const el = document.createElement("div");
    el.className = "division";
    el.innerHTML = `
      <div class="division-header">${div.name} &mdash; ${div.round ? "Rd " + div.round : ""}</div>
      <table>
        <thead>
          <tr>
            <th style="width:52px">#</th>
            <th>Player</th>
            <th class="num" style="width:80px">Total</th>
            <th class="num" style="width:72px">Round</th>
            <th class="num" style="width:56px">Thru</th>
          </tr>
        </thead>
        <tbody>
          ${div.players
            .map(
              (p) => `
            <tr>
              <td class="place ${p.place === 1 ? "p1" : p.place === 2 ? "p2" : p.place === 3 ? "p3" : ""}">
                ${p.place === 1 ? "\uD83E\uDD47" : p.place === 2 ? "\uD83E\uDD48" : p.place === 3 ? "\uD83E\uDD49" : p.place_display}
              </td>
              <td class="name">
                ${p.name}
                ${p.country ? `<span class="country">${p.country}</span>` : ""}
              </td>
              <td class="score ${scoreClass(p.score)}">${p.score_display}</td>
              <td class="round-score ${scoreClass(p.score)}" style="opacity:0.65">${p.round_score}</td>
              <td class="thru">${p.thru}</td>
            </tr>
          `,
            )
            .join("")}
        </tbody>
      </table>
    `;
    track.appendChild(el);

    const spacer = document.createElement("div");
    spacer.className = "spacer";
    track.appendChild(spacer);
  });

  track.innerHTML += track.innerHTML;
  vpHeight = viewport.clientHeight;
  totalHeight = track.scrollHeight / 2;
}

function scoreClass(score) {
  if (score < 0) return "under";
  if (score > 0) return "over";
  return "even";
}

// -- Fetch & render (live mode only) -------------------------------
let pollTimer = null;

async function fetchAndRender() {
  try {
    const res = await fetch("/api/scores");
    const data = await res.json();
    const hasDivisions = data.divisions && data.divisions.length > 0;

    if (hasDivisions) {
      renderScores(data);
      loading.style.display = "none";
      if (scrollStartTime === null) scrollStartTime = performance.now();

      const fromCache = data.from_cache === true;
      const updatedEl = document.getElementById("last-updated");
      const endDate = data.end_date ? new Date(data.end_date) : null;
      const isOver = endDate && endDate < new Date();
      if (data.last_updated) {
        updatedEl.innerHTML =
          fromCache && !isOver
            ? `<span id="cache-badge">\u25CF Cached</span> as of ${data.last_updated} - fetching live...`
            : `Updated ${data.last_updated}`;
      } else {
        updatedEl.textContent = "";
      }
      clearTimeout(pollTimer);
      pollTimer = setTimeout(fetchAndRender, POLL_MS);
    } else {
      loading.style.display = "flex";
      loading.textContent =
        data.event_name === "Loading..."
          ? "Fetching scores from PDGA..."
          : `Loading ${data.event_name}...`;
      clearTimeout(pollTimer);
      pollTimer = setTimeout(fetchAndRender, 2000);
    }
  } catch (e) {
    console.error("Score fetch failed:", e);
    loading.style.display = "flex";
    loading.textContent = "Connection error - retrying...";
    clearTimeout(pollTimer);
    pollTimer = setTimeout(fetchAndRender, 3000);
  }
}

// -- Smooth scroll loop --------------------------------------------
function scrollLoop(ts) {
  const scrollReady =
    scrollStartTime !== null && ts - scrollStartTime >= SCROLL_DELAY_MS;
  if (lastRender !== null && !paused && scrollReady) {
    const delta = (ts - lastRender) / 1000;
    scrollY += SCROLL_PX_S * delta;
    if (totalHeight > 0 && scrollY >= totalHeight) scrollY -= totalHeight;
    track.style.transform = `translateY(-${scrollY}px)`;
  }
  if (paused && Date.now() - lastMouseMove > PAUSE_AFTER_MOUSE_MS) {
    paused = false;
    pausedBadge.classList.remove("visible");
  }
  lastRender = ts;
  requestAnimationFrame(scrollLoop);
}

// -- Mouse pause ---------------------------------------------------
document.addEventListener("mousemove", () => {
  lastMouseMove = Date.now();
  paused = true;
  pausedBadge.classList.add("visible");
});

// -- Start scroll loop ---------------------------------------------
requestAnimationFrame(scrollLoop);
