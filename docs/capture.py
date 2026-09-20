"""Drive the running tool in a real browser, exercising it end to end and
capturing the screenshots the guide needs.

Every shot is taken after the real interaction that produces it, so a failure
here is a failure in the tool, not in the capture.

    python docs/capture.py            (needs serve.py running on 8787)
"""
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# The tool's copy uses arrows and en-dashes; this console is cp1252.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8787"
OUT = Path(__file__).parent / "screenshots"
MANAGER = ("admin@local", "IhtoSwzdsBjh")
CONSULTANT = ("mplante@local", "flyerdemo2026")

results = []


def step(name):
    def wrap(fn):
        results.append((name, fn))
        return fn
    return wrap


def shot(page, filename, clip=None):
    page.wait_for_timeout(450)
    page.screenshot(path=str(OUT / filename), clip=clip)
    print(f"    captured {filename}")


def pick(page, field, listbox, typed, wanted):
    """Type into a combo and choose from its dropdown, the way a user does.

    The list overlays the Search button while open, so it has to be dismissed
    by selecting rather than left hanging."""
    page.fill(field, typed)
    try:
        page.wait_for_selector(f"{listbox} li", timeout=6000)
        option = page.locator(f"{listbox} li", has_text=wanted).first
        (option if option.count() else page.locator(f"{listbox} li").first).click()
    except PWTimeout:
        page.fill(field, wanted)          # no suggestions: the typed value stands
        page.keyboard.press("Escape")
    page.wait_for_selector(listbox, state="hidden", timeout=6000)


def sign_in(page, creds, portal="login"):
    page.goto(f"{BASE}/{portal}.html", wait_until="networkidle")
    page.fill("#email", creds[0])
    page.fill("#password", creds[1])
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/index.html", timeout=15000)
    page.wait_for_selector("#rows tr", timeout=15000)


def run(pw):
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                              device_scale_factor=2)
    page = ctx.new_page()
    problems = []

    def check(label, cond, detail=""):
        mark = "ok  " if cond else "FAIL"
        print(f"    [{mark}] {label}" + (f" — {detail}" if detail else ""))
        if not cond:
            problems.append(f"{label}: {detail}")

    # ---------------------------------------------------------- 01 login
    print("\n[1] consultant sign-in page")
    page.goto(f"{BASE}/login.html", wait_until="networkidle")
    check("portal names both consultant roles",
          "Media Account Consultants" in page.content())
    shot(page, "01-consultant-login.png")

    # ---------------------------------------------------------- 02 list
    print("\n[2] signing in as a consultant")
    sign_in(page, CONSULTANT)
    rows = page.locator("#rows tr").count()
    check("campaigns visible to the consultant", rows > 0, f"{rows} rows")
    check("stage column rendered", page.locator(".pill").count() > 0)
    shot(page, "02-campaign-list.png")

    # ---------------------------------------------------------- 03 date
    print("\n[3] creating a campaign")
    page.goto(f"{BASE}/campaign.html", wait_until="networkidle")
    page.wait_for_selector("#dateModal:not([hidden])", timeout=20000)
    check("date dialog opens on a new campaign", True)
    shot(page, "03-new-campaign-date.png")
    page.click("#dateSave")
    page.wait_for_selector("#dateModal", state="hidden", timeout=8000)

    # ---------------------------------------------------------- 04 lookup
    print("\n[4] business lookup — Dentists / GTA")
    page.wait_for_function("document.querySelectorAll('path.leaflet-interactive').length > 100",
                           timeout=60000)
    page.click("#tabBiz")
    pick(page, "#what", "#whatList", "Dentists", "Dentists")
    pick(page, "#where", "#whereList", "Greater Toronto", "Greater Toronto Area (GTA)")
    page.click("#doBiz")
    page.wait_for_selector("#bizSummary:not([hidden])", timeout=90000)
    summary = page.inner_text("#bizSummary")
    print(f"      summary: {summary}")
    check("search returned a summary", "postal area" in summary, summary[:70])
    check("results listed", page.locator(".brow").count() > 0,
          f"{page.locator('.brow').count()} rows")
    check("postal-area tags on results", page.locator(".fsa-tag").count() > 0)
    shot(page, "04-business-lookup.png")

    # Compare against the browser's own collation: the tool sorts with
    # numeric:true, so 1, 3, 20, 88 — not the "123 before 3D" a naive
    # lexicographic sort would give.
    names = page.locator(".brow b").all_inner_texts()
    ordered = page.evaluate(
        "ns => ns.slice().sort((a, b) =>"
        " a.localeCompare(b, 'en', {sensitivity: 'base', numeric: true}))", names)
    check("results alphabetical", names == ordered, f"first: {names[:2]}")

    # ------------------------------------------------------- 05 add areas
    print("\n[5] adding the postal areas")
    add = page.locator("#addAreas")
    check("add-areas button offered", add.is_visible(), add.inner_text())
    shot(page, "05-add-areas.png", clip=_panel_clip(page))
    add.click()
    page.wait_for_timeout(900)

    total = page.inner_text("#cTotal")
    areas = page.inner_text("#cAreas")
    print(f"      chips: total={total} areas={areas} farms={page.inner_text('#cFarms')}")
    check("areas landed in the selection", areas not in ("0", ""), f"{areas} areas")
    check("totals computed", total not in ("0", ""), f"{total} businesses")
    shot(page, "06-areas-selected.png")

    # ---------------------------------------------------- 07 region / farms
    print("\n[6] region + farm filter")
    page.click("#tabAreas")
    page.select_option("#filter", "farmheavy")
    page.wait_for_timeout(700)
    page.locator("#region").scroll_into_view_if_needed()
    check("farm filter applied", page.input_value("#filter") == "farmheavy")
    shot(page, "07-region-filter.png", clip=_panel_clip(page))

    # ------------------------------------------------ 08 design + thread
    print("\n[7] design panel and team thread")
    page.goto(f"{BASE}/index.html", wait_until="networkidle")
    page.wait_for_selector("#rows tr")
    page.locator("#rows a", has_text="Open").first.click()
    page.wait_for_selector("#crm:not([hidden])", timeout=60000)
    designs = page.locator("#designs .crm-row").count()
    msgs = page.locator("#thread .msg").count()
    check("design versions listed", designs > 0, f"{designs}")
    check("team thread has messages", msgs > 0, f"{msgs}")
    page.locator("#crm").scroll_into_view_if_needed()
    shot(page, "08-design-thread.png", clip=_el_clip(page, "#crm"))

    # ------------------------------------------------------- 09 client
    print("\n[8] client record")
    page.goto(f"{BASE}/clients.html", wait_until="networkidle")
    page.wait_for_selector("#rows tr")
    page.locator("#rows a", has_text="Northgate").first.click()
    page.wait_for_selector("#contacts .row", timeout=20000)
    check("client contacts listed", page.locator("#contacts .row").count() > 0)
    check("client campaigns listed", page.locator("#campaigns .row").count() > 0)
    check("activity timeline present", page.locator("#activities .tl").count() > 0)
    shot(page, "09-client-record.png")

    # ------------------------------------------------------- 10 manager
    print("\n[9] manager portal")
    page.click("#signout")
    page.wait_for_url(f"{BASE}/login.html", timeout=15000)
    sign_in(page, MANAGER, portal="manager")
    mrows = page.locator("#rows tr").count()
    check("manager sees the whole book", mrows >= rows, f"{mrows} vs consultant {rows}")
    check("manager badge shown", "MANAGER" in page.inner_text("#nav"))
    shot(page, "10-manager-view.png")

    browser.close()
    return problems


def _panel_clip(page):
    box = page.locator(".side").bounding_box()
    return {k: box[k] for k in ("x", "y", "width", "height")} if box else None


def _el_clip(page, sel):
    box = page.locator(sel).bounding_box()
    if not box:
        return None
    return {"x": max(box["x"] - 8, 0), "y": max(box["y"] - 8, 0),
            "width": box["width"] + 16, "height": min(box["height"] + 16, 1400)}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        try:
            issues = run(pw)
        except PWTimeout as exc:
            print(f"\nTIMED OUT: {str(exc)[:300]}")
            sys.exit(1)
    print("\n" + "=" * 60)
    files = sorted(p.name for p in OUT.glob("*.png"))
    print(f"{len(files)} screenshots in {OUT}")
    for f in files:
        print(f"   {f}")
    if issues:
        print(f"\n{len(issues)} problem(s) found while testing:")
        for i in issues:
            print(f"   - {i}")
        sys.exit(1)
    print("\nno problems found")
