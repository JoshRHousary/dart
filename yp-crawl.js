(async () => {
  const DELAY = 400;      // ms between requests — keep it polite
  const MAX_DEPTH = 3;    // category tree depth
  const MAX_PAGES = 1200; // safety cap

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = { scrapedAt: new Date().toISOString(), locations: [], categories: [], errors: [] };

  const getDoc = async path => {
    const res = await fetch(path, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(path + ' -> HTTP ' + res.status);
    return new DOMParser().parseFromString(await res.text(), 'text/html');
  };

  const links = (doc, re) => [...doc.querySelectorAll('a[href]')]
    .map(a => {
      let p;
      try { p = new URL(a.getAttribute('href'), location.origin).pathname; } catch { return null; }
      return { text: a.textContent.trim().replace(/\s+/g, ' '), path: p };
    })
    .filter(l => l && l.text && re.test(l.path));

  const save = () => {
    const b = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'yp-taxonomy.json';
    a.click();
  };

  // ---- PHASE 1: locations (provinces -> cities) ----
  console.log('%c PHASE 1: locations ', 'background:#fc0;color:#000');
  try {
    const provinces = links(await getDoc('/locations/'), /^\/locations\/[^\/]+\/?$/);
    console.log('Provinces found:', provinces.length, provinces.map(p => p.text));
    for (const p of provinces) {
      await sleep(DELAY);
      try {
        const cities = links(await getDoc(p.path), /^\/locations\/[^\/]+\/[^\/]+\/?$/);
        cities.forEach(c => out.locations.push({ province: p.text, city: c.text, path: c.path }));
        console.log('  ' + p.text + ': ' + cities.length + ' cities');
      } catch (e) { out.errors.push(e.message); console.warn('  ' + p.text, e.message); }
    }
  } catch (e) { out.errors.push('locations root: ' + e.message); console.error(e); }
  console.log('Total city rows:', out.locations.length);

  // ---- PHASE 2: categories (breadth-first over /business/) ----
  console.log('%c PHASE 2: categories ', 'background:#fc0;color:#000');
  const visited = new Set();
  const queue = [{ path: '/business/', name: '(root)', depth: 0 }];
  while (queue.length && visited.size < MAX_PAGES) {
    const node = queue.shift();
    if (visited.has(node.path)) continue;
    visited.add(node.path);
    await sleep(DELAY);
    try {
      const kids = links(await getDoc(node.path), /^\/business\/\d+\.html$/);
      for (const k of kids) {
        const id = k.path.match(/(\d+)\.html/)[1];
        out.categories.push({ name: k.text, id, parent: node.name, depth: node.depth + 1, path: k.path });
        if (node.depth + 1 < MAX_DEPTH && !visited.has(k.path)) {
          queue.push({ path: k.path, name: k.text, depth: node.depth + 1 });
        }
      }
      console.log('  [' + visited.size + '/' + MAX_PAGES + '] ' + node.name + ' -> ' + kids.length + ' (queue ' + queue.length + ')');
    } catch (e) { out.errors.push(e.message); console.warn('  ' + node.path, e.message); }
  }

  console.log('%c DONE ', 'background:#0a0;color:#fff',
    out.locations.length + ' city rows, ' + out.categories.length + ' category rows, ' + out.errors.length + ' errors');
  save();
})();
