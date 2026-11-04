"""Offline tests for the permanent archive (tools/archive_lib.py, build_archive.py, backfill_archive.py).
Synthetic deleted-today.json-shaped snapshots only; no network, no live files, no git history reads."""
import json, os, re, subprocess, sys

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, TOOLS)
import archive_lib as al  # noqa: E402
import build_deleted_today as b  # noqa: E402

PLATFORM_NAMES = {"baidu": "Baidu 百度", "weibo": "Weibo 微博", "toutiao": "Toutiao 今日头条"}


def item(platform="baidu", title_zh="某话题", title_en="Some Topic", label="Dropped off", label_zh="已下榜",
         peak_rank=5, first_missing_et="Nov 3, 3:15 AM ET", minutes_on_list=60,
         url="https://example.invalid/s?wd=x", evidence=None, official_line=None, official_line_zh=None,
         evidence_strength="standard"):
    return {
        "platform": platform, "platform_name": PLATFORM_NAMES.get(platform, platform),
        "title_zh": title_zh, "title_en": title_en, "label": label, "label_zh": label_zh,
        "evidence_strength": evidence_strength, "peak_rank": peak_rank,
        "first_seen_et": "Nov 3, 1:00 AM ET", "last_seen_et": "Nov 3, 3:10 AM ET",
        "first_missing_et": first_missing_et, "minutes_on_list": minutes_on_list, "url": url,
        "official_line": official_line, "official_line_zh": official_line_zh,
        "evidence": evidence if evidence is not None else [f"Dropped off while hot 热度高时突然消失: peak #{peak_rank}"],
    }


def snapshot(items, generated_at_et="2026-11-03 07:20 ET"):
    return {"generated_at_et": generated_at_et, "window_hours": 24, "label": "x", "note": "x",
            "count": len(items), "cut": {}, "items": items}


def run_build_archive(tmp_path, items, generated_at_et="2026-11-03 07:20 ET", out_dir=None):
    src = tmp_path / "deleted-today.json"
    src.write_text(json.dumps(snapshot(items, generated_at_et), ensure_ascii=False))
    out = out_dir or (tmp_path / "docs")
    out.mkdir(exist_ok=True)
    subprocess.run([sys.executable, os.path.join(TOOLS, "build_archive.py"), str(src), str(out)],
                    check=True, capture_output=True, text=True)
    return out


def all_bytes(out_dir):
    data = {}
    for root, _, files in os.walk(out_dir):
        for fn in files:
            p = os.path.join(root, fn)
            data[os.path.relpath(p, out_dir)] = open(p, "rb").read()
    return data


# ---- merge append ----

def test_merge_append_keeps_existing_items(tmp_path):
    out = tmp_path / "docs"
    a = item(title_zh="第一个话题", platform="baidu", first_missing_et="Nov 3, 3:15 AM ET")
    run_build_archive(tmp_path, [a], out_dir=out)
    day = json.loads((out / "archive" / "2026-11-03.json").read_text())
    assert [i["title_zh"] for i in day["items"]] == ["第一个话题"]

    c = item(title_zh="第二个话题", platform="toutiao", first_missing_et="Nov 3, 5:00 AM ET")
    run_build_archive(tmp_path, [c], generated_at_et="2026-11-03 09:00 ET", out_dir=out)
    day = json.loads((out / "archive" / "2026-11-03.json").read_text())
    assert sorted(i["title_zh"] for i in day["items"]) == ["第一个话题", "第二个话题"]


def test_merge_never_removes_items_across_days(tmp_path):
    out = tmp_path / "docs"
    old = item(title_zh="旧话题", first_missing_et="Nov 2, 11:00 PM ET")
    run_build_archive(tmp_path, [old], out_dir=out)
    assert (out / "archive" / "2026-11-02.json").exists()

    new = item(title_zh="新话题", first_missing_et="Nov 3, 1:00 AM ET")
    run_build_archive(tmp_path, [new], generated_at_et="2026-11-03 09:00 ET", out_dir=out)
    # the 2026-11-02 file and its item must still be there untouched
    day2 = json.loads((out / "archive" / "2026-11-02.json").read_text())
    assert [i["title_zh"] for i in day2["items"]] == ["旧话题"]
    assert sorted(al.list_days(out)) == ["2026-11-02", "2026-11-03"]


def test_merge_upserts_same_key_with_latest_version(tmp_path):
    out = tmp_path / "docs"
    a1 = item(title_zh="某话题", peak_rank=5, label="Dropped off", label_zh="已下榜")
    run_build_archive(tmp_path, [a1], out_dir=out)
    # same platform+title+first_missing (the dedupe key) reappears later with more evidence / evidence upgraded
    a2 = item(title_zh="某话题", peak_rank=5, label="Likely censored", label_zh="疑似被删",
              evidence_strength="stronger", evidence=["Hard evidence 确凿证据: the topic link returns 404/410 链接已失效"])
    run_build_archive(tmp_path, [a2], generated_at_et="2026-11-03 09:00 ET", out_dir=out)
    day = json.loads((out / "archive" / "2026-11-03.json").read_text())
    assert len(day["items"]) == 1
    assert day["items"][0]["label"] == "Likely censored"


# ---- idempotence ----

def test_two_runs_on_same_input_are_byte_identical(tmp_path):
    items = [item(title_zh="话题甲", platform="baidu", peak_rank=1, first_missing_et="Nov 3, 3:15 AM ET"),
             item(title_zh="话题乙", platform="toutiao", peak_rank=2, first_missing_et="Nov 2, 9:51 PM ET",
                  label="Likely censored", label_zh="疑似被删", evidence_strength="stronger",
                  official_line={"source": "Tencent News 腾讯网", "title": "后续", "url": "https://example.invalid/a",
                                 "published": "2026-11-03 10:00:00"})]
    src = tmp_path / "deleted-today.json"
    src.write_text(json.dumps(snapshot(items), ensure_ascii=False))
    out1, out2 = tmp_path / "docs1", tmp_path / "docs2"
    for out in (out1, out2):
        out.mkdir()
        subprocess.run([sys.executable, os.path.join(TOOLS, "build_archive.py"), str(src), str(out)],
                        check=True, capture_output=True, text=True)
    assert all_bytes(out1) == all_bytes(out2)

    # running again into the SAME dir (append path) must also be a no-op
    before = all_bytes(out1)
    subprocess.run([sys.executable, os.path.join(TOOLS, "build_archive.py"), str(src), str(out1)],
                    check=True, capture_output=True, text=True)
    assert all_bytes(out1) == before


# ---- wording rules ----

def test_no_forbidden_wording_in_archive_output(tmp_path):
    items = [
        item(title_zh="某突发事件", platform="weibo", peak_rank=1, first_missing_et="Nov 3, 3:15 AM ET",
             label="Likely censored", label_zh="疑似被删", evidence_strength="stronger",
             evidence=["Hard evidence 确凿证据: the topic link returns 404/410 链接已失效"],
             official_line="No official comment found"),
        item(title_zh="另一个话题", platform="baidu", peak_rank=2, first_missing_et="Nov 3, 2:00 AM ET"),
    ]
    out = run_build_archive(tmp_path, items)
    texts = []
    for root, _, files in os.walk(out):
        for fn in files:
            if fn.endswith((".html", ".xml", ".txt", ".json")):
                texts.append((os.path.join(root, fn), open(os.path.join(root, fn), encoding="utf-8").read()))
    for path, text in texts:
        assert "撤下" not in text, path
        from urllib.parse import urlparse
        assert urlparse(b.X402).hostname not in text, path
        assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text, re.I), path
        if path.endswith(".html"):
            assert ">Censored<" not in text, path
            visible = b.html.unescape(text)
            # the literal word "deleted" may only appear inside the deleted-today.json filename/URL
            lowered = visible.lower()
            idx = lowered.find("deleted")
            while idx != -1:
                assert lowered[idx:idx + len("deleted-today.json")] == "deleted-today.json", (path, lowered[idx - 20:idx + 20])
                idx = lowered.find("deleted", idx + 1)


# ---- sitemap ----

def test_sitemap_contains_all_day_pages(tmp_path):
    out = tmp_path / "docs"
    run_build_archive(tmp_path, [item(title_zh="话题一", first_missing_et="Nov 1, 3:15 AM ET")],
                       generated_at_et="2026-11-01 07:20 ET", out_dir=out)
    run_build_archive(tmp_path, [item(title_zh="话题二", first_missing_et="Nov 2, 3:15 AM ET")],
                       generated_at_et="2026-11-02 07:20 ET", out_dir=out)
    run_build_archive(tmp_path, [item(title_zh="话题三", first_missing_et="Nov 3, 3:15 AM ET")],
                       generated_at_et="2026-11-03 07:20 ET", out_dir=out)
    days = al.list_days(out)
    assert days == ["2026-11-01", "2026-11-02", "2026-11-03"]
    sitemap = (out / "sitemap.xml").read_text()
    for day in days:
        assert f"<loc>{al.SITE}archive/{day}.html</loc>" in sitemap
    assert f"<loc>{al.SITE}archive/index.html</loc>" in sitemap
    assert f"<loc>{al.SITE}privacy.html</loc>" in sitemap
    assert f"<loc>{al.SITE}</loc>" in sitemap


def test_robots_and_llms_txt_reference_sitemap_and_feed(tmp_path):
    out = run_build_archive(tmp_path, [item(title_zh="某话题")])
    robots = (out / "robots.txt").read_text()
    assert robots == "User-agent: *\nAllow: /\nSitemap: https://ownly-network.github.io/china-news-feed-samples/sitemap.xml\n"
    llms = (out / "llms.txt").read_text()
    assert llms.startswith("# Ownly Network")
    assert "> Ownly Network monitors" in llms
    assert "OWNLY NETWORK LLC" not in llms
    assert "5055 Broadway" not in llms
    assert "## Publisher\nChina News Feed." in llms
    assert al.SITE + "feed.xml" in llms and al.SITE + "archive/index.html" in llms


# ---- notable topic pages ----

def test_notable_items_get_topic_pages_others_do_not(tmp_path):
    notable_evidence = item(title_zh="疑似被删话题", peak_rank=5, label="Likely censored", label_zh="疑似被删",
                             evidence_strength="stronger")
    notable_rank = item(title_zh="高排名话题", platform="weibo", peak_rank=1)
    ordinary = item(title_zh="普通话题", platform="toutiao", peak_rank=8)
    out = run_build_archive(tmp_path, [notable_evidence, notable_rank, ordinary])
    day = json.loads((out / "archive" / "2026-11-03.json").read_text())
    by_title = {i["title_zh"]: i for i in day["items"]}
    assert by_title["疑似被删话题"]["notable"] is True
    assert by_title["高排名话题"]["notable"] is True
    assert by_title["普通话题"]["notable"] is False
    topic_files = set(os.listdir(out / "vanished" / "2026-11-03"))
    assert f"{by_title['疑似被删话题']['slug']}.html" in topic_files
    assert f"{by_title['高排名话题']['slug']}.html" in topic_files
    assert f"{by_title['普通话题']['slug']}.html" not in topic_files
