#!/usr/bin/env python3
"""Shared rendering/merge logic for the permanent archive (docs/archive/, docs/vanished/) built from
deleted-today.json snapshots. Used by build_archive.py (daily append) and backfill_archive.py (one-time
backfill from git history). No wall-clock reads anywhere: every date comes from the data itself, so
regenerate_all() produces byte-identical output when run twice on the same docs/archive/*.json files.
"""
import hashlib, html, json, os, re
from datetime import datetime, timedelta

import build_deleted_today as b

ET = b.ET
SITE = b.SITE
OG_IMAGE = b.OG_IMAGE
REPO = b.REPO

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_DISP_RE = re.compile(r"^(\w{3}) (\d{1,2}), (\d{1,2}):(\d{2}) (AM|PM) ET$")


def parse_generated_at(s):
    """Parse a "YYYY-MM-DD HH:MM ET" generated_at_et string into an ET-aware datetime, or None."""
    if not s:
        return None
    try:
        return datetime.strptime(s.replace(" ET", ""), "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    except ValueError:
        return None


def parse_display_et(s, ref):
    """Parse a "%b %-d, %-I:%M %p ET"-style display string (no year) into an ET datetime, inferring
    the year from `ref` (the snapshot's generated_at_et, close in time) and correcting a Dec/Jan
    year rollover: if the naive guess lands far in ref's future, the event was actually last year."""
    m = _DISP_RE.match(s or "")
    if not m or ref is None:
        return None
    mon, day, hh, mm, ap = m.groups()
    month = _MONTHS.get(mon)
    if not month:
        return None
    hour = (int(hh) % 12) + (12 if ap == "PM" else 0)
    dt = datetime(ref.year, month, int(day), hour, int(mm), tzinfo=ET)
    if dt > ref + timedelta(days=3):
        dt = dt.replace(year=ref.year - 1)
    return dt


def slug_for(item):
    digest = hashlib.sha1((item.get("title_zh") or "").encode("utf-8")).hexdigest()[:12]
    return f"{item.get('platform') or 'x'}-{digest}"


def key_for(item, iso):
    return f"{item.get('platform')}|{item.get('title_zh')}|{iso}"


def is_notable(item):
    pr = item.get("peak_rank")
    return item.get("label") == "Likely censored" or (isinstance(pr, int) and pr <= 3)


def enrich(item, ref):
    """Return a copy of `item` with first_missing_iso/day/slug/key/notable added, or None if its
    first_missing_et can't be parsed."""
    dt = parse_display_et(item.get("first_missing_et"), ref)
    if dt is None:
        return None
    it = dict(item)
    it["first_missing_iso"] = dt.isoformat(timespec="seconds")
    it["day"] = dt.strftime("%Y-%m-%d")
    it["slug"] = slug_for(item)
    it["key"] = key_for(item, it["first_missing_iso"])
    it["notable"] = is_notable(item)
    return it


def _sort_items(items):
    return sorted(items, key=lambda r: (r["first_missing_iso"], r["platform"] or "", r["title_zh"] or ""))


# ---- per-day JSON store ----

def archive_dir(out_dir):
    return os.path.join(out_dir, "archive")


def day_json_path(out_dir, day):
    return os.path.join(archive_dir(out_dir), f"{day}.json")


def day_html_path(out_dir, day):
    return os.path.join(archive_dir(out_dir), f"{day}.html")


def load_day_items(out_dir, day):
    """{key: item} for a day's JSON store, or {} if it doesn't exist yet."""
    p = day_json_path(out_dir, day)
    if not os.path.exists(p):
        return {}
    data = json.load(open(p))
    return {it["key"]: it for it in data.get("items", [])}


def save_day_items(out_dir, day, items_by_key):
    os.makedirs(archive_dir(out_dir), exist_ok=True)
    items = _sort_items(items_by_key.values())
    json.dump({"date": day, "count": len(items), "items": items}, open(day_json_path(out_dir, day), "w"),
               ensure_ascii=False, indent=1, sort_keys=True)


def merge_day(out_dir, day, new_items):
    """Upsert `new_items` (already enriched) into docs/archive/<day>.json by key. Existing items for
    other keys are kept; an item with the same key is replaced by the new (more complete) version.
    Calling this twice with the same new_items is a no-op the second time (idempotent)."""
    existing = load_day_items(out_dir, day)
    for it in new_items:
        existing[it["key"]] = it
    save_day_items(out_dir, day, existing)


def list_days(out_dir):
    d = archive_dir(out_dir)
    if not os.path.isdir(d):
        return []
    days = [fn[:-5] for fn in os.listdir(d) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", fn)]
    return sorted(days)


# ---- shared HTML bits ----

def meta_head(title, desc, url, type_="website"):
    e = html.escape
    return (f'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title>'
            f'<meta name="description" content="{e(desc)}">'
            f'{b.meta_tags(title, desc, url, type_)}'
            f'<style>{b.CSS}</style>')


def evidence_li(ev_list):
    e = html.escape
    out = []
    for x in ev_list or []:
        if isinstance(x, dict):
            link = (f'<a href="{e(x["url"])}" rel="nofollow noopener" target="_blank">{e(x.get("source") or "")}</a>'
                    if x.get("url") else e(x.get("source") or ""))
            pub = f" ({e(x['published'])})" if x.get("published") else ""
            out.append(f"<li>{e(x.get('type') or '')}: {link}{pub}</li>")
        else:
            out.append(f"<li>{e(x)}</li>")
    return "".join(out)


def _evidence_block(r):
    e = html.escape
    ev = [f"<li>On the list 上榜 {e(r['first_seen_et'])} → last seen 最后出现 {e(r['last_seen_et'])} · "
          f"{e(b.mins(r['minutes_on_list']))} on list 在榜时长</li>", evidence_li(r.get("evidence"))]
    ol = r.get("official_line")
    if isinstance(ol, dict) and ol.get("url"):
        pub = f" ({e(ol['published'])})" if ol.get("published") else ""
        ev.append(f'<li>Related coverage still online 相关报道: <a href="{e(ol["url"])}" '
                  f'rel="nofollow noopener" target="_blank">{e(b.bilingual(ol.get("source")))}: '
                  f'{e(ol.get("title") or "")}</a>{pub}</li>')
    elif isinstance(ol, str) and ol:
        ev.append(f"<li>Official response 官方回应: {e(ol)} / {e(r.get('official_line_zh') or '')}</li>")
    if r.get("url"):
        ev.append(f'<li><a href="{e(r["url"])}" rel="nofollow noopener" target="_blank">'
                  f'Search this topic on {e(r["platform_name"])}</a></li>')
    return "".join(ev)


def card_html(r, day):
    e = html.escape
    color = b.PLATFORM_COLORS.get(r["platform"], "#555")
    evid = r.get("evidence_strength") == "stronger"
    zh = e(r["title_zh"])
    if r.get("notable"):
        zh = f'<a href="../vanished/{e(day)}/{e(r["slug"])}.html">{zh}</a>'
    en = (f'<p class="en">{e(r["title_en"])}</p>' if r.get("title_en")
          else '<p class="en pending">English translation pending · 英文翻译待补</p>')
    return f"""<article class="card" data-p="{e(r['platform'] or '')}">
<div class="top"><span class="plat" style="background:{color}">{e(r['platform_name'])}</span><span class="lab{'' if evid else ' off'}">{e(r.get('label') or '')} {e(r.get('label_zh') or '')}</span><span class="rank">peak #{e(str(r['peak_rank']))}</span></div>
<p class="zh">{zh}</p>{en}
<div class="times">Dropped off at: {e(r['first_missing_et'])} 下榜时间：{e(r['first_missing_et'])}</div>
<details><summary>Evidence 证据</summary><ul>{_evidence_block(r)}</ul></details></article>"""


# ---- pages ----

def render_day_html(day, items, all_days):
    e = html.escape
    idx = all_days.index(day)
    prev_day = all_days[idx - 1] if idx > 0 else None
    next_day = all_days[idx + 1] if idx < len(all_days) - 1 else None
    pretty = datetime.strptime(day, "%Y-%m-%d").strftime("%B %-d, %Y")
    url = f"{SITE}archive/{day}.html"
    title = f"Dropped off {pretty} · {day}下榜 | China hot-list watch archive"
    desc = (f"{len(items)} hot-list topics that left Weibo, Baidu, Zhihu, Toutiao or Bilibili on "
            f"{pretty} and didn't return.")
    cards = "".join(card_html(r, day) for r in items) or '<div class="empty">No archived topics for this day.</div>'
    nav = ['<a href="index.html">All days 往日存档</a>']
    if prev_day:
        nav.insert(0, f'<a href="{e(prev_day)}.html">← {e(prev_day)}</a>')
    if next_day:
        nav.append(f'<a href="{e(next_day)}.html">{e(next_day)} →</a>')
    return f"""<!doctype html><html lang="en"><head>{meta_head(title, desc, url)}</head><body>
<header><div class="wrap"><p class="nav"><a href="../index.html">Dropped off today 今日下榜</a> · <a href="index.html">Archive 往日存档</a></p>
<h1>Dropped off {e(pretty)} <span>{e(day)}下榜</span></h1>
<p class="sub">{len(items)} topics left a hot list on this day and didn't return.</p>
<p class="sub nav">{" · ".join(nav)}</p></div></header>
<main class="wrap"><section class="grid">{cards}</section></main>
<footer class="wrap">Built by Ownly from public, logged-out sources. Source: <a href="{REPO}">{REPO.split('github.com/')[1]}</a>.</footer>
</body></html>"""


def render_topic_html(day, r):
    e = html.escape
    url = f"{SITE}vanished/{day}/{r['slug']}.html"
    title = f"{r['title_zh']} — {r.get('title_en') or r.get('label') or 'Dropped off'} | {r['platform_name']} | China hot-list watch"
    desc = (f'{r["platform_name"]}: "{r["title_zh"]}" left the hot list on {day} '
            f'(peak #{r.get("peak_rank")}) and didn\'t return. {r.get("label")} 下榜话题.')
    color = b.PLATFORM_COLORS.get(r["platform"], "#555")
    evid = r.get("evidence_strength") == "stronger"
    en = (f'<p class="en">{e(r["title_en"])}</p>' if r.get("title_en")
          else '<p class="en pending">English translation pending · 英文翻译待补</p>')
    return f"""<!doctype html><html lang="en"><head>{meta_head(title, desc, url, "article")}</head><body>
<header><div class="wrap"><p class="nav"><a href="../../index.html">Dropped off today 今日下榜</a> · <a href="../../archive/index.html">Archive 往日存档</a> · <a href="../../archive/{e(day)}.html">{e(day)}</a></p>
<div class="top"><span class="plat" style="background:{color}">{e(r['platform_name'])}</span><span class="lab{'' if evid else ' off'}">{e(r.get('label') or '')} {e(r.get('label_zh') or '')}</span><span class="rank">peak #{e(str(r['peak_rank']))}</span></div>
<h1 class="zh">{e(r['title_zh'])}</h1>{en}
<div class="times">Dropped off at: {e(r['first_missing_et'])} 下榜时间：{e(r['first_missing_et'])}</div></div></header>
<main class="wrap"><ul class="evidence-list">{_evidence_block(r)}</ul>
<p><a href="../../archive/{e(day)}.html">← Back to {e(day)}</a> · <a href="../../index.html">Live page →</a></p></main>
<footer class="wrap">Built by Ownly from public, logged-out sources. Source: <a href="{REPO}">{REPO.split('github.com/')[1]}</a>.</footer>
</body></html>"""


def render_archive_index_html(day_summaries):
    """day_summaries: [(day, count), ...] ascending by day."""
    e = html.escape
    url = f"{SITE}archive/index.html"
    title = "Archive · 往日存档 | China hot-list watch"
    desc = (f"Every day's dropped-off hot-list topics, {day_summaries[0][0]} to {day_summaries[-1][0]}."
            if day_summaries else "Archive of dropped-off hot-list topics.")
    rows = "".join(f'<li><a href="{e(d)}.html">{e(d)}</a> — {n} topic{"s" if n != 1 else ""}</li>'
                    for d, n in reversed(day_summaries))
    jsonld = {"@context": "https://schema.org", "@type": "Dataset",
              "name": "Ownly Network — Dropped off hot-list topics archive", "description": desc,
              "url": url, "creator": {"@type": "Organization", "name": "Ownly Network"}}
    return f"""<!doctype html><html lang="en"><head>{meta_head(title, desc, url)}
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False, sort_keys=True)}</script></head><body>
<header><div class="wrap"><p class="nav"><a href="../index.html">Dropped off today 今日下榜</a></p>
<h1>Archive <span>往日存档</span></h1><p class="sub">{len(day_summaries)} days archived.</p></div></header>
<main class="wrap"><ul class="archive-list">{rows}</ul></main>
<footer class="wrap">Built by Ownly from public, logged-out sources. Source: <a href="{REPO}">{REPO.split('github.com/')[1]}</a>.</footer>
</body></html>"""


def render_sitemap(days, topic_entries):
    """topic_entries: [(day, item), ...] for notable items only."""
    e = html.escape
    latest = days[-1] if days else None
    urls = []

    def u(loc, lastmod=None):
        lm = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls.append(f"<url><loc>{e(loc)}</loc>{lm}</url>")

    u(SITE, latest)
    u(f"{SITE}privacy.html")
    u(f"{SITE}archive/index.html", latest)
    for d in days:
        u(f"{SITE}archive/{d}.html", d)
    for d, it in topic_entries:
        u(f"{SITE}vanished/{d}/{it['slug']}.html", d)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>")


def render_feed(all_items):
    """all_items: [(day, item), ...]. Newest first, capped at 200."""
    e = html.escape
    newest = sorted(all_items, key=lambda p: p[1]["first_missing_iso"], reverse=True)[:200]
    entries = []
    for day, it in newest:
        link = f"{SITE}vanished/{day}/{it['slug']}.html" if it["notable"] else f"{SITE}archive/{day}.html"
        title = f"{it['title_zh']} — {it.get('title_en') or it.get('label') or ''}"
        summary = (f"{it['platform_name']}: {it.get('label')} {it.get('label_zh')}. "
                   f"Peak rank #{it.get('peak_rank')}. {it.get('first_missing_et')}.")
        entries.append(f"<entry><id>{e(link)}</id><title>{e(title)}</title>"
                        f'<link href="{e(link)}"/><updated>{it["first_missing_iso"]}</updated>'
                        f"<summary>{e(summary)}</summary></entry>")
    updated = newest[0][1]["first_missing_iso"] if newest else "1970-01-01T00:00:00+00:00"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Dropped off — Ownly Network</title>
<subtitle>Topics that left a China hot list abruptly and didn't return.</subtitle>
<id>{SITE}feed.xml</id>
<link href="{SITE}feed.xml" rel="self"/>
<link href="{SITE}"/>
<updated>{updated}</updated>
{"".join(entries)}
</feed>"""


def render_llms_txt(days):
    start, end = (days[0], days[-1]) if days else (None, None)
    coverage = f"{start} to {end}" if start else "no data yet"
    return f"""# Ownly Network — China Hot-List Deletion Watch

> Ownly Network monitors China's hot-search lists (Weibo 微博, Baidu 百度, Zhihu 知乎, Toutiao 今日头条, Bilibili 哔哩哔哩, Douyin 抖音, Kuaishou 快手) and flags topics that leave a list abruptly while still popular. A topic is labeled "Dropped off" by default and "Likely censored" only when there is hard evidence (a dead link, a platform removal notice, or a matching entry on a censorship tracker). Data coverage: {coverage}.

## Live data
- [Dropped off today]({SITE}): topics that left a hot list in the last 24 hours.
- [Today's dropped-off topics as JSON]({SITE}deleted-today.json): the live page as JSON. Item fields: platform, title_zh, title_en, label, label_zh, peak_rank, first_seen_et, last_seen_et, first_missing_et, minutes_on_list, url, evidence, official_line.
- [Atom feed]({SITE}feed.xml): one entry per dropped-off topic, newest first.

## Archive
- [Archive index]({SITE}archive/index.html): every past day, newest first.

## Full product
- [Apify actor — full live feed, $8 per 1,000 rows]({b.ACTOR})
- [Hugging Face dataset — free sample]({b.HF})
- [Hugging Face Space — What vanished this week](https://huggingface.co/spaces/ownly-network/china-deletion-watch)
- [GitHub repo]({REPO})

## Publisher
Ownly Network (OWNLY NETWORK LLC).
"""


def render_robots_txt():
    return f"User-agent: *\nAllow: /\nSitemap: {SITE}sitemap.xml\n"


# ---- top-level: rebuild everything from docs/archive/*.json ----

def regenerate_all(out_dir):
    days = list_days(out_dir)
    all_items, day_summaries, topic_entries = [], [], []
    for day in days:
        items = _sort_items(load_day_items(out_dir, day).values())
        day_summaries.append((day, len(items)))
        open(day_html_path(out_dir, day), "w").write(render_day_html(day, items, days))
        for it in items:
            all_items.append((day, it))
            if it["notable"]:
                topic_entries.append((day, it))
                topic_dir = os.path.join(out_dir, "vanished", day)
                os.makedirs(topic_dir, exist_ok=True)
                open(os.path.join(topic_dir, f"{it['slug']}.html"), "w").write(render_topic_html(day, it))
    os.makedirs(archive_dir(out_dir), exist_ok=True)
    open(os.path.join(archive_dir(out_dir), "index.html"), "w").write(render_archive_index_html(day_summaries))
    open(os.path.join(out_dir, "sitemap.xml"), "w").write(render_sitemap(days, topic_entries))
    open(os.path.join(out_dir, "feed.xml"), "w").write(render_feed(all_items))
    open(os.path.join(out_dir, "llms.txt"), "w").write(render_llms_txt(days))
    open(os.path.join(out_dir, "robots.txt"), "w").write(render_robots_txt())
    return days, topic_entries
