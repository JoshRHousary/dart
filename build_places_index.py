"""Build the What/Where lookup index: every Canadian city and province in the
Overture extract, with a bounding box.

Bounds use the 1st/99th percentile of member coordinates so a single
mis-geocoded record can't stretch a city across the province.

Writes yp-site/places-index.js.
"""
import json
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
PARQUET = (HERE / "data" / "places-ca.parquet").as_posix()
OUT = HERE / "yp-site" / "places-index.js"
MIN_BUSINESSES = 5

PROVINCES = {
    "ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta",
    "MB": "Manitoba", "SK": "Saskatchewan", "NS": "Nova Scotia",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island", "YT": "Yukon", "NT": "Northwest Territories",
    "NU": "Nunavut",
}

BOUNDS = """
    quantile_cont(lat, 0.01) AS s, quantile_cont(lon, 0.01) AS w,
    quantile_cont(lat, 0.99) AS n, quantile_cont(lon, 0.99) AS e
"""
# Case-normalised province code, restricted to the real ones.
PROV = "upper(trim(province))"
KEEP = "upper(trim(province)) IN (" + ",".join(f"'{p}'" for p in PROVINCES) + ")"


def box(s, w, n, e):
    """Pad a degenerate box (a town with one coordinate) to something searchable."""
    if n - s < 0.02:
        s, n = s - 0.01, n + 0.01
    if e - w < 0.02:
        w, e = w - 0.015, e + 0.015
    return [round(v, 4) for v in (s, w, n, e)]


def main():
    con = duckdb.connect()

    provinces = []
    for code, n, s_, w_, n_, e_ in con.execute(f"""
        SELECT {PROV} AS code, count(*) AS n, {BOUNDS}
        FROM read_parquet('{PARQUET}')
        WHERE {KEEP} AND lat IS NOT NULL
        GROUP BY 1 ORDER BY n DESC
    """).fetchall():
        provinces.append({"code": code, "name": PROVINCES[code],
                          "n": n, "bbox": box(s_, w_, n_, e_)})

    cities = []
    for city, code, n, s_, w_, n_, e_ in con.execute(f"""
        SELECT trim(city) AS city, {PROV} AS code, count(*) AS n, {BOUNDS}
        FROM read_parquet('{PARQUET}')
        WHERE {KEEP} AND city IS NOT NULL AND trim(city) <> '' AND lat IS NOT NULL
        GROUP BY 1, 2
        HAVING count(*) >= {MIN_BUSINESSES}
        ORDER BY city
    """).fetchall():
        cities.append({"city": city, "prov": code, "n": n, "bbox": box(s_, w_, n_, e_)})

    payload = {"provinces": provinces, "cities": cities}
    OUT.write_text("window.PLACE_INDEX = " + json.dumps(payload, separators=(",", ":")) + ";\n",
                   encoding="utf-8")

    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB)")
    print(f"  {len(provinces)} provinces, {len(cities):,} cities (>= {MIN_BUSINESSES} businesses)")
    print("\nlargest cities:")
    for c in sorted(cities, key=lambda c: -c["n"])[:8]:
        print(f"   {c['city']:<22} {c['prov']}  {c['n']:>7,}  {c['bbox']}")


if __name__ == "__main__":
    main()
