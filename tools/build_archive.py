#!/usr/bin/env python3
"""Merge the current run's deleted-today.json items into the permanent docs/archive/<day>.json
files, then regenerate the archive day/topic pages, archive index, sitemap, feed and llms.txt from
ALL docs/archive/*.json (not just the days touched this run).

Usage: build_archive.py <deleted-today.json> <out_dir>
Idempotent: running twice on the same deleted-today.json produces byte-identical output, and never
removes an item already in the archive.
"""
import json, sys

import archive_lib as al


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: build_archive.py <deleted-today.json> <out_dir>")
    src, out_dir = sys.argv[1], sys.argv[2]
    data = json.load(open(src))
    ref = al.parse_generated_at(data.get("generated_at_et"))
    by_day = {}
    skipped = 0
    for item in data.get("items", []):
        enriched = al.enrich(item, ref)
        if enriched is None:
            skipped += 1
            continue
        by_day.setdefault(enriched["day"], []).append(enriched)
    for day, items in by_day.items():
        al.merge_day(out_dir, day, items)
    al.regenerate_all(out_dir)
    print(f"archived {len(data.get('items', [])) - skipped} item(s) into {len(by_day)} day(s) "
          f"({skipped} skipped); archive now has {len(al.list_days(out_dir))} day(s) total")


if __name__ == "__main__":
    main()
