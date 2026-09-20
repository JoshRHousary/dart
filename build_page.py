"""Render yp-taxonomy.json into the browsable index page.

Writes:
    yp-site/index.html   full HTML document, for the local server
    yp-page.html         body-only fragment, for publishing as an Artifact
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
data = json.loads((HERE / "yp-taxonomy.json").read_text(encoding="utf-8"))

cats = data["categories"]
leaves = [c for c in cats if c["level"] == "category"]
sections = [c for c in cats if c["level"] == "section"]
subs = [c for c in cats if c["level"] == "subsection"]
per_section = Counter(c["section"] for c in leaves)

payload = {
    "scrapedAt": data["scrapedAt"],
    "categories": {
        "label": "Categories",
        "facet": "section",
        "cols": [
            {"key": "name", "head": "Category (What)"},
            {"key": "section", "head": "Section"},
            {"key": "subsection", "head": "Subsection"},
            {"key": "id", "head": "YP ID", "cls": "id"},
        ],
        "rows": [
            {"name": c["name"], "section": c["section"], "subsection": c["subsection"], "id": c["id"]}
            for c in sorted(leaves, key=lambda c: (c["section"], c["subsection"], c["name"]))
        ],
    },
    "cities": {
        "label": "Cities",
        "facet": "province",
        "cols": [
            {"key": "city", "head": "City (Where)"},
            {"key": "province", "head": "Province"},
        ],
        "rows": [
            {"city": c, "province": p}
            for c, p in sorted({(l["city"], l["province"]) for l in data["locations"]})
        ],
    },
    "sections": {
        "label": "Sections",
        "cols": [
            {"key": "name", "head": "Section"},
            {"key": "count", "head": "Categories", "cls": "num"},
            {"key": "id", "head": "YP ID", "cls": "id"},
        ],
        "rows": [
            {"name": s["name"], "count": per_section.get(s["name"], 0), "id": s["id"]}
            for s in sorted(sections, key=lambda s: -per_section.get(s["name"], 0))
        ],
    },
    "subsections": {
        "label": "Subsections",
        "cols": [
            {"key": "name", "head": "Subsection"},
            {"key": "section", "head": "Section"},
            {"key": "id", "head": "YP ID", "cls": "id"},
        ],
        "rows": [
            {"name": s["name"], "section": s["section"], "id": s["id"]}
            for s in sorted(subs, key=lambda s: (s["section"], s["name"]))
        ],
    },
}

STYLE = """
  :root {
    --bg: #F2F5F1; --surface: #FFFFFF; --surface-2: #E9EEE7; --ink: #141A16;
    --muted: #5B665E; --line: #D3DCD2; --accent: #B0780A; --accent-soft: #F6ECD6;
    --deep: #2B5749; --shadow: 0 1px 2px rgba(20,26,22,.06);
    --sans: "Archivo", ui-sans-serif, system-ui, sans-serif;
    --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #11150F; --surface: #1A201B; --surface-2: #232B24; --ink: #E7EDE7;
      --muted: #97A49B; --line: #313A32; --accent: #E0A93B; --accent-soft: #33280F;
      --deep: #79B8A3; --shadow: 0 1px 2px rgba(0,0,0,.4);
    }
  }
  :root[data-theme="dark"] {
    --bg: #11150F; --surface: #1A201B; --surface-2: #232B24; --ink: #E7EDE7;
    --muted: #97A49B; --line: #313A32; --accent: #E0A93B; --accent-soft: #33280F;
    --deep: #79B8A3; --shadow: 0 1px 2px rgba(0,0,0,.4);
  }
  body { background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.5; }
  .wrap { max-width: 1100px; margin: 0 auto; padding-inline: 16px; padding-block: 0 56px; }
  header.top { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 20;
    background: var(--bg); border-bottom: 1px solid var(--line); padding-block: 18px 0; }
  h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -.015em; margin: 0; text-wrap: balance; }
  .sub { color: var(--muted); font-size: .84rem; margin: 3px 0 0; }
  .sub b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 14px; }
  input[type="search"] { flex: 1 1 220px; min-width: 0; font: inherit; color: var(--ink);
    background: var(--surface); border: 1px solid var(--line); border-radius: 7px; padding: 8px 11px; }
  input[type="search"]:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  button { font: inherit; font-size: .85rem; font-weight: 500; color: var(--ink);
    background: var(--surface); border: 1px solid var(--line); border-radius: 7px; padding: 8px 12px; cursor: pointer; }
  button:hover { border-color: var(--accent); }
  .tabs { display: flex; gap: 2px; margin-top: 14px; overflow-x: auto; }
  .tab { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: none;
    color: var(--muted); padding: 9px 13px; white-space: nowrap; }
  .tab .n { font-family: var(--mono); font-size: .78rem; opacity: .75; margin-left: 5px; }
  .tab[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 18px; }
  .chip { font-family: var(--mono); font-size: .74rem; padding: 5px 10px; border-radius: 99px;
    background: var(--surface); border: 1px solid var(--line); color: var(--muted); cursor: pointer; }
  .chip[aria-pressed="true"] { background: var(--deep); border-color: var(--deep); color: var(--bg); font-weight: 500; }
  .tablewrap { overflow-x: auto; margin-top: 16px; background: var(--surface);
    border: 1px solid var(--line); border-radius: 9px; box-shadow: var(--shadow); }
  table { border-collapse: collapse; width: 100%; font-size: .9rem; }
  th, td { text-align: left; padding: 8px 14px; border-bottom: 1px solid var(--line); }
  tbody tr:last-child td { border-bottom: 0; }
  th { position: sticky; top: 0; background: var(--surface-2); color: var(--muted); font-size: .72rem;
    font-weight: 600; text-transform: uppercase; letter-spacing: .07em; cursor: pointer;
    user-select: none; white-space: nowrap; z-index: 2; }
  th .arrow { opacity: .35; margin-left: 4px; }
  th[aria-sort] .arrow { opacity: 1; color: var(--accent); }
  td.id, td.num { font-family: var(--mono); font-variant-numeric: tabular-nums; color: var(--muted); font-size: .82rem; }
  tbody tr:hover { background: var(--surface-2); }
  .empty { padding: 28px 14px; text-align: center; color: var(--muted); font-size: .88rem; }
  footer { margin-top: 20px; color: var(--muted); font-size: .8rem; }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
"""

SCRIPT = r"""
(() => {
  "use strict";
  const DATA = __PAYLOAD__;
  const keys = ["categories", "cities", "sections", "subsections"];
  let active = keys[0], sortKey = null, sortDir = 1, facet = null;
  const CAP = 800;

  const el = id => document.getElementById(id);
  const tabsEl = el("tabs"), theadEl = el("thead"), tbodyEl = el("tbody");
  const chipsEl = el("chips"), emptyEl = el("empty"), footEl = el("foot"), qEl = el("q");

  keys.forEach(k => {
    const b = document.createElement("button");
    b.className = "tab"; b.type = "button"; b.setAttribute("role", "tab"); b.dataset.key = k;
    b.innerHTML = DATA[k].label + '<span class="n">' + DATA[k].rows.length.toLocaleString() + "</span>";
    b.addEventListener("click", () => { active = k; sortKey = null; facet = null; qEl.value = ""; render(); });
    tabsEl.appendChild(b);
  });

  const matching = () => {
    const set = DATA[active], q = qEl.value.trim().toLowerCase();
    let rows = set.rows.filter(r => {
      if (facet && r[set.facet] !== facet) return false;
      if (!q) return true;
      return set.cols.some(c => String(r[c.key] ?? "").toLowerCase().includes(q));
    });
    if (sortKey) {
      rows = rows.slice().sort((a, b) => {
        const x = a[sortKey] ?? "", y = b[sortKey] ?? "";
        if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir;
        return String(x).localeCompare(String(y), "en", { numeric: true }) * sortDir;
      });
    }
    return rows;
  };

  function render() {
    const set = DATA[active];
    [...tabsEl.children].forEach(b => b.setAttribute("aria-selected", b.dataset.key === active ? "true" : "false"));

    chipsEl.innerHTML = "";
    if (set.facet) {
      const counts = {};
      set.rows.forEach(r => { counts[r[set.facet]] = (counts[r[set.facet]] || 0) + 1; });
      Object.keys(counts).sort().forEach(v => {
        const c = document.createElement("button");
        c.className = "chip"; c.type = "button";
        c.textContent = v + " · " + counts[v];
        c.setAttribute("aria-pressed", facet === v ? "true" : "false");
        c.addEventListener("click", () => { facet = facet === v ? null : v; render(); });
        chipsEl.appendChild(c);
      });
    }

    const tr = document.createElement("tr");
    set.cols.forEach(c => {
      const th = document.createElement("th");
      th.textContent = c.head;
      if (sortKey === c.key) th.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
      const s = document.createElement("span");
      s.className = "arrow";
      s.textContent = sortKey === c.key ? (sortDir === 1 ? "↑" : "↓") : "↕";
      th.appendChild(s);
      th.addEventListener("click", () => {
        if (sortKey === c.key) sortDir = -sortDir; else { sortKey = c.key; sortDir = 1; }
        render();
      });
      tr.appendChild(th);
    });
    theadEl.replaceChildren(tr);

    const rows = matching(), shown = rows.slice(0, CAP);
    tbodyEl.replaceChildren(...shown.map(r => {
      const t = document.createElement("tr");
      set.cols.forEach(c => {
        const td = document.createElement("td");
        if (c.cls) td.className = c.cls;
        const v = r[c.key];
        td.textContent = (v === "" || v == null) ? "—" : v;
        t.appendChild(td);
      });
      return t;
    }));

    emptyEl.hidden = rows.length > 0;
    footEl.textContent = "Showing " + shown.length.toLocaleString() +
      (rows.length > shown.length ? " of " + rows.length.toLocaleString() + " matches (narrow the filter to see more)" :
        " of " + set.rows.length.toLocaleString() + " " + set.label.toLowerCase()) +
      (facet ? " · " + facet : "") + ".";
  }

  qEl.addEventListener("input", render);

  el("copy").addEventListener("click", async () => {
    const set = DATA[active];
    const esc = v => /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    const rows = matching();
    const csv = [set.cols.map(c => esc(c.head)).join(",")]
      .concat(rows.map(r => set.cols.map(c => esc(String(r[c.key] ?? ""))).join(",")))
      .join("\n");
    const btn = el("copy");
    try { await navigator.clipboard.writeText(csv); btn.textContent = "Copied " + rows.length.toLocaleString() + " rows"; }
    catch { btn.textContent = "Copy blocked"; }
    setTimeout(() => { btn.textContent = "Copy as CSV"; }, 1800);
  });

  el("theme").addEventListener("click", () => {
    const now = document.documentElement.getAttribute("data-theme");
    const dark = now ? now === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
  });

  render();
})();
"""

body = f"""<title>Category &amp; City Index</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{STYLE}</style>

<header class="top">
  <div class="wrap" style="padding-block:0">
    <h1>Category &amp; City Index</h1>
    <p class="sub">The complete YellowPages.ca directory structure —
      <b>{len(payload['categories']['rows']):,}</b> categories across
      <b>{len(sections)}</b> sections and <b>{len(subs)}</b> subsections,
      <b>{len(payload['cities']['rows']):,}</b> cities in 13 provinces and territories.</p>
    <div class="controls">
      <input type="search" id="q" placeholder="Filter rows…" autocomplete="off" aria-label="Filter rows">
      <button id="copy" type="button">Copy as CSV</button>
      <button id="theme" type="button">Theme</button>
    </div>
    <div class="tabs" id="tabs" role="tablist"></div>
  </div>
</header>

<div class="wrap">
  <div class="chips" id="chips"></div>
  <div class="tablewrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
  <div class="empty" id="empty" hidden>No rows match that filter.</div>
  <footer id="foot"></footer>
</div>

<script>{SCRIPT.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))}</script>
"""

(HERE / "yp-page.html").write_text(body, encoding="utf-8")

doc = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
  :root { color-scheme: light dark; }
  html, body { margin: 0; }
  img { max-width: 100%; }
  [hidden] { display: none !important; }
</style>
</head>
<body>
""" + body + "\n</body>\n</html>\n"

site = HERE / "yp-site"
site.mkdir(exist_ok=True)
(site / "taxonomy.html").write_text(doc, encoding="utf-8")

# Lookup lists for the map tool's what/where autocomplete.
lookup = {
    "categories": sorted({c["name"] for c in leaves}),
    "cities": [{"city": c, "province": p}
               for c, p in sorted({(l["city"], l["province"]) for l in data["locations"]})],
}
(site / "taxonomy-data.js").write_text(
    "window.YP_DATA = " + json.dumps(lookup, ensure_ascii=False) + ";\n", encoding="utf-8")

print(f"categories {len(payload['categories']['rows']):,} | cities {len(payload['cities']['rows']):,} | "
      f"sections {len(sections)} | subsections {len(subs)}")
print(f"wrote yp-page.html ({len(body):,} bytes), yp-site/taxonomy.html, yp-site/taxonomy-data.js")
