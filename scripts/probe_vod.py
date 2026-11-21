#!/usr/bin/env python3
"""影视接口探测：首页与分类都要能出非空片单，避免“只有 class 分类壳”的站被误判存活。

用法：
    python3 scripts/probe_vod.py --input config/sites.json --alive config/sites.alive.json --dead config/sites.dead.json
说明：
    - type=3（jar 爬虫）无法离线探测，直接保留并标注 unprobeable；
    - type=0/1/4 与纯 JSON 接口走 HTTP 探测（GET 或 POST ext）；
    - 首页只有 class、没有 list 时，再按第一个分类请求一次分类页，仍为空才判失效；
    - 探测失败的站不删除，移到 sites.dead.json，供人工复核后决定是否彻底摘除。
"""
import argparse, json, sys, time, urllib.error, urllib.parse, urllib.request

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


def http_retry(url, timeout=10, data=None, headers=None, attempts=2):
    last = None
    for i in range(attempts):
        try:
            return http(url, timeout, data, headers)
        except Exception as e:
            last = e
            if i + 1 < attempts:
                time.sleep(0.6)
    raise last


def with_params(url, params):
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def shape_ok(text):
    """返回 (是否已有非空片单, 原因)。class-only 需要继续请求分类页。"""
    try:
        obj = json.loads(text)
    except Exception:
        return False, "not-json"
    if isinstance(obj, list):
        return (len(obj) > 0), "list-root"

    if not isinstance(obj, dict):
        return False, "bad-type"

    for key in ("list", "vod"):
        value = obj.get(key)
        if isinstance(value, list) and value:
            return True, f"{key}={len(value)}"

    data = obj.get("data")
    if isinstance(data, dict):
        for key in ("list", "vod"):
            value = data.get(key)
            if isinstance(value, list) and value:
                return True, f"data.{key}={len(value)}"
    if isinstance(data, list) and data:
        return True, f"data={len(data)}"

    classes = obj.get("class") or obj.get("categories")
    if isinstance(classes, list) and classes:
        return False, f"class-only({len(classes)})"

    return False, f"no-list; keys={sorted(obj.keys())[:6]}"


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
            text = http_retry(api, timeout, body, site.get("header"))
        else:
            text = http_retry(api, timeout, None, site.get("header"))
    except Exception as e:
        return False, f"{type(e).__name__}"

    ok, why = shape_ok(text)
    if ok:
        return True, why
    if not why.startswith("class-only"):
        return False, why

    # 首页只返回分类壳时，按第一个分类再探测一次真实列表。
    try:
        obj = json.loads(text)
        classes = obj.get("class") or obj.get("categories") or []
        type_id = str((classes[0] or {}).get("type_id") or "").strip()
        if not type_id:
            return False, f"{why}; no-type-id"
        ac = "videolist" if site.get("type") == 0 else "detail"
        category_url = with_params(api, {"ac": ac, "t": type_id, "pg": "1"})
        category_text = http_retry(category_url, timeout, None, site.get("header"))
        category_ok, category_why = shape_ok(category_text)
        return category_ok, f"{why}; category={category_why}"
    except Exception as e:
        return False, f"{why}; category={type(e).__name__}"


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
