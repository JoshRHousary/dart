"""Crawl YellowPages.ca for its full city list and category heading tree.

The category tree has exactly three levels:
    Section (8000xxxx) -> Subsection (9000xxxx) -> Leaf category (00535000 etc.)

Writes yp-taxonomy.json next to this script.
"""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote

BASE = "https://www.yellowpages.ca"
DELAY = 0.35
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

SECTION_RE = re.compile(
    r'<h3 class="categories-title catTitle"><a href="/business/(\d+)\.html">(.*?)</a></h3>\s*'
    r'<ul class="categories-list">(.*?)</ul>', re.S)
ITEM_RE = re.compile(r'<li class="resp-list"><a[^>]*href="/business/(\d+)\.html"[^>]*>(.*?)</a></li>')
LIST_RE = re.compile(r'<ul class="categories-list">(.*?)</ul>', re.S)
CITY_RE = re.compile(r'href="(/locations/([^/"]+)/([^/"]+?)/?)"[^>]*>\s*([^<]{1,70}?)\s*<')
TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    return TAG_RE.sub("", text).replace("&amp;", "&").replace("&#39;", "'").strip()


def fetch(path, tries=3):
    url = path if path.startswith("http") else BASE + path
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-CA,en"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return ""


def crawl_locations(log):
    root = fetch("/locations/")
    provinces = sorted({m[1] for m in CITY_RE.findall(root)})
    log(f"provinces: {len(provinces)}")

    rows = []
    for prov in provinces:
        time.sleep(DELAY)
        try:
            html = fetch(f"/locations/{prov}/")
        except Exception as exc:
            log(f"  !! {prov}: {exc}")
            continue
        found = {}
        for path, p, city_slug, name in CITY_RE.findall(html):
            if p == prov:
                found[path] = name
        for path, name in found.items():
            rows.append({
                "province": unquote(prov).replace("-", " "),
                "city": clean(name),
                "path": path,
            })
        log(f"  {unquote(prov).replace('-', ' ')}: {len(found)}")
    return rows


def level_of(cat_id):
    """YP encodes the tier in the ID prefix."""
    if cat_id.startswith("8000"):
        return "section"
    if cat_id.startswith("9000"):
        return "subsection"
    return "category"


def crawl_categories(log):
    rows = []
    root = fetch("/business/")
    sections = SECTION_RE.findall(root)
    log(f"sections: {len(sections)}")

    subsections = []
    for sec_id, sec_name, body in sections:
        sec_name = clean(sec_name)
        rows.append({"id": sec_id, "name": sec_name, "level": "section",
                     "section": sec_name, "subsection": ""})
        for sub_id, sub_name in ITEM_RE.findall(body):
            sub_name = clean(sub_name)
            if sub_name.lower() == "view all":
                continue
            rows.append({"id": sub_id, "name": sub_name, "level": "subsection",
                         "section": sec_name, "subsection": ""})
            subsections.append((sub_id, sub_name, sec_name))

    log(f"subsections: {len(subsections)}")

    for i, (sub_id, sub_name, sec_name) in enumerate(subsections, 1):
        time.sleep(DELAY)
        try:
            html = fetch(f"/business/{sub_id}.html")
        except Exception as exc:
            log(f"  !! {sub_name}: {exc}")
            continue
        leaves = {}
        for block in LIST_RE.findall(html):
            for leaf_id, leaf_name in ITEM_RE.findall(block):
                name = clean(leaf_name)
                # Sidebar lists repeat sibling sections/subsections; keep only true leaves.
                if level_of(leaf_id) == "category" and name.lower() != "view all":
                    leaves[leaf_id] = name
        for leaf_id, leaf_name in leaves.items():
            rows.append({"id": leaf_id, "name": leaf_name, "level": "category",
                         "section": sec_name, "subsection": sub_name})
        log(f"  [{i}/{len(subsections)}] {sub_name[:40]:40s} {len(leaves):4d} categories")

    # Each section's own page lists every category in it, including any that sit
    # under no named subsection.
    seen = {r["id"] for r in rows}
    log("-- section pages --")
    for sec_id, sec_name_raw, _ in sections:
        sec_name = clean(sec_name_raw)
        time.sleep(DELAY)
        try:
            html = fetch(f"/business/{sec_id}.html")
        except Exception as exc:
            log(f"  !! {sec_name}: {exc}")
            continue
        added = 0
        for block in LIST_RE.findall(html):
            for leaf_id, leaf_name in ITEM_RE.findall(block):
                name = clean(leaf_name)
                if level_of(leaf_id) == "category" and name.lower() != "view all" and leaf_id not in seen:
                    seen.add(leaf_id)
                    rows.append({"id": leaf_id, "name": name, "level": "category",
                                 "section": sec_name, "subsection": ""})
                    added += 1
        log(f"  {sec_name[:40]:40s} +{added:4d} new")

    return rows


def main():
    here = Path(__file__).parent
    logf = (here / "yp-crawl.log").open("w", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    started = time.time()
    log("== PHASE 1: locations ==")
    locations = crawl_locations(log)
    log(f"cities: {len(locations)}")

    log("== PHASE 2: category headings ==")
    categories = crawl_categories(log)
    uniq = {c["id"]: c for c in categories}
    log(f"category rows: {len(categories)}  unique ids: {len(uniq)}")

    (here / "yp-taxonomy.json").write_text(json.dumps({
        "scrapedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": BASE,
        "locations": locations,
        "categories": sorted(uniq.values(), key=lambda c: (c["section"], c["subsection"], c["name"])),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"done in {time.time() - started:.0f}s")
    logf.close()


if __name__ == "__main__":
    main()
