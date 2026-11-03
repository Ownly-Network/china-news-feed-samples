#!/usr/bin/env python3
"""One-time backfill: build docs/archive/*.json (and the day/topic pages, archive index, sitemap,
feed and llms.txt) from every past hourly snapshot of docs/deleted-today.json in this repo's git
history, plus (optionally) an older read-only repo with earlier snapshots.

Usage: backfill_archive.py <out_dir> [--repo .] [--older-repo PATH]
Reads history with `git log`/`git show` only: no checkout, no writes to any repo.
"""
import argparse, json, subprocess, sys

import archive_lib as al


def commits(repo_dir, path="docs/deleted-today.json"):
    """Oldest-first list of commit SHAs that touched `path` in repo_dir."""
    out = subprocess.run(["git", "-C", repo_dir, "log", "--reverse", "--format=%H", "--", path],
                          capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def show(repo_dir, sha, path="docs/deleted-today.json"):
    r = subprocess.run(["git", "-C", repo_dir, "show", f"{sha}:{path}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def apply_snapshot(data, by_day):
    """Enrich every item in one snapshot and upsert it into by_day[day][key]. A later call for the
    same key overwrites the earlier one, so processing snapshots oldest-first keeps the latest
    (most complete) version of each item."""
    ref = al.parse_generated_at(data.get("generated_at_et"))
    if ref is None:
        return 0
    n = 0
    for item in data.get("items", []):
        enriched = al.enrich(item, ref)
        if enriched is None:
            continue
        by_day.setdefault(enriched["day"], {})[enriched["key"]] = enriched
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--repo", default=".", help="this repo's working directory (default: cwd)")
    ap.add_argument("--older-repo", help="read-only clone with earlier snapshots, e.g. "
                     "/workspace/cnf-1020/china-news-feed-samples (processed before --repo)")
    a = ap.parse_args()

    by_day = {}
    total_snapshots = 0
    for repo in [r for r in (a.older_repo, a.repo) if r]:
        shas = commits(repo)
        print(f"{repo}: {len(shas)} snapshot(s)", file=sys.stderr)
        for sha in shas:
            data = show(repo, sha)
            if data is None:
                continue
            apply_snapshot(data, by_day)
            total_snapshots += 1

    for day, items_by_key in by_day.items():
        al.merge_day(a.out_dir, day, list(items_by_key.values()))
    al.regenerate_all(a.out_dir)
    print(f"backfilled {total_snapshots} snapshot(s) into {len(by_day)} day(s); "
          f"archive now has {len(al.list_days(a.out_dir))} day(s) total")


if __name__ == "__main__":
    main()
