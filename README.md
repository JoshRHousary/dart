# DART — direct-mail targeting for Canada

Campaign planning, client CRM and business lookup for direct-mail teams.
Runs entirely as a static site on GitHub Pages with a free Supabase project
behind it — no server to keep alive.

**Live:** https://joshrhousary.github.io/dart/

| URL | Who |
|---|---|
| `manager.html` | Managers — every campaign, every client, team management. On a fresh database this page creates the first manager account. |
| `login.html` | Media Account Consultants and Direct Mail Experts — their own and assigned campaigns |
| `taxonomy.html` | Public: every YellowPages.ca category and Canadian city |

## How it's put together

```
yp-site/                the whole site (this is what gets published)
  app.js                api() — same /api/... paths the pages always called,
                        answered by Supabase + in-browser search
  config.js             Supabase URL + anon key for this deployment
  tiles/                1.48M Canadian businesses cut into 0.25° map tiles
  fsa.geojson           postal-area (FSA) boundaries with counts
  *.html                the pages
supabase/schema.sql     tables, trigger and row-level-security policies
build_tiles.py          rebuilds yp-site/tiles/ from data/places-ca.parquet
.github/workflows/pages.yml   publishes yp-site/ to the gh-pages branch on push
```

**Accounts.** Supabase Auth (email + password). Every sign-up gets a row in
`profiles`. The very first becomes the approved manager; anyone else is
pending until a manager approves them — which is what the Team screen's
"Add user" does (sign them up, then set role, team and approved).

**Data access.** Row-level security in Postgres enforces the same rules the
old Python server did: managers see everything; consultants see campaigns
they own or are assigned; clients, contacts, activity, artwork and threads
are shared by the whole team; deleting a client is manager-only.

**Search.** `build_tiles.py` shards the Overture Maps extract by 0.25°
cell into gzipped JSON tiles. A search fetches only the tiles under the
chosen area (busiest first, capped at 120 tiles / 350k rows for
province-sized boxes), filters by category or name, and merges duplicates
— all in the browser.

## Setting up a new deployment

1. Create a Supabase project. In **SQL Editor**, paste and run
   `supabase/schema.sql`.
2. **Authentication → Providers → Email**: turn **Confirm email** off (users
   are created by a manager, not by email invite).
3. Put the project's URL and anon key in `yp-site/config.js`, push.
4. Open `manager.html` on the live site and create the manager account.

## Refreshing the business data

Overture publishes roughly monthly. Update `RELEASE` in `fetch_overture.py`,
then:

```bash
python fetch_overture.py        # data/places-ca.parquet  (~4 min)
python build_fsa.py             # yp-site/fsa.geojson
python build_places_index.py    # yp-site/places-index.js
python build_tiles.py           # yp-site/tiles/
git add -A && git commit -m "Refresh places" && git push
```

## Running locally

Any static file server over `yp-site/` works, e.g.
`python -m http.server 8787 --directory yp-site`. The old self-hosted server
(`serve.py` + SQLite) still runs too — see `deploy/README.md` — but the
pages now talk to Supabase, so it only serves files.
