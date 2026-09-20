"""One-time extract of Canadian business places from Overture Maps into a local parquet.

Overture Places is CDLA-Permissive-2.0 open data aggregating Meta, Microsoft and
other contributors. Querying it live over S3 takes ~60s, so pull Canada once and
serve locally.

    python fetch_overture.py
"""
import time
from pathlib import Path

import duckdb

RELEASE = "2026-07-22.0"
SRC = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*.parquet"
OUT = Path(__file__).parent / "data" / "places-ca.parquet"

# Canada: lon -141.0..-52.6, lat 41.6..83.2
QUERY = f"""
COPY (
  SELECT
    id,
    names.primary                                   AS name,
    categories.primary                              AS category,
    list_transform(categories.alternate, x -> x)    AS alt_categories,
    confidence,
    addresses[1].freeform                           AS street,
    addresses[1].locality                           AS city,
    addresses[1].region                             AS province,
    addresses[1].postcode                           AS postcode,
    phones[1]                                       AS phone,
    websites[1]                                     AS website,
    ST_X(geometry)                                  AS lon,
    ST_Y(geometry)                                  AS lat
  FROM read_parquet('{SRC}')
  WHERE bbox.xmin BETWEEN -141.0 AND -52.6
    AND bbox.ymin BETWEEN 41.6 AND 83.2
    AND addresses[1].country = 'CA'
    AND names.primary IS NOT NULL
    AND addresses[1].freeform IS NOT NULL
) TO '{OUT.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
"""


def main():
    OUT.parent.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    con.execute("SET s3_region='us-west-2'; SET enable_progress_bar=true;")

    print(f"extracting Canadian places from Overture {RELEASE} …", flush=True)
    started = time.time()
    con.execute(QUERY)
    mins = (time.time() - started) / 60

    n = con.execute(f"SELECT count(*) FROM read_parquet('{OUT.as_posix()}')").fetchone()[0]
    mb = OUT.stat().st_size / 1e6
    print(f"\n{n:,} places -> {OUT} ({mb:.0f} MB) in {mins:.1f} min")

    print("\ntop categories:")
    for cat, cnt in con.execute(
        f"SELECT category, count(*) c FROM read_parquet('{OUT.as_posix()}') "
        "WHERE category IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT 15"
    ).fetchall():
        print(f"  {cat:<34} {cnt:,}")

    print("\nby province:")
    for prov, cnt in con.execute(
        f"SELECT province, count(*) c FROM read_parquet('{OUT.as_posix()}') "
        "GROUP BY 1 ORDER BY c DESC LIMIT 15"
    ).fetchall():
        print(f"  {str(prov):<34} {cnt:,}")


if __name__ == "__main__":
    main()
