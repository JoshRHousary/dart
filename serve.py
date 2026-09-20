"""Direct-mail campaign tool: static site + JSON API.

Serves yp-site/ and provides:
  /api/auth/*       login, logout, current user
  /api/users        team management (manager role only)
  /api/campaigns    per-user saved campaigns
  /api/search       business lookup over the local Overture extract

    python serve.py [port]
"""
import json
import math
import os
import re
import sqlite3
import secrets
import sys
import threading
import time
from hashlib import scrypt
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import duckdb

import crm

HERE = Path(__file__).parent
PARQUET = (HERE / "data" / "places-ca.parquet").as_posix()
DB_PATH = HERE / "data" / "app.db"
WEB = HERE / "yp-site"

SESSION_DAYS = 14
COOKIE = "dart_session"

# Failed sign-ins, keyed on IP *and* the email being tried. Keying on IP alone
# would let one person's typos lock out a whole office behind a single NAT
# address; keying on email alone would let anyone lock out a named user.
LOGIN_WINDOW = 300
LOGIN_MAX = 10
_login_fails = {}
_login_lock = threading.Lock()


def login_blocked(key):
    cutoff = time.time() - LOGIN_WINDOW
    with _login_lock:
        hits = [t for t in _login_fails.get(key, ()) if t > cutoff]
        if hits:
            _login_fails[key] = hits
        else:
            _login_fails.pop(key, None)
        return len(hits) >= LOGIN_MAX


def note_login_failure(key):
    with _login_lock:
        _login_fails.setdefault(key, []).append(time.time())


def clear_login_failures(key):
    with _login_lock:
        _login_fails.pop(key, None)

# ---------------------------------------------------------------- categories

CATEGORY_MAP = [
    (r"dentist|dental|orthodont", ["dentist", "orthodontist", "dental_clinic"]),
    (r"pharmac|drug ?store", ["pharmacy", "drugstore"]),
    (r"hospital", ["hospital"]),
    (r"veterinar", ["veterinarian", "veterinary_care"]),
    (r"physician|doctor|medical clinic|walk-?in", ["doctor", "medical_clinic", "physician"]),
    (r"physiotherap", ["physical_therapist", "physiotherapist"]),
    (r"chiropract", ["chiropractor"]),
    (r"optic|optometr|eyewear", ["optometrist", "eyewear_and_opticians"]),
    (r"fast ?food|burger|take-?out", ["fast_food_restaurant", "burger_restaurant"]),
    (r"pizza", ["pizza_restaurant"]),
    (r"caf[eé]|coffee", ["cafe", "coffee_shop"]),
    (r"bakery|baker", ["bakery"]),
    (r"butcher", ["butcher_shop"]),
    (r"night ?club", ["nightclub"]),
    (r"bar\b|pub\b|tavern|brewer", ["bar", "pub", "brewery"]),
    (r"restaurant|dining|bistro|steakhouse", ["restaurant"]),
    (r"grocer|supermarket", ["grocery_store", "supermarket"]),
    (r"liquor|wine|spirits", ["liquor_store", "beer_wine_and_spirits"]),
    (r"bank|credit union", ["bank", "credit_union"]),
    (r"insurance", ["insurance_agency"]),
    (r"real.?estate|realtor", ["real_estate_agent", "real_estate"]),
    (r"lawyer|attorney|legal|barrister|notar", ["lawyer", "legal_services", "notary"]),
    (r"accountant|accounting|bookkeep", ["accountant", "accounting"]),
    (r"travel agenc", ["travel_agency"]),
    (r"motel", ["motel"]),
    (r"hotel|inn\b|lodging|resort", ["hotel", "resort"]),
    (r"hair|barber", ["hair_salon", "barber"]),
    (r"beauty|nail|esthetic", ["beauty_salon", "nail_salon"]),
    (r"spa\b", ["spa"]),
    (r"gym|fitness|yoga|pilates", ["gym", "fitness_center", "yoga_studio"]),
    (r"dry ?clean|laundr", ["dry_cleaning", "laundry_service", "laundromat"]),
    (r"funeral|cremat", ["funeral_home", "funeral_services"]),
    (r"florist|flower", ["florist"]),
    (r"jewel", ["jewelry_store"]),
    (r"shoe|footwear", ["shoe_store"]),
    (r"clothing|apparel|fashion|boutique", ["clothing_store", "fashion"]),
    (r"furniture|mattress", ["furniture_store", "mattress_store"]),
    (r"hardware|building suppl|lumber", ["hardware_store", "home_improvement"]),
    (r"book", ["bookstore"]),
    (r"pet|kennel|groom", ["pet_store", "pet_groomer"]),
    (r"cell ?phone|mobile phone", ["mobile_phone_store"]),
    (r"computer|electronic", ["electronics_store", "computer_store"]),
    (r"car ?wash", ["car_wash"]),
    (r"tire|tyre", ["tire_shop"]),
    (r"auto.*(repair|service|body|mechanic)|mechanic|garage", ["auto_repair", "car_repair"]),
    (r"car dealer|auto.*dealer|used cars", ["car_dealer", "auto_dealer"]),
    (r"gas ?(bar|station)|fuel|petrol", ["gas_station"]),
    (r"day ?care|child ?care|kindergarten", ["child_care", "daycare"]),
    (r"college|universit", ["college_university"]),
    (r"school|academy|tutor", ["school"]),
    (r"librar", ["library"]),
    (r"church|mosque|synagogue|temple|worship", ["religious_organization", "church"]),
    (r"bicycle|bike", ["bicycle_store"]),
    (r"golf", ["golf_course"]),
    (r"sport|athletic", ["sporting_goods", "sports_club"]),
    (r"toy|hobby", ["toy_store", "hobby_store"]),
    (r"gift|souvenir", ["gift_shop"]),
    (r"galler", ["art_gallery"]),
    (r"museum", ["museum"]),
    (r"cinema|movie|theatre|theater", ["cinema", "performing_arts"]),
    (r"plumb", ["plumber"]),
    (r"electric(ian|al contract)", ["electrician"]),
    (r"roof", ["roofing_contractor", "roofer"]),
    (r"paint", ["painter", "painting_contractor"]),
    (r"hvac|heating|air ?condition|furnace", ["hvac_services", "heating_and_air_conditioning"]),
    (r"landscap|lawn|garden centre", ["landscaping", "garden_center"]),
    (r"clean(ing|er)|janitor|maid", ["cleaning_services", "janitorial_service"]),
    (r"farm|agricult|ranch|orchard|dairy|livestock|poultry|vineyard",
     ["farm", "farmers_market", "agricultural_service", "agriculture", "livestock_breeder",
      "agricultural_cooperatives", "farming_services", "farm_equipment_and_supply",
      "urban_farm", "dairy_farm", "poultry_farm", "orchard", "vineyard"]),
]

SUFFIXES = {"inc", "ltd", "llc", "llp", "co", "corp", "corporation", "limited",
            "incorporated", "the", "and", "&"}
STREET_WORDS = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "boulevard": "blvd",
    "crescent": "cres", "court": "crt", "place": "pl", "lane": "ln", "parkway": "pkwy",
    "highway": "hwy", "terrace": "terr", "circle": "cir", "square": "sq", "trail": "trl",
    "west": "w", "east": "e", "north": "n", "south": "s",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}


def slugs_for(term):
    low = (term or "").lower()
    for pattern, slugs in CATEGORY_MAP:
        if re.search(pattern, low):
            return slugs
    return None


def norm_name(s):
    return " ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
                    if w not in SUFFIXES)


def norm_addr(s):
    s = re.sub(r"\b(unit|suite|ste|apt|#)\s*[\w-]+", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(STREET_WORDS.get(w, w) for w in s.split())


def haversine(a_lat, a_lon, b_lat, b_lon):
    r = 6371000
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def dedupe(rows):
    """Collapse one business appearing more than once: exact normalized
    name+street, then same name within 75 m. Survivor inherits contact details."""
    rows.sort(key=lambda r: -(r.get("confidence") or 0))
    by_key, kept = {}, []
    for r in rows:
        n, a = norm_name(r["name"]), norm_addr(r["street"])
        hit = by_key.get((n, a))
        if hit is None:
            for other in kept:
                if other["_n"] == n and haversine(r["lat"], r["lon"], other["lat"], other["lon"]) < 75:
                    hit = other
                    break
        if hit:
            hit["merged"] += 1
            hit["phone"] = hit["phone"] or r["phone"]
            hit["website"] = hit["website"] or r["website"]
            continue
        r["_n"], r["merged"] = n, 1
        by_key[(n, a)] = r
        kept.append(r)
    for r in kept:
        r.pop("_n", None)
    return kept


# ---------------------------------------------------------------- accounts

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            name TEXT NOT NULL DEFAULT '',
            pw TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            account_name TEXT NOT NULL DEFAULT '',
            account_phone TEXT NOT NULL DEFAULT '',
            campaign_date TEXT NOT NULL DEFAULT '',
            areas TEXT NOT NULL DEFAULT '[]',
            businesses INTEGER NOT NULL DEFAULT 0,
            farms INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_user ON campaigns(user_id);
    """)
    con.commit()


def hash_pw(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    key = scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + "$" + key.hex()


def verify_pw(password, stored):
    try:
        salt_hex, key_hex = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_pw(password, bytes.fromhex(salt_hex)), stored)


def create_user(con, email, password, role="user", name=""):
    con.execute(
        "INSERT INTO users (email, name, pw, role, created_at) VALUES (?,?,?,?,?)",
        (email.strip(), name or email.split("@")[0], hash_pw(password), role, now()))
    con.commit()
    return con.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- server

class Handler(SimpleHTTPRequestHandler):
    duck = None
    sql = None
    lock = threading.Lock()

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):
        line = args[0] if args else ""
        if "/api/" in line:
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------

    def json_out(self, obj, code=200, cookie=None):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def current_user(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        token = SimpleCookie(raw).get(COOKIE)
        if not token:
            return None
        with Handler.lock:
            row = Handler.sql.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token = ? AND s.expires > ? AND u.disabled = 0",
                (token.value, time.time())).fetchone()
        return row

    def require(self, master=False):
        user = self.current_user()
        if not user:
            self.json_out({"error": "Not signed in."}, 401)
            return None
        if master and not crm.is_manager(user):
            self.json_out({"error": "Manager access required."}, 403)
            return None
        return user

    # -- dispatch --------------------------------------------------------

    def do_GET(self):
        p = urlparse(self.path)
        if p.path.startswith("/api/"):
            return self.api("GET", p.path, parse_qs(p.query))
        if p.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        p = urlparse(self.path)
        return self.api("POST", p.path, parse_qs(p.query))

    def do_PUT(self):
        p = urlparse(self.path)
        return self.api("PUT", p.path, parse_qs(p.query))

    def do_DELETE(self):
        p = urlparse(self.path)
        return self.api("DELETE", p.path, parse_qs(p.query))

    def api(self, method, path, q):
        try:
            if path == "/api/auth/login" and method == "POST":
                return self.login()
            if path == "/api/auth/logout" and method == "POST":
                return self.logout()
            if path == "/api/auth/me" and method == "GET":
                user = self.current_user()
                return self.json_out({"user": self.user_json(user)} if user else {"user": None})
            if path == "/api/users":
                return self.users(method)
            if path.startswith("/api/campaigns"):
                return self.campaigns(method, path)
            if path == "/api/search" and method == "GET":
                return self.search(q)
            if path.startswith("/api/accounts") or path.startswith("/api/contacts") \
               or path.startswith("/api/activities") or path.startswith("/api/designs") \
               or path.startswith("/api/messages") or path in (
                   "/api/inbox", "/api/dashboard", "/api/meta"):
                return self.crm_api(method, path, q)
            self.json_out({"error": "Unknown endpoint."}, 404)
        except Exception as exc:                                  # noqa: BLE001
            self.json_out({"error": str(exc)}, 500)

    @staticmethod
    def user_json(u):
        keys = u.keys()
        return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"],
                "team": u["team"] if "team" in keys else "Sales"}

    # -- auth ------------------------------------------------------------

    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For")
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

    def https(self):
        """True behind a TLS-terminating proxy, or when forced by config."""
        return (self.headers.get("X-Forwarded-Proto") == "https"
                or os.environ.get("DART_SECURE_COOKIES") == "1")

    def login(self):
        data = self.body_json()
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        attempt = (self.client_ip(), email.lower())

        if login_blocked(attempt):
            return self.json_out(
                {"error": "Too many failed attempts. Try again in a few minutes."}, 429)

        with Handler.lock:
            row = Handler.sql.execute(
                "SELECT * FROM users WHERE email = ? AND disabled = 0", (email,)).fetchone()
        if not row or not verify_pw(password, row["pw"]):
            note_login_failure(attempt)
            time.sleep(0.4)                       # blunt the obvious guessing loop
            return self.json_out({"error": "Wrong email or password."}, 401)

        # The manager portal is manager-only; the consultant portal takes anyone.
        if (data.get("portal") == "manager") and not crm.is_manager(row):
            time.sleep(0.4)
            return self.json_out(
                {"error": "This account isn't a manager. Sign in at the consultant portal.",
                 "portal": "consultant"}, 403)

        clear_login_failures(attempt)
        token = secrets.token_urlsafe(32)
        with Handler.lock:
            Handler.sql.execute(
                "INSERT INTO sessions (token, user_id, expires) VALUES (?,?,?)",
                (token, row["id"], time.time() + SESSION_DAYS * 86400))
            Handler.sql.commit()
        cookie = (f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
                  f"Max-Age={SESSION_DAYS * 86400}"
                  + ("; Secure" if self.https() else ""))
        self.json_out({"user": self.user_json(row)}, cookie=cookie)

    def logout(self):
        raw = self.headers.get("Cookie")
        if raw:
            tok = SimpleCookie(raw).get(COOKIE)
            if tok:
                with Handler.lock:
                    Handler.sql.execute("DELETE FROM sessions WHERE token = ?", (tok.value,))
                    Handler.sql.commit()
        self.json_out({"ok": True}, cookie=f"{COOKIE}=; Path=/; HttpOnly; Max-Age=0"
                      + ("; Secure" if self.https() else ""))

    # -- users (master only) ---------------------------------------------

    def users(self, method):
        user = self.require(master=True)
        if not user:
            return
        if method == "GET":
            with Handler.lock:
                rows = Handler.sql.execute(
                    "SELECT u.id, u.email, u.name, u.role, u.team, u.created_at, u.disabled,"
                    "  (SELECT count(*) FROM campaigns c WHERE c.user_id = u.id) AS campaigns "
                    "FROM users u ORDER BY u.created_at").fetchall()
            return self.json_out({"users": [dict(r) for r in rows]})
        if method == "POST":
            d = self.body_json()
            email = (d.get("email") or "").strip()
            password = d.get("password") or ""
            if "@" not in email or len(password) < 8:
                return self.json_out(
                    {"error": "Need a valid email and a password of at least 8 characters."}, 400)
            with Handler.lock:
                if Handler.sql.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                    return self.json_out({"error": "That email already has an account."}, 409)
                row = create_user(Handler.sql, email, password,
                                  d.get("role") or "user", d.get("name") or "")
                team = d.get("team")
                if team in crm.TEAMS:
                    Handler.sql.execute("UPDATE users SET team = ? WHERE id = ?", (team, row["id"]))
                    Handler.sql.commit()
            return self.json_out({"user": self.user_json(row)}, 201)
        self.json_out({"error": "Method not allowed."}, 405)

    # -- campaigns -------------------------------------------------------

    def campaigns(self, method, path):
        user = self.require()
        if not user:
            return
        master = crm.is_manager(user)
        tail = path[len("/api/campaigns"):].strip("/")
        cid = int(tail) if tail.isdigit() else None

        if method == "GET" and cid is None:
            sql = ("SELECT c.*, u.email AS owner, a.name AS account, "
                   "       asg.name AS assignee_name, asg.team AS assignee_team "
                   "FROM campaigns c "
                   "JOIN users u ON u.id = c.user_id "
                   "LEFT JOIN accounts a ON a.id = c.account_id "
                   "LEFT JOIN users asg ON asg.id = c.assigned_to ")
            args = []
            if not master:
                sql += "WHERE (c.user_id = ? OR c.assigned_to = ?) "
                args += [user["id"], user["id"]]
            sql += "ORDER BY c.modified_at DESC"
            with Handler.lock:
                rows = Handler.sql.execute(sql, args).fetchall()
            return self.json_out({"campaigns": [dict(r) for r in rows], "master": master})

        if method == "GET":
            row = self.one_campaign(cid, user, master)
            return row and self.json_out({"campaign": dict(row)})

        if method == "POST" and cid is None:
            d = self.body_json()
            with Handler.lock:
                cur = Handler.sql.execute(
                    "INSERT INTO campaigns (user_id, title, note, account_name, account_phone,"
                    " campaign_date, areas, businesses, farms, account_id, stage, assigned_to,"
                    " created_at, modified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (user["id"], d.get("title", ""), d.get("note", ""),
                     d.get("account_name", ""), d.get("account_phone", ""),
                     d.get("campaign_date", ""), json.dumps(d.get("areas") or []),
                     int(d.get("businesses") or 0), int(d.get("farms") or 0),
                     d.get("account_id") or None, d.get("stage") or "draft",
                     d.get("assigned_to") or None, now(), now()))
                Handler.sql.commit()
            return self.json_out({"id": cur.lastrowid}, 201)

        if method == "PUT" and cid is not None:
            if not self.one_campaign(cid, user, master, quiet=False):
                return
            d = self.body_json()
            with Handler.lock:
                Handler.sql.execute(
                    "UPDATE campaigns SET title=?, note=?, account_name=?, account_phone=?,"
                    " campaign_date=?, areas=?, businesses=?, farms=?, status=?,"
                    " account_id=?, stage=?, assigned_to=?, modified_at=? WHERE id=?",
                    (d.get("title", ""), d.get("note", ""), d.get("account_name", ""),
                     d.get("account_phone", ""), d.get("campaign_date", ""),
                     json.dumps(d.get("areas") or []), int(d.get("businesses") or 0),
                     int(d.get("farms") or 0), d.get("status") or "draft",
                     d.get("account_id") or None, d.get("stage") or "draft",
                     d.get("assigned_to") or None, now(), cid))
                Handler.sql.commit()
            return self.json_out({"ok": True})

        if method == "DELETE" and cid is not None:
            if not self.one_campaign(cid, user, master, quiet=False):
                return
            with Handler.lock:
                Handler.sql.execute("DELETE FROM campaigns WHERE id = ?", (cid,))
                Handler.sql.commit()
            return self.json_out({"ok": True})

        self.json_out({"error": "Method not allowed."}, 405)

    def one_campaign(self, cid, user, master, quiet=True):
        with Handler.lock:
            row = Handler.sql.execute(
                "SELECT c.*, u.email AS owner, a.name AS account FROM campaigns c "
                "JOIN users u ON u.id = c.user_id "
                "LEFT JOIN accounts a ON a.id = c.account_id WHERE c.id = ?", (cid,)).fetchone()
        if not row or (not master and row["user_id"] != user["id"]
                       and row["assigned_to"] != user["id"]):
            self.json_out({"error": "Campaign not found."}, 404)
            return None
        return row

    # -- CRM -------------------------------------------------------------

    def crm_api(self, method, path, q):
        user = self.require()
        if not user:
            return
        parts = [p for p in path.split("/") if p][1:]      # drop "api"
        head = parts[0]
        ident = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        body = self.body_json() if method in ("POST", "PUT") else {}
        con = Handler.sql

        with Handler.lock:
            if head == "meta":
                return self.json_out({
                    "roles": crm.ROLES,
                    "teams": crm.TEAMS, "stages": crm.STAGES,
                    "account_statuses": crm.ACCOUNT_STATUSES,
                    "design_statuses": crm.DESIGN_STATUSES,
                    "activity_types": crm.ACTIVITY_TYPES,
                    "users": [dict(r) for r in con.execute(
                        "SELECT id, name, email, team FROM users WHERE disabled = 0"
                        " ORDER BY name")],
                })

            if head == "dashboard":
                return self.json_out(crm.dashboard(con, user))

            if head == "inbox":
                return self.json_out({"messages": crm.inbox(con, user)})

            if head == "accounts":
                if method == "GET" and ident is None:
                    return self.json_out({
                        "accounts": crm.list_accounts(con, (q.get("q", [""])[0] or "").strip())})
                if method == "GET":
                    acc = crm.get_account(con, ident)
                    return self.json_out({"account": acc}) if acc else \
                        self.json_out({"error": "Account not found."}, 404)
                if method == "POST":
                    if not (body.get("name") or "").strip():
                        return self.json_out({"error": "An account needs a name."}, 400)
                    return self.json_out({"id": crm.create_account(con, body, user["id"])}, 201)
                if method == "PUT" and ident is not None:
                    crm.update_account(con, ident, body)
                    return self.json_out({"ok": True})
                if method == "DELETE" and ident is not None:
                    if not crm.is_manager(user):
                        return self.json_out({"error": "Manager access required."}, 403)
                    crm.delete_account(con, ident)
                    return self.json_out({"ok": True})

            if head == "contacts":
                if method == "POST":
                    return self.json_out({"id": crm.create_contact(con, body)}, 201)
                if method == "DELETE" and ident is not None:
                    crm.delete_contact(con, ident)
                    return self.json_out({"ok": True})

            if head == "activities":
                if method == "POST":
                    return self.json_out({"id": crm.create_activity(con, body, user["id"])}, 201)
                if method == "PUT" and ident is not None:
                    crm.toggle_activity(con, ident, body.get("done"))
                    return self.json_out({"ok": True})
                if method == "GET":
                    return self.json_out({"tasks": crm.open_tasks(con, user["id"])})

            if head == "designs":
                if method == "GET":
                    cid = int(q.get("campaign_id", [0])[0] or 0)
                    return self.json_out({"designs": crm.list_designs(con, cid)})
                if method == "POST":
                    return self.json_out({"id": crm.create_design(con, body, user["id"])}, 201)
                if method == "PUT" and ident is not None:
                    crm.set_design_status(con, ident, body.get("status", "draft"))
                    return self.json_out({"ok": True})

            if head == "messages":
                if method == "GET":
                    cid = int(q.get("campaign_id", [0])[0] or 0)
                    return self.json_out({"messages": crm.list_messages(con, cid)})
                if method == "POST":
                    if not (body.get("body") or "").strip():
                        return self.json_out({"error": "Message is empty."}, 400)
                    return self.json_out({"id": crm.create_message(con, body, user["id"])}, 201)

        self.json_out({"error": "Method not allowed."}, 405)

    # -- business search -------------------------------------------------

    def search(self, q):
        if not self.require():
            return
        if Handler.duck is None:
            return self.json_out({"error": "Place data not loaded."}, 503)
        try:
            what = (q.get("what", [""])[0] or "").strip()
            s, w, n, e = (float(q[k][0]) for k in ("s", "w", "n", "e"))
            limit = min(int(q.get("limit", ["1200"])[0]), 5000)
        except (KeyError, ValueError, IndexError):
            return self.json_out({"error": "Bad parameters."}, 400)

        slugs = slugs_for(what)
        like = "%" + re.sub(r"[%_]", "", what.lower()) + "%"
        where = ["lat BETWEEN ? AND ?", "lon BETWEEN ? AND ?"]
        params = [s, n, w, e]
        if slugs:
            marks = ",".join("?" * len(slugs))
            where.append(f"(category IN ({marks}) OR "
                         f"len(list_intersect(alt_categories, [{marks}])) > 0 OR lower(name) LIKE ?)")
            params += slugs + slugs + [like]
        else:
            where.append("(lower(category) LIKE ? OR lower(name) LIKE ?)")
            params += [like, like]

        clause = " AND ".join(where)
        with Handler.lock:
            cur = Handler.duck.cursor()
            rows = cur.execute(
                f"SELECT name, street, city, province, postcode, category, phone, website,"
                f" lat, lon, confidence FROM read_parquet('{PARQUET}') WHERE {clause}"
                f" ORDER BY confidence DESC LIMIT ?", params + [limit]).fetchall()
            cols = [c[0] for c in cur.description]
            total = cur.execute(
                f"SELECT count(*) FROM read_parquet('{PARQUET}') WHERE {clause}",
                params).fetchone()[0]

        raw = [dict(zip(cols, r)) for r in rows]
        merged = dedupe(raw)
        merged.sort(key=lambda r: (r["name"] or "").lower())
        self.json_out({"source": "Overture Maps", "total": total, "raw": len(raw),
                       "capped": total > len(raw), "removed": len(raw) - len(merged),
                       "results": merged})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    DB_PATH.parent.mkdir(exist_ok=True)

    con = db()
    init_db(con)
    crm.migrate(con)
    Handler.sql = con

    if not con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        pw = secrets.token_urlsafe(9)
        create_user(con, "admin@local", pw, role="manager", name="Manager")
        print("=" * 58)
        print("  Manager account created")
        print("    email    admin@local")
        print(f"    password {pw}")
        print("  Sign in at /manager.html, then add users from the Team screen.")
        print("=" * 58)

    con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    con.commit()

    if Path(PARQUET).exists():
        duck = duckdb.connect()
        duck.execute("INSTALL spatial; LOAD spatial;")
        n = duck.execute(f"SELECT count(*) FROM read_parquet('{PARQUET}')").fetchone()[0]
        Handler.duck = duck
        print(f"loaded {n:,} Canadian places")
    else:
        print(f"WARNING: {PARQUET} missing — /api/search disabled")

    users = con.execute("SELECT count(*) FROM users").fetchone()[0]
    camps = con.execute("SELECT count(*) FROM campaigns").fetchone()[0]
    print(f"{users} account(s), {camps} campaign(s)")
    print(f"serving {WEB} on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
