"""Build the DART user guide as a PDF.

Screenshots go in docs/screenshots/ using the filenames in SHOTS below. Any
that are missing render as a labelled placeholder, so the guide is complete
and readable before every screenshot exists.

    python docs/build_guide.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

HERE = Path(__file__).parent
SHOT_DIR = HERE / "screenshots"
OUT = HERE / "DART-user-guide.pdf"

YELLOW = colors.HexColor("#FFD200")
BLACK = colors.HexColor("#1A1A1A")
GREY = colors.HexColor("#6E6E6E")
LINE = colors.HexColor("#DEDEDE")
BAND = colors.HexColor("#F4F4F4")
SOFT = colors.HexColor("#FFF6D0")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# filename -> caption shown under the image
SHOTS = {
    "01-consultant-login.png": "The consultant portal. Managers use a separate one.",
    "02-campaign-list.png": "Every campaign you own or have been assigned, with its stage and counts.",
    "03-new-campaign-date.png": "Creating a campaign starts by setting the in-home date.",
    "04-business-lookup.png": "Business lookup: a What and a Where, results A→Z with their postal area.",
    "05-add-areas.png": "The summary line converts a business search into a list of postal areas.",
    "06-areas-selected.png": "Selected areas fill yellow. The chips total businesses and farms live.",
    "07-region-filter.png": "Regions and the farm filter for agricultural targeting.",
    "08-design-thread.png": "Design versions and the team thread on a saved campaign.",
    "09-client-record.png": "The client record: contacts, campaigns and an activity timeline.",
    "10-manager-view.png": "The manager portal sees every campaign across the team.",
}


def styles():
    s = getSampleStyleSheet()
    base = dict(fontName="Helvetica", textColor=BLACK, leading=14.5)
    s.add(ParagraphStyle("Body2", parent=s["Normal"], fontSize=10, spaceAfter=7, **base))
    s.add(ParagraphStyle("H1", parent=s["Normal"], fontName="Helvetica-Bold",
                         fontSize=19, textColor=BLACK, spaceBefore=4, spaceAfter=9, leading=23))
    s.add(ParagraphStyle("H2", parent=s["Normal"], fontName="Helvetica-Bold",
                         fontSize=13, textColor=BLACK, spaceBefore=13, spaceAfter=6, leading=17))
    s.add(ParagraphStyle("Step", parent=s["Normal"], fontName="Helvetica-Bold",
                         fontSize=11, textColor=BLACK, spaceBefore=11, spaceAfter=5, leading=15))
    s.add(ParagraphStyle("Caption", parent=s["Normal"], fontName="Helvetica-Oblique",
                         fontSize=8.5, textColor=GREY, spaceBefore=4, spaceAfter=12,
                         alignment=TA_CENTER, leading=11))
    s.add(ParagraphStyle("Bullet2", parent=s["Normal"], fontSize=10, leftIndent=11,
                         bulletIndent=2, spaceAfter=4, **base))
    s.add(ParagraphStyle("CoverTitle", parent=s["Normal"], fontName="Helvetica-Bold",
                         fontSize=34, textColor=BLACK, leading=38, spaceAfter=10))
    s.add(ParagraphStyle("CoverSub", parent=s["Normal"], fontSize=12.5, textColor=GREY,
                         leading=19, spaceAfter=6))
    s.add(ParagraphStyle("Note", parent=s["Normal"], fontSize=9.5, textColor=BLACK,
                         leading=13.5, leftIndent=9, rightIndent=9,
                         spaceBefore=4, spaceAfter=4))
    return s


S = styles()


def para(text, style="Body2"):
    return Paragraph(text, S[style])


def bullets(items):
    return [Paragraph(t, S["Bullet2"], bulletText="•") for t in items]


def note(text):
    t = Table([[Paragraph(text, S["Note"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, YELLOW),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def table(rows, widths=None, head=True):
    data = [[Paragraph(f"<b>{c}</b>" if head and i == 0 else c, S["Body2"])
             for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths or [CONTENT_W / len(rows[0])] * len(rows[0]))
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if head:
        style += [("BACKGROUND", (0, 0), (-1, 0), BLACK),
                  ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        for r in range(2, len(data), 2):
            style.append(("BACKGROUND", (0, r), (-1, r), BAND))
    t.setStyle(TableStyle(style))
    return t


def shot(filename):
    """Image scaled to the text column, or a placeholder if not supplied yet."""
    path = SHOT_DIR / filename
    caption = SHOTS.get(filename, "")
    if path.exists():
        iw, ih = ImageReader(str(path)).getSize()
        w = CONTENT_W
        h = w * ih / iw
        max_h = PAGE_H - 2 * MARGIN - 40 * mm
        if h > max_h:
            h, w = max_h, max_h * iw / ih
        img = Image(str(path), width=w, height=h)
        img.hAlign = "CENTER"
        block = [img]
    else:
        ph = Table([[Paragraph(
            f'<font color="#9A9A9A"><b>Screenshot to add</b><br/>'
            f'<font size="8">docs/screenshots/{filename}</font></font>', S["Caption"])]],
            colWidths=[CONTENT_W], rowHeights=[38 * mm])
        ph.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BAND),
            ("BOX", (0, 0), (-1, -1), 1, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        block = [ph]
    if caption:
        block.append(Paragraph(caption, S["Caption"]))
    return KeepTogether(block)


# ------------------------------------------------------------------ chrome

def cover_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLACK)
    canvas.rect(0, PAGE_H - 78 * mm, PAGE_W, 78 * mm, fill=1, stroke=0)
    canvas.setFillColor(YELLOW)
    canvas.rect(0, PAGE_H - 82 * mm, PAGE_W, 4 * mm, fill=1, stroke=0)
    canvas.circle(MARGIN + 9 * mm, PAGE_H - 30 * mm, 9 * mm, fill=1, stroke=0)
    canvas.setFillColor(BLACK)
    canvas.setFont("Helvetica-Bold", 17)
    canvas.drawCentredString(MARGIN + 9 * mm, PAGE_H - 33 * mm, "D")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(MARGIN + 24 * mm, PAGE_H - 29 * mm, "DART")
    canvas.setFillColor(YELLOW)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(MARGIN + 24 * mm, PAGE_H - 34 * mm, "Direct mail targeting")
    canvas.setFillColor(BLACK)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawCentredString(PAGE_W / 2, 14 * mm, "Internal guide")
    canvas.restoreState()


def body_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(YELLOW)
    canvas.rect(0, PAGE_H - 9 * mm, PAGE_W, 9 * mm, fill=1, stroke=0)
    canvas.setFillColor(BLACK)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawString(MARGIN, PAGE_H - 6 * mm, "DART — USER GUIDE")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8.5 * mm, "Pinpointing businesses for B2B flyer campaigns")
    canvas.drawRightString(PAGE_W - MARGIN, 8.5 * mm, str(canvas.getPageNumber() - 1))
    canvas.restoreState()


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4,
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=MARGIN,
                          title="DART — User Guide",
                          author="Direct mail team",
                          subject="Pinpointing businesses for B2B flyer campaigns")
    frame_cover = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN - 62 * mm, id="cover")
    frame_body = Frame(MARGIN, 17 * mm, CONTENT_W, PAGE_H - 17 * mm - 13 * mm, id="body")
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[frame_cover], onPage=cover_page),
        PageTemplate(id="Body", frames=[frame_body], onPage=body_page),
    ])
    doc.build(story())
    print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
    missing = [f for f in SHOTS if not (SHOT_DIR / f).exists()]
    if missing:
        print(f"\n{len(missing)} of {len(SHOTS)} screenshots still to add, in docs/screenshots/:")
        for f in missing:
            # The console here is cp1252; captions contain arrows and dashes.
            caption = SHOTS[f].encode("ascii", "replace").decode()
            print(f"   {f:<28} {caption}")
    else:
        print("all screenshots present")


def story():
    f = []

    # ---------------------------------------------------------- cover
    f += [Spacer(1, 18 * mm),
          para("Finding the right<br/>businesses to mail", "CoverTitle"),
          para("A practical guide to building B2B flyer campaigns in DART — "
               "from a category search to a print-ready area list.", "CoverSub"),
          Spacer(1, 10 * mm),
          table([
              ["What this tool does", "Picks the postal areas your flyer should land in, "
                                      "based on the businesses actually in them"],
              ["Who it's for", "Media Account Consultants, Direct Mail Experts and Managers"],
              ["Data behind it", "1,478,832 Canadian businesses; 1,643 postal areas"],
          ], widths=[45 * mm, CONTENT_W - 45 * mm], head=False),
          NextPageTemplate("Body"), PageBreak()]

    # ---------------------------------------------------------- why
    f += [para("What this tool is for", "H1"),
          para("You are selling a flyer drop to a business — a dental wholesaler, a farm "
               "parts dealer, a commercial laundry. That client does not want to mail "
               "houses. They want their flyer in the hands of <b>other businesses</b>, "
               "and only the right ones."),
          para("The hard part has always been answering a simple question: "
               "<b>if we mail this area, how many of the client's actual prospects are in it?</b> "
               "DART answers that by holding two things side by side on one map — every "
               "business in Canada, and the postal areas mail is sold by."),
          para("So the pitch stops being “this area has 12,000 addresses” and becomes "
               "“this area has 340 dental clinics.” That is a different conversation."),
          note("<b>Businesses and farms only.</b> DART deliberately leaves out houses and "
               "apartments. Every count you see is commercial — that is the whole point of "
               "a B2B drop. Farms are counted separately because agricultural clients care "
               "about them specifically."),

          para("The three things it puts together", "H2"),
          table([
              ["Layer", "What it gives you"],
              ["Businesses", "1.48 million Canadian businesses with a street address, "
                             "searchable by category — dentists, restaurants, farms, "
                             "1,944 categories in all"],
              ["Postal areas", "1,643 Forward Sortation Areas — the first three characters "
                               "of a postal code, e.g. M5G — each with its own business and "
                               "farm count"],
              ["Campaigns", "A saved selection of areas with a client, a date, a stage, "
                            "artwork and a team conversation attached"],
          ], widths=[34 * mm, CONTENT_W - 34 * mm]),

          para("Two ways in", "H2"),
          para("There are two sign-in pages, and which one you use depends on your role."),
          table([
              ["Portal", "Who signs in here", "What they see"],
              ["/login.html", "Media Account Consultants, Direct Mail Experts",
               "Their own campaigns, plus any assigned to them"],
              ["/manager.html", "Managers", "Every campaign in the team, every client, "
                                            "and team management"],
          ], widths=[32 * mm, 52 * mm, CONTENT_W - 84 * mm]),
          shot("01-consultant-login.png"),
          PageBreak()]

    # ---------------------------------------------------------- tutorial
    f += [para("Tutorial: a flyer drop for a dental wholesaler", "H1"),
          para("We will build the campaign that ships with the tool as an example: "
               "<b>Northgate Dental Supply</b> sells chairside consumables and wants a "
               "flyer in front of dental clinics across the Greater Toronto Area."),
          para("The logic runs backwards from the client's customer. Their customer is a "
               "dental clinic. So we find the dental clinics, see which postal areas they "
               "cluster in, and mail those areas — rather than guessing at a radius."),

          para("Step 1 — Open a new campaign", "Step"),
          para("From the Campaigns screen, choose <b>+ Create a new Campaign</b>. The first "
               "thing it asks for is the in-home date: the day the flyer should land. "
               "Set it and save."),
          shot("02-campaign-list.png"),
          shot("03-new-campaign-date.png"),

          para("Step 2 — Find the client's prospects", "Step"),
          para("Switch the right-hand panel to <b>Business lookup</b>. This is the What and "
               "Where pair, the same shape as a directory search:"),
          *bullets([
              "<b>What</b> — the category your client sells to. Type “Dentists”. "
              "It autocompletes against all 1,944 categories.",
              "<b>Where</b> — a city, a province, or a wider area. Type “Greater Toronto "
              "Area” and pick it from the list.",
          ]),
          para("Press <b>Search</b>. Every matching business appears as a pin on the map and "
               "a row in the list, ordered A→Z, each tagged with the postal area it sits in."),
          shot("04-business-lookup.png"),

          para("Step 3 — Turn prospects into mailable areas", "Step"),
          para("Read the summary line above the results. It says something like:"),
          note("<b>4,176</b> dentists in Greater Toronto Area (GTA) · showing 1,200 · "
               "across <b>189</b> postal areas · A→Z"),
          para("That is the whole insight in one sentence. Those 4,176 clinics are not spread "
               "evenly — they sit in 189 specific postal areas, and some of those areas hold "
               "far more than others."),
          para("Underneath it is a button: <b>Add 189 postal areas to campaign</b>. Press it "
               "and every area containing a prospect joins your selection."),
          shot("05-add-areas.png"),
          note("The totals come from the <b>full</b> result set, not just the 1,200 rows "
               "loaded into the list. Adding 189 areas reflects all 4,176 dentists."),

          para("Step 4 — Trim the selection", "Step"),
          para("189 areas is usually too many to mail. Switch to the <b>Areas</b> tab, where "
               "each selected area is listed with its own counts, and cut it down:"),
          *bullets([
              "Click any area on the map to drop it from the selection, or use the × in the list.",
              "Click a row to zoom the map to that area's boundary.",
              "Use <b>Search by radius</b> to keep only what is near a chosen city.",
              "Watch the chips above the map — <b>Total</b>, <b>Farms</b>, <b>biz.</b> and "
              "<b>Areas</b> update on every change.",
          ]),
          para("Those chips are what you quote to the client. When the business count matches "
               "the budget, the selection is done."),
          shot("06-areas-selected.png"),

          para("Step 5 — Name it, link the client, save", "Step"),
          para("Below the map, give the campaign a title, pick the <b>Client</b> from the "
               "dropdown, set the <b>Stage</b>, and assign it to whoever picks it up next. "
               "Press <b>Save</b>."),
          table([
              ["Field", "What to put in it"],
              ["Title", "What the drop is, e.g. “Q4 chairside consumables drop”"],
              ["Client", "Links the campaign to a client record, so it appears on their page"],
              ["Stage", "draft → proposed → approved → design → print → mailed → closed"],
              ["Assigned to", "Hands it to a teammate — they immediately gain access to it"],
          ], widths=[30 * mm, CONTENT_W - 30 * mm]),
          PageBreak()]

    # ---------------------------------------------------------- farms
    f += [para("A second example: targeting farms", "H1"),
          para("<b>Prairie AgriParts</b> sells tractor parts in Saskatchewan. Their customer "
               "is a working farm, and a normal business count tells them nothing useful — "
               "a postal area full of offices is worthless to them."),
          para("This is why farms are counted separately everywhere in the tool."),

          para("How to build it", "Step"),
          *bullets([
              "In <b>Business lookup</b>, search What = “Farms”, Where = “Saskatchewan”.",
              "Or work from the map: on the <b>Areas</b> tab set the filter to "
              "<b>Farms only focus (10+ farms)</b>, which greys out every area without "
              "meaningful agricultural presence.",
              "Select the areas that remain and read the <b>Farms</b> chip.",
          ]),
          para("The seeded example lands on 4 postal areas holding <b>406 farms</b> alongside "
               "2,180 other businesses. The client's number is the 406."),
          shot("07-region-filter.png"),
          note("Rural postal areas have a <b>0</b> as their second character — S0K, K0K, J0B. "
               "If your farm selection is full of them, that is a good sign you are in the "
               "right place."),

          para("Picking areas by region", "H2"),
          para("The <b>Region</b> dropdown selects whole metro areas in one action — 26 of "
               "them, including the GTA, Lower Mainland, Greater Montreal, Calgary Region "
               "and the National Capital Region. Useful when a client says “all of the GTA” "
               "and you want the full footprint before trimming."),
          PageBreak()]

    # ---------------------------------------------------------- handoff
    f += [para("Handing the work between teams", "H1"),
          para("A flyer campaign passes through several hands. Once a campaign is saved, two "
               "panels appear beneath it that carry it the rest of the way."),

          para("Design", "H2"),
          para("Each artwork round is added as a version — v1, v2 — with a link to the proof "
               "and a status you can change inline: <b>draft</b>, <b>in review</b>, "
               "<b>approved</b>, <b>sent to print</b>. Everyone on the campaign sees the "
               "current state, so nobody mails a proof that was never signed off."),

          para("Team thread", "H2"),
          para("A conversation attached to the campaign itself, not scattered across email. "
               "Each message can be addressed to one team — Sales, Design, Production, "
               "Management — or to everyone, and shows the sender's team beside their name."),
          shot("08-design-thread.png"),
          note("<b>Assigning gives access.</b> A consultant cannot see a campaign that is "
               "not theirs. The moment it is assigned to them it appears in their list. "
               "That is how work moves between teams without opening everything to everyone."),

          para("The client record", "H2"),
          para("Every client has a page holding their details, their contacts, every campaign "
               "run for them, and a timeline of calls, emails, meetings, tasks and notes. "
               "Tasks carry a due date and can be ticked off."),
          para("Before a renewal call, this page is the whole history in one place: what you "
               "mailed, where, how many businesses it reached, and what was said."),
          shot("09-client-record.png"),
          PageBreak()]

    # ---------------------------------------------------------- manager
    f += [para("For managers", "H1"),
          para("Signing in through <b>/manager.html</b> shows every campaign in the team "
               "rather than just your own, with an Owner column and the stage of each."),
          shot("10-manager-view.png"),
          para("Managing the team", "H2"),
          para("The <b>Team</b> screen — visible only to managers — creates accounts. Each "
               "person gets a role and a team:"),
          table([
              ["Role", "Portal", "Access"],
              ["Manager", "/manager.html", "Every campaign, every client, team management"],
              ["Media Account Consultant", "/login.html", "Own campaigns and assigned ones"],
              ["Direct Mail Expert", "/login.html", "Own campaigns and assigned ones"],
          ], widths=[46 * mm, 32 * mm, CONTENT_W - 78 * mm]),
          para("The team — Sales, Design, Production or Management — is separate from the "
               "role. It decides who a thread message reaches, not what someone can see."),

          para("Reading the pipeline", "H2"),
          para("Stage colour on the campaigns list gives you the state of the book at a "
               "glance: grey while it is still being planned, yellow once it is in flight, "
               "black when it has been mailed or closed."),

          para("Where the numbers come from", "H1"),
          table([
              ["Source", "What it provides", "Licence"],
              ["Overture Maps", "1,478,832 Canadian businesses with addresses, categories, "
                                "phone numbers", "CDLA-Permissive 2.0"],
              ["Statistics Canada", "1,643 FSA boundaries from the 2021 Census",
               "Statistics Canada Open Licence"],
              ["OpenStreetMap", "Base map tiles", "ODbL"],
          ], widths=[34 * mm, CONTENT_W - 72 * mm, 38 * mm]),
          note("<b>One limit worth knowing.</b> DART works at postal-area (FSA) level, not "
               "Canada Post letter-carrier route level. An FSA is a district; a route is a "
               "single walk of a few hundred addresses. Use these counts to choose and pitch "
               "the target areas — then confirm the exact route selection and final price "
               "with Canada Post before the drop is booked."),
          Spacer(1, 6 * mm),
          para("Duplicate listings are merged automatically: the same business recorded twice "
               "under slightly different spellings or addresses is collapsed into one, keeping "
               "whichever record has the phone number and website. Counts you quote are of "
               "real distinct businesses.")]

    return f


if __name__ == "__main__":
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    build()
