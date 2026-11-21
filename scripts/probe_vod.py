#!/usr/bin/env python3
"""影视接口探测：按 Site 类型打一次首页请求，判断接口当天是否还能出片单。

用法：
    python3 scripts/probe_vod.py --input config/sites.json --alive config/sites.alive.json --dead config/sites.dead.json
说明：
    - type=3（jar 爬虫）无法离线探测，直接保留并标注 unprobeable；
    - type=0/1/4 与纯 JSON 接口走 HTTP 探测（GET 或 POST ext）；
    - 探测失败的站不删除，移到 sites.dead.json，供人工复核后决定是否彻底摘除。
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

UA = "okhttp/4.12.0"

def http(url, timeout=10, data=None, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def shape_ok(text):
    """首页响应至少要能解析成 JSON，且带 class/list/vod 之一。"""
    try:
        obj = json.loads(text)
    except Exception:
        return False, "not-json"
    if not isinstance(obj, (dict, list)):
        return False, "bad-type"
    if isinstance(obj, list):
        return (len(obj) > 0), "list-root"
    keys = set(obj.keys())
    hit = keys & {"class", "list", "vod", "data", "categories"}
    return bool(hit), f"keys={sorted(keys)[:6]}"

def probe(site, timeout=10):
    if site.get("disabled"):
        return None, "disabled"
    api = (site.get("api") or "").strip()
    if site.get("type") == 3 or api.startswith("csp_") or api.startswith("./") or api.endswith((".js", ".py")):
        return None, "unprobeable(crawler)"
    if not api.lower().startswith(("http://", "https://")):
        return None, "unprobeable(no-url)"
    ext = site.get("ext")
    try:
        if site.get("type") == 4:
            body = {"ext": ext if isinstance(ext, str) else json.dumps(ext or {})}
            text = http(api, timeout, body, site.get("header"))
        else:
            text = http(api, timeout, None, site.get("header"))
    except Exception as e:
        return False, f"{type(e).__name__}"
    ok, why = shape_ok(text)
    return ok, why

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="config/sites.json")
    ap.add_argument("--alive", default="config/sites.alive.json")
    ap.add_argument("--dead", default="config/sites.dead.json")
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    sites = json.load(open(args.input, encoding="utf-8"))
    alive, dead = [], []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for s in sites:
        start = time.time()
        ok, why = probe(s, args.timeout)
        ms = int((time.time() - start) * 1000)
        rec = dict(s)
        rec["probe"] = {"state": "skip" if ok is None else ("ok" if ok else "dead"), "why": why, "at": now, "ms": ms}
        if ok is None:
            alive.append(rec)
            print(f"  ~ {rec.get('key')}: {why} ({ms}ms)")
        elif ok:
            alive.append(rec)
            print(f"  + {rec.get('key')}: {why} ({ms}ms)")
        else:
            dead.append(rec)
            print(f"  - {rec.get('key')}: {why} ({ms}ms)")

    json.dump(alive, open(args.alive, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(dead, open(args.dead, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"存活 {len(alive)} / 失效 {len(dead)}")

if __name__ == "__main__":
    sys.exit(main())
