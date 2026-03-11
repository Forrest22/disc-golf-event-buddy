// landing.js -- shared logic for live and static landing pages.
// The embedding page provides:
//   - initEvents() call (live: fetches API, static: renders from baked-in data)
// via the inline <script> block that runs after this file loads.

// Cookie helpers
const Cookies = {
  set(name, value) {
    const expires = new Date(Date.now() + 365 * 864e5).toUTCString();
    document.cookie = `${name}=${encodeURIComponent(JSON.stringify(value))}; expires=${expires}; path=/`;
  },
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

// Theme
function applyTheme(light) {
  document.body.classList.toggle("light", light);
  document.getElementById("theme-icon").textContent = light
    ? "\uD83C\uDF19"
    : "\u2600\uFE0F";
  document.getElementById("theme-label").textContent = light ? "Dark" : "Light";
  Cookies.set("theme", light ? "light" : "dark");
}
applyTheme(Cookies.get("theme", "dark") === "light");
document.getElementById("theme-toggle").addEventListener("click", () => {
  applyTheme(!document.body.classList.contains("light"));
});

// Date formatter
function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

// Settings sliders
const savedSpeed = Cookies.get("scrollSpeed", 60);
const savedPoll = Cookies.get("pollInterval", 30);
document.getElementById("scroll-speed").value = savedSpeed;
document.getElementById("scroll-speed-val").textContent = `${savedSpeed} px/s`;
document.getElementById("poll-interval").value = savedPoll;
document.getElementById("poll-interval-val").textContent = `${savedPoll}s`;

document.getElementById("scroll-speed").addEventListener("input", (e) => {
  const v = parseInt(e.target.value);
  document.getElementById("scroll-speed-val").textContent = `${v} px/s`;
  Cookies.set("scrollSpeed", v);
});
document.getElementById("poll-interval").addEventListener("input", (e) => {
  const v = parseInt(e.target.value);
  document.getElementById("poll-interval-val").textContent = `${v}s`;
  Cookies.set("pollInterval", v);
});

// Division checkboxes
const divisionFilter = new Set(Cookies.get("divisionFilter", []));

function renderDivisionCheckboxes(divs) {
  const grid = document.getElementById("div-grid");
  if (!divs.length) {
    grid.innerHTML = `<span style="color:var(--muted);font-size:13px;">No divisions found.</span>`;
    return;
  }
  grid.innerHTML = divs
    .map((d) => {
      const checked = divisionFilter.size === 0 || divisionFilter.has(d.code);
      return `<label class="div-check">
      <input type="checkbox" value="${d.code}" ${checked ? "checked" : ""} />
      <span>${d.code}</span>
    </label>`;
    })
    .join("");

  grid.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => {
      if (cb.checked) divisionFilter.add(cb.value);
      else divisionFilter.delete(cb.value);
      Cookies.set("divisionFilter", [...divisionFilter]);
    });
  });
}
