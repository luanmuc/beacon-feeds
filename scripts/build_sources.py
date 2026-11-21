#!/usr/bin/env python3
"""把探测后的存活影视接口整理成 QuickJS 源可读的 vod-sites.json。

只保留 type=1、HTTP(S)、非 disabled 的 JSON 接口；探测失败的站留在
config/sites.dead.json，不进入运行时聚合池，避免单源脚本启动时被坏站拖慢。
"""
import argparse
import datetime
import json
import pathlib
import sys


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="config/sites.alive.json")
    ap.add_argument("--fallback", default="config/sites.json")
    ap.add_argument("--out", default="vod-sites.json")
    args = ap.parse_args()

    sites = load(args.input)
    if sites is None:
        sites = load(args.fallback, [])
    if not isinstance(sites, list):
        sites = []

    rows = []
    for site in sites:
        if not isinstance(site, dict) or site.get("disabled"):
            continue
        if site.get("type") != 1:
            continue
        api = str(site.get("api") or "").strip()
        if not api.lower().startswith(("http://", "https://")):
            continue
        row = {
            "key": str(site.get("key") or "").strip(),
            "name": str(site.get("name") or "").strip(),
            "api": api,
        }
        if not row["key"] or not row["name"]:
            continue
        for field in ("searchable", "quickSearch", "header", "ext", "probe"):
            if site.get(field) not in (None, "", {}, []):
                row[field] = site[field]
        rows.append(row)

    rows.sort(key=lambda item: item["key"])
    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sites": rows,
    }
    pathlib.Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写出 {args.out}：{len(rows)} 个影视接口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
