"""Seed realistic B2B flyer examples so the tool demos with real content.

Safe to re-run: it skips anything already present.

    python seed_examples.py
"""
import json
import sqlite3
from pathlib import Path

import crm
import serve

DB = Path(__file__).parent / "data" / "app.db"

TEAM = [
    ("mplante@local", "Marc Plante", "mac", "Sales"),
    ("swong@local", "Selina Wong", "expert", "Production"),
]

CLIENTS = [
    dict(name="Northgate Dental Supply", industry="Dental wholesale",
         phone="(416) 555-0142", email="orders@northgatedental.ca",
         city="Toronto", province="ON", status="active",
         note="Sells chairside consumables to clinics. Wants quarterly flyers "
              "to dentists across the GTA."),
    dict(name="Prairie AgriParts", industry="Farm equipment parts",
         phone="(306) 555-0178", email="sales@prairieagriparts.ca",
         city="Saskatoon", province="SK", status="active",
         note="Spring and autumn drops to working farms. Cares about farm "
              "counts more than total addresses."),
    dict(name="Coastal Linen Services", industry="Commercial laundry",
         phone="(604) 555-0119", email="hello@coastallinen.ca",
         city="Vancouver", province="BC", status="lead",
         note="Prospecting restaurants and hotels in Metro Vancouver."),
]

CONTACTS = {
    "Northgate Dental Supply": [("Priya Raman", "Marketing Lead", "priya@northgatedental.ca", 1)],
    "Prairie AgriParts": [("Doug Halvorsen", "Owner", "doug@prairieagriparts.ca", 1)],
    "Coastal Linen Services": [("Tomas Ricci", "Sales Director", "tomas@coastallinen.ca", 1)],
}

# Postal areas chosen to match each client's real target market.
CAMPAIGNS = [
    dict(client="Northgate Dental Supply", title="Q4 chairside consumables drop",
         date="2026-10-15", stage="design",
         areas=["M5G", "M5B", "M4W", "M2N", "L4G", "L3Y", "L5M", "L4C"],
         businesses=9840, farms=12,
         note="Targeting dental clinics in the GTA core plus York Region. "
              "Flyer is a two-sided 5x7 with a trade-show offer."),
    dict(client="Prairie AgriParts", title="Spring parts catalogue — SK farms",
         date="2026-11-02", stage="approved",
         areas=["S0K", "S0E", "S0G", "S0H"],
         businesses=2180, farms=406,
         note="Farm-weighted selection. Doug wants the farm count above 400."),
    dict(client="Coastal Linen Services", title="Hospitality prospecting — Metro Van",
         date="2026-11-20", stage="proposed",
         areas=["V6B", "V6C", "V6E", "V5K"],
         businesses=6420, farms=3,
         note="First drop for this client. Restaurants and hotels downtown."),
]

DESIGNS = {
    "Q4 chairside consumables drop": [
        ("Chairside flyer A", "in review", "https://example.com/proofs/northgate-a.pdf"),
    ],
    "Spring parts catalogue — SK farms": [
        ("Catalogue cover v1", "approved", "https://example.com/proofs/agriparts-v1.pdf"),
    ],
}

MESSAGES = {
    "Q4 chairside consumables drop": [
        ("mplante@local", "Design", "Client approved the area list — 9,840 businesses. "
                                    "Proof needed by the 8th please."),
        ("swong@local", "Sales", "Proof is up as v1. Logo scaled and the offer block "
                                 "moved to the front. Ready for client review."),
    ],
    "Spring parts catalogue — SK farms": [
        ("mplante@local", "", "Doug confirmed the farm count works. Moving to print."),
    ],
}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    crm.migrate(con)

    users = {r["email"]: r["id"] for r in con.execute("SELECT id, email FROM users")}
    for email, name, role, team in TEAM:
        if email in users:
            continue
        row = serve.create_user(con, email, "flyerdemo2026", role=role, name=name)
        con.execute("UPDATE users SET team = ? WHERE id = ?", (team, row["id"]))
        users[email] = row["id"]
        print(f"  user   {name} ({role}, {team})")
    con.commit()

    owner = users.get("mplante@local") or next(iter(users.values()))

    accounts = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM accounts")}
    for c in CLIENTS:
        if c["name"] in accounts:
            continue
        accounts[c["name"]] = crm.create_account(con, c, owner)
        print(f"  client {c['name']}")

    have = {r["name"] for r in con.execute("SELECT name FROM contacts")}
    for client, people in CONTACTS.items():
        for name, role, email, primary in people:
            if name in have or client not in accounts:
                continue
            crm.create_contact(con, dict(account_id=accounts[client], name=name,
                                         role=role, email=email, is_primary=primary))
            print(f"  contact {name}")

    camps = {r["title"]: r["id"] for r in con.execute("SELECT id, title FROM campaigns")}
    for c in CAMPAIGNS:
        if c["title"] in camps:
            continue
        cur = con.execute(
            """INSERT INTO campaigns (user_id, title, note, account_id, campaign_date,
                                      areas, businesses, farms, stage, assigned_to,
                                      created_at, modified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (owner, c["title"], c["note"], accounts.get(c["client"]), c["date"],
             json.dumps(c["areas"]), c["businesses"], c["farms"], c["stage"],
             users.get("swong@local"), crm.now(), crm.now()))
        camps[c["title"]] = cur.lastrowid
        print(f"  campaign {c['title']}  ({c['businesses']:,} biz / {c['farms']} farms)")
    con.commit()

    seen = {r["name"] for r in con.execute("SELECT name FROM designs")}
    for title, items in DESIGNS.items():
        for name, status, url in items:
            if name in seen or title not in camps:
                continue
            crm.create_design(con, dict(campaign_id=camps[title], name=name,
                                        status=status, url=url),
                              users.get("swong@local", owner))
            print(f"  design  {name} ({status})")

    body_seen = {r["body"] for r in con.execute("SELECT body FROM messages")}
    for title, msgs in MESSAGES.items():
        for email, to_team, body in msgs:
            if body in body_seen or title not in camps:
                continue
            crm.create_message(con, dict(campaign_id=camps[title], to_team=to_team, body=body),
                               users.get(email, owner))
            print(f"  message from {email} to {to_team or 'everyone'}")

    con.commit()
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("users", "accounts", "contacts", "campaigns", "designs", "messages")}
    print("\n  " + " | ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
