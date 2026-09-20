"""Cuts data/places-ca.parquet into small map tiles for in-browser search.

Each 0.25-degree cell becomes yp-site/tiles/<latIdx>_<lonIdx>.json.gz holding
rows as compact arrays (see COLS). tiles/index.json lists every tile with its
row count so the browser can budget a search before fetching anything.

    python build_tiles.py
"""
import gzip
import json
import shutil
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
PARQUET = (HERE / "data" / "places-ca.parquet").as_posix()
OUT = HERE / "yp-site" / "tiles"
STEP = 0.25

COLS = ["name", "street", "city", "province", "postcode", "category",
        "alt_categories", "phone", "website", "lat", "lon", "confidence"]


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT floor(lat/{STEP})::INT AS a, floor(lon/{STEP})::INT AS b,
               name, street, city, province, postcode, category,
               array_to_string(alt_categories, '|') AS alt_categories,
               phone, website, round(lat, 5), round(lon, 5), round(confidence, 3)
        FROM read_parquet('{PARQUET}')
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY 1, 2, confidence DESC
    """).fetchall()

    index = {}
    key, buf = None, []

    def flush():
        if not buf:
            return
        name = f"{key[0]}_{key[1]}"
        with gzip.open(OUT / f"{name}.json.gz", "wt", encoding="utf-8", compresslevel=9) as f:
            json.dump(buf, f, ensure_ascii=False, separators=(",", ":"))
        index[name] = len(buf)

    for r in rows:
        k = (r[0], r[1])
        if k != key:
            flush()
            key, buf = k, []
        buf.append([v if v is not None else "" for v in r[2:]])
    flush()

    (OUT / "index.json").write_text(json.dumps(
        {"step": STEP, "cols": COLS, "tiles": index}, separators=(",", ":")), encoding="utf-8")

    total = sum(index.values())
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"{len(index):,} tiles, {total:,} places, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
