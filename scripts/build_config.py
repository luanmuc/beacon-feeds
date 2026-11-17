#!/usr/bin/env python3
"""把 base.json + sites.alive.json + live/all.m3u 合并成唯一的 tvbox.json。

用法：
    RAW_BASE=https://raw.githubusercontent.com/<owner>/<repo>/main python3 scripts/build_config.py
说明：
    - base.json 里的 {RAW_BASE} 占位符会被环境变量替换；
    - lives 指向 live/all.m3u，sites 用探测后的存活清单；
    - 生成前做必填校验（sites 的 key/name/api、lives 的 name/url），失败即非零退出（CI 会红）。
"""
import json, os, re, sys

def load(path, default=None):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding="utf-8"))

def check_sites(sites):
    errs = []
    seen = set()
    for s in sites:
        for f in ("key", "name", "api"):
            if not str(s.get(f) or "").strip():
                errs.append(f"site 缺字段 {f}: {s}")
        k = s.get("key")
        if k in seen:
            errs.append(f"site key 重复: {k}")
        seen.add(k)
    return errs

def check_lives(lives):
    errs = []
    for l in lives:
        for f in ("name",):
            if not str(l.get(f) or "").strip():
                errs.append(f"live 缺字段 {f}: {l}")
        if not (l.get("url") or l.get("api")):
            errs.append(f"live 既无 url 也无 api: {l}")
    return errs

def main():
    base = load("config/base.json", {}) or {}
    sites = load("config/sites.alive.json", None)
    if sites is None:
        sites = load("config/sites.json", []) or []
    lives = base.get("lives", [])
    raw_base = os.environ.get("RAW_BASE", "").rstrip("/")

    def sub(obj):
        if isinstance(obj, str):
            return obj.replace("{RAW_BASE}", raw_base or "https://raw.githubusercontent.com/OWNER/REPO/main")
        if isinstance(obj, list):
            return [sub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: sub(v) for k, v in obj.items()}
        return obj

    cfg = {
        "name": base.get("name", "自制订阅"),
        "spider": sub(base.get("spider", "")),
        "lives": sub(lives),
        "sites": [dict(s) for s in sites if not s.get("disabled")],
        "parses": sub(base.get("parses", [])),
        "flags": base.get("flags", []),
    }
    if base.get("headers"):
        cfg["headers"] = sub(base["headers"])
    if base.get("wallpaper"):
        cfg["wallpaper"] = sub(base["wallpaper"])

    errs = check_sites(cfg["sites"]) + check_lives(cfg["lives"])
    if errs:
        print("校验失败：", *errs, sep="\n  ")
        return 1
    if not raw_base:
        print("! 未设置 RAW_BASE，lives.url 里仍是占位符，仅可用于本地检查")

    out = json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True)
    os.makedirs("config", exist_ok=True)
    open("tvbox.json", "w", encoding="utf-8").write(out + "\n")
    print(f"写出 tvbox.json：sites={len(cfg['sites'])} lives={len(cfg['lives'])}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
