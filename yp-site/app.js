/* Shared helpers: API calls, session guard, top bar. */
(() => {
  "use strict";

  const api = async (path, opts = {}) => {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch { /* empty body */ }
    if (!res.ok) throw Object.assign(new Error(data.error || res.statusText), { status: res.status });
    return data;
  };

  const esc = s => String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const fmt = n => (n ?? 0).toLocaleString("en-CA");

  const fmtDate = s => {
    if (!s) return "—";
    const d = new Date(s.length <= 10 ? s + "T00:00:00" : s);
    return isNaN(d) ? s : d.toLocaleDateString("en-CA",
      { year: "numeric", month: "short", day: "numeric" });
  };

  /* Managers came in through their own portal; send them back to it. */
  const portalFor = () =>
    sessionStorage.getItem("dart_portal") === "manager" ? "/manager.html" : "/login.html";

  /* Redirects to the sign-in page when there is no session. */
  async function requireUser() {
    try {
      const { user } = await api("/api/auth/me");
      if (!user) { location.href = portalFor(); return null; }
      return user;
    } catch {
      location.href = portalFor();
      return null;
    }
  }

  function navbar(user, active) {
    const links = [
      ["/index.html", "Campaigns", "campaigns"],
      ["/clients.html", "Clients", "clients"],
    ];
    if (user.role === "manager") links.push(["/users.html", "Team", "team"]);

    document.getElementById("nav").innerHTML =
      '<div class="logo"><span class="dot">D</span>' +
      "<span><b>DART</b><small>Direct mail targeting</small></span></div>" +
      '<nav>' +
      links.map(([href, label, key]) =>
        '<a href="' + href + '"' + (key === active ? ' class="on"' : "") + ">" + label + "</a>").join("") +
      '<span>' + esc(user.name || user.email) +
      (user.team ? ' <span class="pill">' + esc(user.team) + "</span>" : "") +
      (user.role === "manager" ? ' <span class="pill pill-master">MANAGER</span>' : "") +
      "</span>" +
      '<button id="signout" type="button">Sign out</button></nav>';

    document.getElementById("signout").addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      const back = portalFor();
      try { sessionStorage.removeItem("dart_portal"); } catch { /* private mode */ }
      location.href = back;
    });
  }

  /* Sorts a table by clicking its headers; keys come from data-key. */
  function sortable(table, rows, render) {
    let key = null, dir = 1;
    table.querySelectorAll("th[data-key]").forEach(th => {
      th.addEventListener("click", () => {
        const k = th.dataset.key;
        if (k === key) dir = -dir; else { key = k; dir = 1; }
        table.querySelectorAll("th[data-key] .car").forEach(c => { c.textContent = "⇅"; });
        th.querySelector(".car").textContent = dir === 1 ? "▲" : "▼";
        rows.sort((a, b) => {
          const x = a[key], y = b[key];
          if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
          return String(x ?? "").localeCompare(String(y ?? ""), "en", { numeric: true }) * dir;
        });
        render();
      });
    });
  }

  window.App = { api, esc, fmt, fmtDate, requireUser, navbar, sortable };
})();
