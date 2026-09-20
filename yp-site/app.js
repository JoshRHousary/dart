/* Shared helpers: API calls, session guard, top bar.

   This build runs without serve.py. `api()` keeps the same paths the pages
   already call (/api/campaigns, /api/accounts/3, /api/search?…) but answers
   them from Supabase (auth + Postgres, see supabase/schema.sql) and, for
   search, from the pre-cut place tiles in tiles/ (see build_tiles.py). */
(() => {
  "use strict";

  const CFG = window.DART_CONFIG || {};
  const SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js";

  const fail = (message, status = 400) => Object.assign(new Error(message), { status });

  /* ---------------------------------------------------------- supabase */

  let sb = null, sbLoading = null, profile = null;

  function loadScript(src) {
    return new Promise((ok, no) => {
      const s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = () => no(new Error("Could not load " + src));
      document.head.appendChild(s);
    });
  }

  async function client() {
    if (sb) return sb;
    if (!CFG.supabaseUrl || !CFG.supabaseAnonKey) {
      throw fail("This site isn't connected to a database yet (config.js is empty).", 503);
    }
    if (!sbLoading) sbLoading = window.supabase ? Promise.resolve() : loadScript(SUPABASE_JS);
    await sbLoading;
    sb = window.supabase.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey);
    return sb;
  }

  /* Turns a supabase-js result into data, or throws like the old server did. */
  function unwrap({ data, error }, notFound) {
    if (error) {
      const code = error.code === "PGRST116" ? 404 : error.code === "42501" ? 403 : 400;
      throw fail(code === 404 && notFound ? notFound : error.message, code);
    }
    return data;
  }

  const userJson = p => p && ({ id: p.id, email: p.email, name: p.name, role: p.role, team: p.team });

  async function me() {
    const s = await client();
    const { data: { session } } = await s.auth.getSession();
    if (!session) { profile = null; return null; }
    if (profile && profile.auth_id === session.user.id) return profile;
    const { data } = await s.from("profiles").select("*").eq("auth_id", session.user.id).maybeSingle();
    profile = data || null;
    return profile;
  }

  async function requireActive(manager = false) {
    const p = await me();
    if (!p) throw fail("Not signed in.", 401);
    if (!p.approved) throw fail("Your account is waiting for a manager to approve it.", 403);
    if (p.disabled) throw fail("This account is disabled.", 403);
    if (manager && p.role !== "manager") throw fail("Manager access required.", 403);
    return p;
  }

  const NOW = () => new Date().toISOString();

  /* ---------------------------------------------------------- constants (crm.py) */

  const TEAMS = ["Sales", "Design", "Production", "Management"];
  const ROLES = {
    manager: { label: "Manager", portal: "manager",
               blurb: "Every campaign, every client, plus team management." },
    mac:     { label: "Media Account Consultant", portal: "consultant",
               blurb: "Their own campaigns and any assigned to them." },
    expert:  { label: "Direct Mail Expert", portal: "consultant",
               blurb: "Their own campaigns and any assigned to them." },
  };
  const STAGES = ["draft", "proposed", "approved", "design", "print", "mailed", "closed"];
  const ACCOUNT_STATUSES = ["lead", "active", "on hold", "inactive"];
  const DESIGN_STATUSES = ["draft", "in review", "approved", "sent to print"];
  const ACTIVITY_TYPES = ["call", "email", "meeting", "task", "note"];
  const ACCOUNT_FIELDS = ["name", "phone", "email", "website", "industry", "street",
                          "city", "province", "postcode", "status", "note"];

  /* ---------------------------------------------------------- auth */

  async function login({ email, password, portal }) {
    const s = await client();
    const { error } = await s.auth.signInWithPassword({ email: (email || "").trim(), password: password || "" });
    if (error) throw fail("Wrong email or password.", 401);
    profile = null;
    const p = await me();
    if (!p) { await s.auth.signOut(); throw fail("No team profile for this account.", 403); }
    if (!p.approved || p.disabled) {
      await s.auth.signOut();
      throw fail(p.disabled ? "This account is disabled."
        : "Your account is waiting for a manager to approve it.", 403);
    }
    if (portal === "manager" && p.role !== "manager") {
      await s.auth.signOut();
      throw Object.assign(fail("This account isn't a manager. Sign in at the consultant portal.", 403),
        { portal: "consultant" });
    }
    return { user: userJson(p) };
  }

  async function logout() {
    const s = await client();
    await s.auth.signOut();
    profile = null;
    return { ok: true };
  }

  /* First run: no accounts exist, so the manager portal creates one. */
  async function setup({ email, password, name }) {
    const s = await client();
    if (!unwrap(await s.rpc("setup_needed"))) throw fail("Setup is already done. Sign in instead.", 409);
    if (!(email || "").includes("@") || (password || "").length < 8) {
      throw fail("Need a valid email and a password of at least 8 characters.");
    }
    const { error } = await s.auth.signUp({ email: email.trim(), password, options: { data: { name: name || "" } } });
    if (error) throw fail(error.message);
    return login({ email, password, portal: "manager" });
  }

  /* ---------------------------------------------------------- users */

  async function listUsers() {
    await requireActive(true);
    const s = await client();
    const rows = unwrap(await s.from("profiles")
      .select("id, email, name, role, team, created_at, disabled, approved, campaigns:campaigns!campaigns_user_id_fkey(count)")
      .order("created_at"));
    return { users: rows.map(r => ({ ...r, campaigns: r.campaigns?.[0]?.count || 0,
                                     disabled: r.disabled || !r.approved })) };
  }

  async function createUser(d) {
    await requireActive(true);
    const email = (d.email || "").trim(), password = d.password || "";
    if (!email.includes("@") || password.length < 8) {
      throw fail("Need a valid email and a password of at least 8 characters.");
    }
    const s = await client();
    const exists = unwrap(await s.from("profiles").select("id").ilike("email", email).maybeSingle());
    if (exists) throw fail("That email already has an account.", 409);

    /* A second, memory-only client signs the new person up so the manager's
       own session is untouched. The trigger creates their (pending) profile. */
    const tmp = window.supabase.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey,
      { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });
    const { error } = await tmp.auth.signUp({ email, password, options: { data: { name: d.name || "" } } });
    if (error) throw fail(error.message);

    const role = ROLES[d.role] ? d.role : "mac";
    const team = TEAMS.includes(d.team) ? d.team : "Sales";
    const updated = unwrap(await s.from("profiles")
      .update({ role, team, name: d.name || email.split("@")[0], approved: true })
      .ilike("email", email).select("*"));
    if (!updated.length) throw fail("The account was created but could not be approved.", 500);
    return { user: userJson(updated[0]) };
  }

  /* ---------------------------------------------------------- campaigns */

  const CAMPAIGN_SELECT = "*, owner:profiles!campaigns_user_id_fkey(email), " +
    "account_row:accounts(name), assignee:profiles!campaigns_assigned_to_fkey(name, team)";

  function campaignOut(r) {
    const { owner, account_row, assignee, ...c } = r;
    return { ...c, areas: JSON.stringify(c.areas || []), owner: owner?.email || "",
             account: account_row?.name || null,
             assignee_name: assignee?.name || null, assignee_team: assignee?.team || null };
  }

  function campaignIn(d, p, creating) {
    const out = {
      title: d.title || "", note: d.note || "", account_name: d.account_name || "",
      account_phone: d.account_phone || "", campaign_date: d.campaign_date || "",
      areas: Array.isArray(d.areas) ? d.areas : [], businesses: +d.businesses || 0,
      farms: +d.farms || 0, account_id: d.account_id || null, stage: d.stage || "draft",
      assigned_to: d.assigned_to || null, modified_at: NOW(),
    };
    if (creating) out.user_id = p.id;
    else out.status = d.status || "draft";
    return out;
  }

  async function campaigns(method, id, d) {
    const p = await requireActive();
    const s = await client();
    const master = p.role === "manager";
    if (method === "GET" && id == null) {
      const rows = unwrap(await s.from("campaigns").select(CAMPAIGN_SELECT).order("modified_at", { ascending: false }));
      return { campaigns: rows.map(campaignOut), master };
    }
    if (method === "GET") {
      const row = unwrap(await s.from("campaigns").select(CAMPAIGN_SELECT).eq("id", id).maybeSingle());
      if (!row) throw fail("Campaign not found.", 404);
      return { campaign: campaignOut(row) };
    }
    if (method === "POST" && id == null) {
      const row = unwrap(await s.from("campaigns").insert(campaignIn(d, p, true)).select("id").single());
      return { id: row.id };
    }
    if (method === "PUT" && id != null) {
      const rows = unwrap(await s.from("campaigns").update(campaignIn(d, p, false)).eq("id", id).select("id"));
      if (!rows.length) throw fail("Campaign not found.", 404);
      return { ok: true };
    }
    if (method === "DELETE" && id != null) {
      const rows = unwrap(await s.from("campaigns").delete().eq("id", id).select("id"));
      if (!rows.length) throw fail("Campaign not found.", 404);
      return { ok: true };
    }
    throw fail("Method not allowed.", 405);
  }

  /* ---------------------------------------------------------- CRM */

  async function meta() {
    await requireActive();
    const s = await client();
    const users = unwrap(await s.from("profiles").select("id, name, email, team")
      .eq("disabled", false).eq("approved", true).order("name"));
    return { roles: ROLES, teams: TEAMS, stages: STAGES, account_statuses: ACCOUNT_STATUSES,
             design_statuses: DESIGN_STATUSES, activity_types: ACTIVITY_TYPES, users };
  }

  const pick = d => Object.fromEntries(ACCOUNT_FIELDS.map(f => [f, String(d[f] ?? "")]));

  async function accounts(method, id, d, q) {
    const p = await requireActive();
    const s = await client();
    if (method === "GET" && id == null) {
      let sel = s.from("accounts")
        .select("*, owner:profiles!accounts_owner_id_fkey(email, name), campaigns(count), contacts(count)")
        .order("modified_at", { ascending: false });
      const term = (q.get("q") || "").trim();
      if (term) {
        const like = "%" + term.replace(/[%_,]/g, "") + "%";
        sel = sel.or(`name.ilike.${like},city.ilike.${like},phone.ilike.${like},industry.ilike.${like}`);
      }
      const rows = unwrap(await sel);
      return { accounts: rows.map(({ owner, campaigns: c, contacts: k, ...a }) => ({
        ...a, owner_email: owner?.email || null, owner_name: owner?.name || null,
        campaigns: c?.[0]?.count || 0, contacts: k?.[0]?.count || 0 })) };
    }
    if (method === "GET") {
      const acc = unwrap(await s.from("accounts")
        .select("*, owner:profiles!accounts_owner_id_fkey(email)").eq("id", id).maybeSingle());
      if (!acc) throw fail("Account not found.", 404);
      const [contacts, camps, acts] = await Promise.all([
        s.from("contacts").select("*").eq("account_id", id)
          .order("is_primary", { ascending: false }).order("name"),
        s.from("campaigns").select("id, title, stage, campaign_date, businesses, farms, modified_at, owner:profiles!campaigns_user_id_fkey(email)")
          .eq("account_id", id).order("modified_at", { ascending: false }),
        s.from("activities").select("*, who:profiles!activities_user_id_fkey(name, email)")
          .eq("account_id", id).order("created_at", { ascending: false }).limit(100),
      ]);
      const { owner, ...a } = acc;
      return { account: { ...a, owner_email: owner?.email || null,
        contacts: unwrap(contacts),
        campaigns: unwrap(camps).map(({ owner: o, ...c }) => ({ ...c, owner: o?.email || "" })),
        activities: unwrap(acts).map(({ who, ...x }) => ({ ...x, user_name: who?.name, user_email: who?.email })) } };
    }
    if (method === "POST") {
      if (!(d.name || "").trim()) throw fail("An account needs a name.");
      const row = unwrap(await s.from("accounts")
        .insert({ ...pick(d), owner_id: d.owner_id || p.id }).select("id").single());
      return { id: row.id };
    }
    if (method === "PUT" && id != null) {
      const patch = { ...pick(d), modified_at: NOW() };
      if ("owner_id" in d) patch.owner_id = d.owner_id || null;
      unwrap(await s.from("accounts").update(patch).eq("id", id));
      return { ok: true };
    }
    if (method === "DELETE" && id != null) {
      await requireActive(true);
      unwrap(await s.from("accounts").delete().eq("id", id));
      return { ok: true };
    }
    throw fail("Method not allowed.", 405);
  }

  async function contacts(method, id, d) {
    await requireActive();
    const s = await client();
    if (method === "POST") {
      const row = unwrap(await s.from("contacts").insert({
        account_id: d.account_id, name: d.name || "", role: d.role || "", email: d.email || "",
        phone: d.phone || "", is_primary: !!d.is_primary }).select("id").single());
      return { id: row.id };
    }
    if (method === "DELETE" && id != null) {
      unwrap(await s.from("contacts").delete().eq("id", id));
      return { ok: true };
    }
    throw fail("Method not allowed.", 405);
  }

  async function activities(method, id, d) {
    const p = await requireActive();
    const s = await client();
    if (method === "POST") {
      const row = unwrap(await s.from("activities").insert({
        account_id: d.account_id || null, campaign_id: d.campaign_id || null, user_id: p.id,
        kind: d.kind || "note", subject: d.subject || "", body: d.body || "",
        due_at: d.due_at || "", done: !!d.done }).select("id").single());
      return { id: row.id };
    }
    if (method === "PUT" && id != null) {
      unwrap(await s.from("activities").update({ done: !!d.done }).eq("id", id));
      return { ok: true };
    }
    if (method === "GET") {
      const rows = unwrap(await s.from("activities").select("*, acc:accounts(name)")
        .eq("user_id", p.id).eq("kind", "task").eq("done", false).order("due_at"));
      return { tasks: rows.map(({ acc, ...a }) => ({ ...a, account_name: acc?.name || null })) };
    }
    throw fail("Method not allowed.", 405);
  }

  async function designs(method, id, d, q) {
    const p = await requireActive();
    const s = await client();
    if (method === "GET") {
      const rows = unwrap(await s.from("designs").select("*, who:profiles!designs_user_id_fkey(name)")
        .eq("campaign_id", +q.get("campaign_id") || 0)
        .order("version", { ascending: false }).order("id", { ascending: false }));
      return { designs: rows.map(({ who, ...x }) => ({ ...x, user_name: who?.name || "" })) };
    }
    if (method === "POST") {
      const latest = unwrap(await s.from("designs").select("version").eq("campaign_id", d.campaign_id)
        .order("version", { ascending: false }).limit(1));
      const version = (latest[0]?.version || 0) + 1;
      const row = unwrap(await s.from("designs").insert({
        campaign_id: d.campaign_id, name: d.name || `Version ${version}`, version,
        status: d.status || "draft", url: d.url || "", note: d.note || "", user_id: p.id })
        .select("id").single());
      return { id: row.id };
    }
    if (method === "PUT" && id != null) {
      unwrap(await s.from("designs").update({ status: d.status || "draft" }).eq("id", id));
      return { ok: true };
    }
    throw fail("Method not allowed.", 405);
  }

  async function messages(method, d, q) {
    const p = await requireActive();
    const s = await client();
    if (method === "GET") {
      const rows = unwrap(await s.from("messages").select("*, who:profiles!messages_user_id_fkey(name, email, team)")
        .eq("campaign_id", +q.get("campaign_id") || 0).order("created_at"));
      return { messages: rows.map(({ who, ...m }) => ({ ...m,
        user_name: who?.name, user_email: who?.email, user_team: who?.team })) };
    }
    if (method === "POST") {
      if (!(d.body || "").trim()) throw fail("Message is empty.");
      const row = unwrap(await s.from("messages").insert({
        campaign_id: d.campaign_id || null, account_id: d.account_id || null, user_id: p.id,
        to_team: d.to_team || "", body: d.body }).select("id").single());
      return { id: row.id };
    }
    throw fail("Method not allowed.", 405);
  }

  /* ---------------------------------------------------------- search (serve.py, in the browser) */

  const CATEGORY_MAP = [
    [/dentist|dental|orthodont/, ["dentist", "orthodontist", "dental_clinic"]],
    [/pharmac|drug ?store/, ["pharmacy", "drugstore"]],
    [/hospital/, ["hospital"]],
    [/veterinar/, ["veterinarian", "veterinary_care"]],
    [/physician|doctor|medical clinic|walk-?in/, ["doctor", "medical_clinic", "physician"]],
    [/physiotherap/, ["physical_therapist", "physiotherapist"]],
    [/chiropract/, ["chiropractor"]],
    [/optic|optometr|eyewear/, ["optometrist", "eyewear_and_opticians"]],
    [/fast ?food|burger|take-?out/, ["fast_food_restaurant", "burger_restaurant"]],
    [/pizza/, ["pizza_restaurant"]],
    [/caf[eé]|coffee/, ["cafe", "coffee_shop"]],
    [/bakery|baker/, ["bakery"]],
    [/butcher/, ["butcher_shop"]],
    [/night ?club/, ["nightclub"]],
    [/bar\b|pub\b|tavern|brewer/, ["bar", "pub", "brewery"]],
    [/restaurant|dining|bistro|steakhouse/, ["restaurant"]],
    [/grocer|supermarket/, ["grocery_store", "supermarket"]],
    [/liquor|wine|spirits/, ["liquor_store", "beer_wine_and_spirits"]],
    [/bank|credit union/, ["bank", "credit_union"]],
    [/insurance/, ["insurance_agency"]],
    [/real.?estate|realtor/, ["real_estate_agent", "real_estate"]],
    [/lawyer|attorney|legal|barrister|notar/, ["lawyer", "legal_services", "notary"]],
    [/accountant|accounting|bookkeep/, ["accountant", "accounting"]],
    [/travel agenc/, ["travel_agency"]],
    [/motel/, ["motel"]],
    [/hotel|inn\b|lodging|resort/, ["hotel", "resort"]],
    [/hair|barber/, ["hair_salon", "barber"]],
    [/beauty|nail|esthetic/, ["beauty_salon", "nail_salon"]],
    [/spa\b/, ["spa"]],
    [/gym|fitness|yoga|pilates/, ["gym", "fitness_center", "yoga_studio"]],
    [/dry ?clean|laundr/, ["dry_cleaning", "laundry_service", "laundromat"]],
    [/funeral|cremat/, ["funeral_home", "funeral_services"]],
    [/florist|flower/, ["florist"]],
    [/jewel/, ["jewelry_store"]],
    [/shoe|footwear/, ["shoe_store"]],
    [/clothing|apparel|fashion|boutique/, ["clothing_store", "fashion"]],
    [/furniture|mattress/, ["furniture_store", "mattress_store"]],
    [/hardware|building suppl|lumber/, ["hardware_store", "home_improvement"]],
    [/book/, ["bookstore"]],
    [/pet|kennel|groom/, ["pet_store", "pet_groomer"]],
    [/cell ?phone|mobile phone/, ["mobile_phone_store"]],
    [/computer|electronic/, ["electronics_store", "computer_store"]],
    [/car ?wash/, ["car_wash"]],
    [/tire|tyre/, ["tire_shop"]],
    [/auto.*(repair|service|body|mechanic)|mechanic|garage/, ["auto_repair", "car_repair"]],
    [/car dealer|auto.*dealer|used cars/, ["car_dealer", "auto_dealer"]],
    [/gas ?(bar|station)|fuel|petrol/, ["gas_station"]],
    [/day ?care|child ?care|kindergarten/, ["child_care", "daycare"]],
    [/college|universit/, ["college_university"]],
    [/school|academy|tutor/, ["school"]],
    [/librar/, ["library"]],
    [/church|mosque|synagogue|temple|worship/, ["religious_organization", "church"]],
    [/bicycle|bike/, ["bicycle_store"]],
    [/golf/, ["golf_course"]],
    [/sport|athletic/, ["sporting_goods", "sports_club"]],
    [/toy|hobby/, ["toy_store", "hobby_store"]],
    [/gift|souvenir/, ["gift_shop"]],
    [/galler/, ["art_gallery"]],
    [/museum/, ["museum"]],
    [/cinema|movie|theatre|theater/, ["cinema", "performing_arts"]],
    [/plumb/, ["plumber"]],
    [/electric(ian|al contract)/, ["electrician"]],
    [/roof/, ["roofing_contractor", "roofer"]],
    [/paint/, ["painter", "painting_contractor"]],
    [/hvac|heating|air ?condition|furnace/, ["hvac_services", "heating_and_air_conditioning"]],
    [/landscap|lawn|garden centre/, ["landscaping", "garden_center"]],
    [/clean(ing|er)|janitor|maid/, ["cleaning_services", "janitorial_service"]],
    [/farm|agricult|ranch|orchard|dairy|livestock|poultry|vineyard/,
     ["farm", "farmers_market", "agricultural_service", "agriculture", "livestock_breeder",
      "agricultural_cooperatives", "farming_services", "farm_equipment_and_supply",
      "urban_farm", "dairy_farm", "poultry_farm", "orchard", "vineyard"]],
  ];
  const SUFFIXES = new Set(["inc", "ltd", "llc", "llp", "co", "corp", "corporation", "limited",
                            "incorporated", "the", "and", "&"]);
  const STREET_WORDS = {
    street: "st", avenue: "ave", road: "rd", drive: "dr", boulevard: "blvd", crescent: "cres",
    court: "crt", place: "pl", lane: "ln", parkway: "pkwy", highway: "hwy", terrace: "terr",
    circle: "cir", square: "sq", trail: "trl", west: "w", east: "e", north: "n", south: "s",
    northwest: "nw", northeast: "ne", southwest: "sw", southeast: "se",
  };

  const slugsFor = term => {
    const low = (term || "").toLowerCase();
    const hit = CATEGORY_MAP.find(([re]) => re.test(low));
    return hit ? hit[1] : null;
  };
  const normName = s => (s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/)
    .filter(w => w && !SUFFIXES.has(w)).join(" ");
  const normAddr = s => (s || "").toLowerCase().replace(/\b(unit|suite|ste|apt|#)\s*[\w-]+/g, " ")
    .replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean).map(w => STREET_WORDS[w] || w).join(" ");

  function haversine(aLat, aLon, bLat, bLon) {
    const r = 6371000, p1 = aLat * Math.PI / 180, p2 = bLat * Math.PI / 180;
    const dp = p2 - p1, dl = (bLon - aLon) * Math.PI / 180;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * r * Math.asin(Math.sqrt(h));
  }

  /* Collapse one business appearing more than once: exact normalized
     name+street, then same name within 75 m. Survivor inherits contact details. */
  function dedupe(rows) {
    rows.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    const byKey = new Map(), kept = [];
    for (const r of rows) {
      const n = normName(r.name), a = normAddr(r.street);
      let hit = byKey.get(n + " " + a);
      if (!hit) {
        for (const o of kept) {
          if (o._n === n && haversine(r.lat, r.lon, o.lat, o.lon) < 75) { hit = o; break; }
        }
      }
      if (hit) {
        hit.merged += 1;
        hit.phone = hit.phone || r.phone;
        hit.website = hit.website || r.website;
        continue;
      }
      r._n = n; r.merged = 1;
      byKey.set(n + " " + a, r);
      kept.push(r);
    }
    kept.forEach(r => { delete r._n; });
    return kept;
  }

  let tileIndex = null;
  const tileCache = new Map();
  const TILE_ROW_BUDGET = 350000;      // rows fetched per search before we say "capped"
  const TILE_MAX = 120;                // ...and requests per search, for province-sized boxes
  const CACHE_ROW_BUDGET = 600000;

  async function loadTileIndex() {
    if (tileIndex) return tileIndex;
    const res = await fetch("tiles/index.json");
    if (!res.ok) throw fail("Place data isn't available on this site.", 503);
    tileIndex = await res.json();
    return tileIndex;
  }

  async function loadTile(key) {
    if (tileCache.has(key)) return tileCache.get(key);
    const res = await fetch("tiles/" + key + ".json.gz");
    if (!res.ok) throw fail("Could not load place data (" + res.status + ").", 502);
    let buf = await res.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let text;
    if (bytes[0] === 0x1f && bytes[1] === 0x8b) {           // still gzipped: inflate here
      const ds = new DecompressionStream("gzip");
      text = await new Response(new Blob([buf]).stream().pipeThrough(ds)).text();
    } else {                                                  // server already inflated it
      text = new TextDecoder().decode(buf);
    }
    const rows = JSON.parse(text);
    let cached = 0;
    tileCache.forEach(v => { cached += v.length; });
    if (cached + rows.length > CACHE_ROW_BUDGET) tileCache.clear();
    tileCache.set(key, rows);
    return rows;
  }

  async function search(q) {
    const what = (q.get("what") || "").trim();
    const s = +q.get("s"), w = +q.get("w"), n = +q.get("n"), e = +q.get("e");
    const limit = Math.min(+q.get("limit") || 1200, 5000);
    if (![s, w, n, e].every(Number.isFinite)) throw fail("Bad parameters.");

    const idx = await loadTileIndex();
    const step = idx.step, col = Object.fromEntries(idx.cols.map((c, i) => [c, i]));

    const wanted = [];
    for (let a = Math.floor(s / step); a <= Math.floor(n / step); a++) {
      for (let b = Math.floor(w / step); b <= Math.floor(e / step); b++) {
        const key = a + "_" + b;
        if (idx.tiles[key]) wanted.push({ key, n: idx.tiles[key] });
      }
    }
    /* Busiest tiles first so a province-wide search still covers the cities. */
    wanted.sort((x, y) => y.n - x.n);
    let budget = TILE_ROW_BUDGET, skipped = false;
    const take = [];
    for (const t of wanted) {
      if (take.length >= TILE_MAX || (t.n > budget && take.length)) { skipped = true; continue; }
      take.push(t.key); budget -= t.n;
    }

    const slugs = slugsFor(what);
    const slugSet = slugs && new Set(slugs);
    const like = what.toLowerCase().replace(/[%_]/g, "");
    const matches = r => {
      const lat = r[col.lat], lon = r[col.lon];
      if (lat < s || lat > n || lon < w || lon > e) return false;
      if (slugSet) {
        if (slugSet.has(r[col.category])) return true;
        const alts = r[col.alt_categories];
        if (alts && alts.split("|").some(c => slugSet.has(c))) return true;
        return r[col.name].toLowerCase().includes(like);
      }
      return (r[col.category] || "").toLowerCase().includes(like) || r[col.name].toLowerCase().includes(like);
    };

    /* A few tiles at a time: browsers cap parallel requests anyway, and
       filtering as each one lands keeps memory flat on big searches. */
    const hits = [];
    const queue = take.slice();
    await Promise.all(Array.from({ length: 8 }, async () => {
      while (queue.length) {
        const rows = await loadTile(queue.shift());
        rows.forEach(r => { if (matches(r)) hits.push(r); });
      }
    }));
    hits.sort((a, b) => b[col.confidence] - a[col.confidence]);

    const raw = hits.slice(0, limit).map(r => ({
      name: r[col.name], street: r[col.street], city: r[col.city], province: r[col.province],
      postcode: r[col.postcode], category: r[col.category], phone: r[col.phone] || null,
      website: r[col.website] || null, lat: r[col.lat], lon: r[col.lon], confidence: r[col.confidence],
    }));
    const merged = dedupe(raw);
    merged.sort((a, b) => (a.name || "").toLowerCase().localeCompare((b.name || "").toLowerCase()));
    return { source: "Overture Maps", total: hits.length, raw: raw.length,
             capped: hits.length > raw.length || skipped, removed: raw.length - merged.length,
             results: merged };
  }

  /* ---------------------------------------------------------- router */

  async function api(path, opts = {}) {
    const method = (opts.method || "GET").toUpperCase();
    const body = opts.body || {};
    const [p, qs] = path.split("?");
    const q = new URLSearchParams(qs || "");
    const parts = p.split("/").filter(Boolean).slice(1);    // drop "api"
    const head = parts[0], sub = parts[1];
    const id = sub && /^\d+$/.test(sub) ? +sub : null;

    switch (head) {
      case "auth":
        if (sub === "login" && method === "POST") return login(body);
        if (sub === "logout" && method === "POST") return logout();
        if (sub === "me") return { user: userJson(await me()) };
        if (sub === "setup" && method === "POST") return setup(body);
        break;
      case "setup":
        return { needed: unwrap(await (await client()).rpc("setup_needed")) };
      case "users":
        if (method === "GET") return listUsers();
        if (method === "POST") return createUser(body);
        break;
      case "campaigns": return campaigns(method, id, body);
      case "meta": return meta();
      case "accounts": return accounts(method, id, body, q);
      case "contacts": return contacts(method, id, body);
      case "activities": return activities(method, id, body);
      case "designs": return designs(method, id, body, q);
      case "messages": return messages(method, body, q);
      case "search": return search(q);
      default: break;
    }
    throw fail("Unknown endpoint.", 404);
  }

  /* ---------------------------------------------------------- page helpers */

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
    sessionStorage.getItem("dart_portal") === "manager" ? "manager.html" : "login.html";

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
      ["index.html", "Campaigns", "campaigns"],
      ["clients.html", "Clients", "clients"],
    ];
    if (user.role === "manager") links.push(["users.html", "Team", "team"]);

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
