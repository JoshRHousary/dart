"""CRM layer: accounts, contacts, activities, designs and team messages.

Holds the schema and every query. serve.py owns HTTP; this module owns data,
so the two can be reasoned about separately.
"""
import json
import time

TEAMS = ["Sales", "Design", "Production", "Management"]

# Two sign-in portals map onto three roles.
ROLES = {
    "manager": {"label": "Manager", "portal": "manager",
                "blurb": "Every campaign, every client, plus team management."},
    "mac":     {"label": "Media Account Consultant", "portal": "consultant",
                "blurb": "Their own campaigns and any assigned to them."},
    "expert":  {"label": "Direct Mail Expert", "portal": "consultant",
                "blurb": "Their own campaigns and any assigned to them."},
}
MANAGER = "manager"


def is_manager(user):
    return user["role"] == MANAGER

STAGES = ["draft", "proposed", "approved", "design", "print", "mailed", "closed"]
ACCOUNT_STATUSES = ["lead", "active", "on hold", "inactive"]
DESIGN_STATUSES = ["draft", "in review", "approved", "sent to print"]
ACTIVITY_TYPES = ["call", "email", "meeting", "task", "note"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    street TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    province TEXT NOT NULL DEFAULT '',
    postcode TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'lead',
    owner_id INTEGER REFERENCES users(id),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL DEFAULT 'note',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    due_at TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS designs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    url TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    to_team TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_account ON contacts(account_id);
CREATE INDEX IF NOT EXISTS idx_activity_account ON activities(account_id);
CREATE INDEX IF NOT EXISTS idx_activity_campaign ON activities(campaign_id);
CREATE INDEX IF NOT EXISTS idx_designs_campaign ON designs(campaign_id);
CREATE INDEX IF NOT EXISTS idx_messages_campaign ON messages(campaign_id);
"""

# Columns added to tables serve.py created in an earlier version.
MIGRATIONS = [
    ("users", "team", "TEXT NOT NULL DEFAULT 'Sales'"),
    ("campaigns", "account_id", "INTEGER REFERENCES accounts(id)"),
    ("campaigns", "stage", "TEXT NOT NULL DEFAULT 'draft'"),
    ("campaigns", "assigned_to", "INTEGER REFERENCES users(id)"),
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def migrate(con):
    con.executescript(SCHEMA)
    for table, column, spec in MIGRATIONS:
        cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")
    # Earlier builds used master/user; fold them into the named roles.
    con.execute("UPDATE users SET role = 'manager' WHERE role = 'master'")
    con.execute("UPDATE users SET role = 'mac' WHERE role = 'user'")
    con.commit()


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------------ accounts

ACCOUNT_FIELDS = ("name", "phone", "email", "website", "industry", "street",
                  "city", "province", "postcode", "status", "note")


def list_accounts(con, q=""):
    sql = """
        SELECT a.*, u.email AS owner_email, u.name AS owner_name,
               (SELECT count(*) FROM campaigns c WHERE c.account_id = a.id) AS campaigns,
               (SELECT count(*) FROM contacts ct WHERE ct.account_id = a.id) AS contacts
        FROM accounts a LEFT JOIN users u ON u.id = a.owner_id
    """
    args = []
    if q:
        sql += (" WHERE a.name LIKE ? OR a.city LIKE ? OR a.phone LIKE ?"
                " OR a.industry LIKE ?")
        args = [f"%{q}%"] * 4
    sql += " ORDER BY a.modified_at DESC"
    return rows(con.execute(sql, args))


def get_account(con, account_id):
    acc = con.execute("""
        SELECT a.*, u.email AS owner_email FROM accounts a
        LEFT JOIN users u ON u.id = a.owner_id WHERE a.id = ?""", (account_id,)).fetchone()
    if not acc:
        return None
    out = dict(acc)
    out["contacts"] = rows(con.execute(
        "SELECT * FROM contacts WHERE account_id = ? ORDER BY is_primary DESC, name",
        (account_id,)))
    out["campaigns"] = rows(con.execute(
        """SELECT c.id, c.title, c.stage, c.campaign_date, c.businesses, c.farms,
                  c.modified_at, u.email AS owner
           FROM campaigns c LEFT JOIN users u ON u.id = c.user_id
           WHERE c.account_id = ? ORDER BY c.modified_at DESC""", (account_id,)))
    out["activities"] = rows(con.execute(
        """SELECT ac.*, u.name AS user_name, u.email AS user_email
           FROM activities ac JOIN users u ON u.id = ac.user_id
           WHERE ac.account_id = ? ORDER BY ac.created_at DESC LIMIT 100""", (account_id,)))
    return out


def create_account(con, data, owner_id):
    vals = [str(data.get(f, "") or "") for f in ACCOUNT_FIELDS]
    cur = con.execute(
        f"INSERT INTO accounts ({','.join(ACCOUNT_FIELDS)}, owner_id, created_at, modified_at)"
        f" VALUES ({','.join('?' * len(ACCOUNT_FIELDS))}, ?, ?, ?)",
        vals + [data.get("owner_id") or owner_id, now(), now()])
    con.commit()
    return cur.lastrowid


def update_account(con, account_id, data):
    vals = [str(data.get(f, "") or "") for f in ACCOUNT_FIELDS]
    con.execute(
        f"UPDATE accounts SET {', '.join(f + '=?' for f in ACCOUNT_FIELDS)},"
        f" owner_id=?, modified_at=? WHERE id=?",
        vals + [data.get("owner_id"), now(), account_id])
    con.commit()


def delete_account(con, account_id):
    con.execute("UPDATE campaigns SET account_id = NULL WHERE account_id = ?", (account_id,))
    con.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    con.commit()


# ------------------------------------------------------------------ contacts

def create_contact(con, data):
    cur = con.execute(
        """INSERT INTO contacts (account_id, name, role, email, phone, is_primary, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (data["account_id"], data.get("name", ""), data.get("role", ""),
         data.get("email", ""), data.get("phone", ""),
         1 if data.get("is_primary") else 0, now()))
    con.commit()
    return cur.lastrowid


def delete_contact(con, contact_id):
    con.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    con.commit()


# ---------------------------------------------------------------- activities

def create_activity(con, data, user_id):
    cur = con.execute(
        """INSERT INTO activities
           (account_id, campaign_id, user_id, kind, subject, body, due_at, done, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (data.get("account_id") or None, data.get("campaign_id") or None, user_id,
         data.get("kind", "note"), data.get("subject", ""), data.get("body", ""),
         data.get("due_at", ""), 1 if data.get("done") else 0, now()))
    con.commit()
    return cur.lastrowid


def toggle_activity(con, activity_id, done):
    con.execute("UPDATE activities SET done = ? WHERE id = ?", (1 if done else 0, activity_id))
    con.commit()


def open_tasks(con, user_id):
    return rows(con.execute(
        """SELECT ac.*, a.name AS account_name FROM activities ac
           LEFT JOIN accounts a ON a.id = ac.account_id
           WHERE ac.user_id = ? AND ac.kind = 'task' AND ac.done = 0
           ORDER BY ac.due_at""", (user_id,)))


# ------------------------------------------------------------------- designs

def list_designs(con, campaign_id):
    return rows(con.execute(
        """SELECT d.*, u.name AS user_name FROM designs d JOIN users u ON u.id = d.user_id
           WHERE d.campaign_id = ? ORDER BY d.version DESC, d.id DESC""", (campaign_id,)))


def create_design(con, data, user_id):
    nxt = con.execute("SELECT coalesce(max(version), 0) + 1 FROM designs WHERE campaign_id = ?",
                      (data["campaign_id"],)).fetchone()[0]
    cur = con.execute(
        """INSERT INTO designs (campaign_id, name, version, status, url, note, user_id, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (data["campaign_id"], data.get("name", "") or f"Version {nxt}", nxt,
         data.get("status", "draft"), data.get("url", ""), data.get("note", ""), user_id, now()))
    con.commit()
    return cur.lastrowid


def set_design_status(con, design_id, status):
    con.execute("UPDATE designs SET status = ? WHERE id = ?", (status, design_id))
    con.commit()


# ------------------------------------------------------------------ messages

def list_messages(con, campaign_id):
    return rows(con.execute(
        """SELECT m.*, u.name AS user_name, u.email AS user_email, u.team AS user_team
           FROM messages m JOIN users u ON u.id = m.user_id
           WHERE m.campaign_id = ? ORDER BY m.created_at""", (campaign_id,)))


def create_message(con, data, user_id):
    cur = con.execute(
        """INSERT INTO messages (campaign_id, account_id, user_id, to_team, body, created_at)
           VALUES (?,?,?,?,?,?)""",
        (data.get("campaign_id") or None, data.get("account_id") or None, user_id,
         data.get("to_team", ""), data.get("body", ""), now()))
    con.commit()
    return cur.lastrowid


def inbox(con, user):
    """Messages addressed to this user's team, or to every team, newest first."""
    return rows(con.execute(
        """SELECT m.*, u.name AS user_name, u.team AS user_team,
                  c.title AS campaign_title, c.id AS campaign_id
           FROM messages m
           JOIN users u ON u.id = m.user_id
           LEFT JOIN campaigns c ON c.id = m.campaign_id
           WHERE (m.to_team = ? OR m.to_team = '') AND m.user_id <> ?
           ORDER BY m.created_at DESC LIMIT 40""", (user["team"], user["id"])))


# --------------------------------------------------------------- aggregates

def dashboard(con, user):
    master = user["role"] == "master"
    scope = "" if master else " WHERE (c.user_id = ? OR c.assigned_to = ?)"
    args = [] if master else [user["id"], user["id"]]

    by_stage = rows(con.execute(
        f"SELECT c.stage, count(*) n, sum(c.businesses) biz, sum(c.farms) farms"
        f" FROM campaigns c{scope} GROUP BY 1", args))
    totals = con.execute(
        f"SELECT count(*) n, coalesce(sum(c.businesses),0) biz, coalesce(sum(c.farms),0) farms"
        f" FROM campaigns c{scope}", args).fetchone()
    return {
        "stages": {r["stage"]: r for r in by_stage},
        "campaigns": totals["n"],
        "businesses": totals["biz"],
        "farms": totals["farms"],
        "accounts": con.execute("SELECT count(*) FROM accounts").fetchone()[0],
        "open_tasks": len(open_tasks(con, user["id"])),
    }
