"""Join StatCan FSA boundaries to business counts from the Overture extract.

Canada Post's own route geography (letter-carrier walks, rural routes, and the
delivery-mode counts that split a route into houses / apartments / businesses)
is a licensed product with no public API. FSA — the first three characters of a
postal code — is the finest postal geography published as open data, so that is
what this builds on.

Writes yp-site/fsa.geojson.
"""
import json
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
SHP = (HERE / "data" / "fsa" / "lfsa000b21a_e" / "lfsa000b21a_e.shp").as_posix()
PLACES = (HERE / "data" / "places-ca.parquet").as_posix()
OUT = HERE / "yp-site" / "fsa.geojson"

SRC_SRS = "EPSG:3347"          # NAD83 / Statistics Canada Lambert
TOLERANCE = 0.004              # ~400 m, enough detail at province zoom
VALID = "regexp_matches(upper(replace(postcode,' ','')), '^[A-Z][0-9][A-Z][0-9][A-Z][0-9]$')"

# Canada Post counts farms as their own delivery type; these are the Overture
# categories that correspond to it.
FARM_CATEGORIES = [
    "farm", "farmers_market", "agricultural_service", "agriculture",
    "livestock_breeder", "agricultural_cooperatives", "farming_services",
    "farm_equipment_and_supply", "urban_farm", "dairy_farm", "poultry_farm",
    "orchard", "vineyard", "cattle_farm", "pig_farm", "fish_farm",
]


def main():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; SET enable_progress_bar=false;")

    print("aggregating businesses and farms by FSA …", flush=True)
    farms = "[" + ",".join(f"'{c}'" for c in FARM_CATEGORIES) + "]"
    con.execute(f"""
        CREATE TEMP TABLE agg AS
        SELECT substr(upper(replace(postcode,' ','')),1,3) AS fsa,
               count(*)                                    AS businesses,
               count(*) FILTER (WHERE list_contains({farms}, category))  AS farms,
               count(DISTINCT upper(replace(postcode,' ',''))) AS postal_codes,
               mode(category)                              AS top_category
        FROM read_parquet('{PLACES}')
        WHERE postcode IS NOT NULL AND {VALID}
        GROUP BY 1;
    """)
    n_fsa = con.execute("SELECT count(*) FROM agg").fetchone()[0]
    print(f"  {n_fsa:,} FSAs carry businesses")

    print("reprojecting and simplifying polygons …", flush=True)
    rows = con.execute(f"""
        SELECT b.CFSAUID AS fsa,
               b.PRNAME  AS province,
               b.LANDAREA AS area_km2,
               coalesce(a.businesses, 0)   AS businesses,
               coalesce(a.farms, 0)        AS farms,
               coalesce(a.postal_codes, 0) AS postal_codes,
               a.top_category,
               ST_AsGeoJSON(
                 ST_Simplify(
                   ST_Transform(b.geom, '{SRC_SRS}', 'EPSG:4326', always_xy := true),
                   {TOLERANCE})) AS gj
        FROM ST_Read('{SHP}') b
        LEFT JOIN agg a ON a.fsa = b.CFSAUID
        ORDER BY b.CFSAUID;
    """).fetchall()

    feats = []
    for fsa, prov, area, biz, farm, codes, cat, gj in rows:
        if not gj:
            continue
        density = round(biz / area, 1) if area else 0
        feats.append({
            "type": "Feature",
            "properties": {
                "fsa": fsa,
                "province": (prov or "").split(" / ")[0],
                "businesses": biz,
                "farms": farm,
                "postal_codes": codes,
                "top_category": (cat or "").replace("_", " "),
                "area_km2": round(area or 0, 1),
                "per_km2": density,
            },
            "geometry": json.loads(gj),
        })

    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                              separators=(",", ":")), encoding="utf-8")

    total = sum(f["properties"]["businesses"] for f in feats)
    dense = sorted(feats, key=lambda f: -f["properties"]["per_km2"])[:10]
    print(f"\nwrote {OUT} — {len(feats):,} FSAs, {total:,} businesses, "
          f"{OUT.stat().st_size/1e6:.1f} MB")
    print("\ndensest FSAs (businesses per km²):")
    for f in dense:
        p = f["properties"]
        print(f"  {p['fsa']}  {p['per_km2']:>8,.1f}/km²  {p['businesses']:>5,} businesses  {p['province']}")


if __name__ == "__main__":
    main()
