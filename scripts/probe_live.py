#!/usr/bin/env python3
"""直播源探测：拉取候选 m3u -> 解析频道 -> 逐路探测可用性 -> 合并同名频道 -> 输出 all.m3u。

用法：
    python3 scripts/probe_live.py --input live/sources.txt --out live/all.m3u --report live/report.json
    python3 scripts/probe_live.py --parse-only            # 只解析不探测（离线调试）
候选文件 sources.txt 每行：
    <名字>\t<m3u地址>   或直接写 <m3u地址>；# 开头为注释。
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
TIMEOUT = 8
MAX_URLS_PER_CHANNEL = 3

EXTINF = re.compile(r"#EXTINF:.*?(?:,)(?P<name>.+?)$", re.M)
ATTR = re.compile(r'(?P<k>[a-zA-Z0-9\-]+)="(?P<v>[^"]*)"')

def fetch(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")

def parse_m3u(text):
    """返回 [{name, group, url, attrs}]，容忍 #EXTINF 与 URL 分行/同行两种写法。"""
    channels = []
    pending = None
    attrs = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            for k, v in ATTR.findall(line):
                attrs[k] = v
            continue
        if line.startswith("#EXTINF"):
            m = EXTINF.search(line)
            pending = m.group("name").strip() if m else ""
            pending_attrs = {k.lower(): v for k, v in ATTR.findall(line)}
            pending_attrs["__name"] = pending
            if pending_attrs.get("group-title") is None:
                pass
            attrs_local = pending_attrs
            continue
        if line.startswith("#"):
            continue
        if pending is not None:
            url, _, header = line.partition("|")
            channels.append({
                "name": attrs_local.get("__name") or "",
                "group": attrs_local.get("group-title", "未分组"),
                "url": url.strip(),
                "header": header if header else "",
                "logo": attrs_local.get("tvg-logo", ""),
                "tvg_id": attrs_local.get("tvg-id", ""),
                "chno": attrs_local.get("tvg-chno", ""),
                "catchup": attrs_local.get("catchup", ""),
            })
            pending, attrs_local = None, {}
    return channels

def request_prefix(url, timeout=TIMEOUT, headers=None):
    """GET 前 2KB；返回 (状态码, Content-Type, 字节前缀, 最终 URL)。"""
    h = {"User-Agent": UA, "Range": "bytes=0-2047"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get_content_type(), r.read(2048), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get_content_type() if e.headers else "", e.read(2048), url
    except Exception as e:
        return None, type(e).__name__, b"", url


def first_uris(base, text, limit=2):
    uris = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            uris.append(urllib.parse.urljoin(base, line))
            if len(uris) >= limit:
                break
    return uris


def valid_body(status, ctype, body):
    if status is None or status >= 400:
        return False
    if not body:
        return False
    head = body.lstrip().lower()
    if head.startswith(b"<html") or head.startswith(b"<!doctype html"):
        return False
    if ctype.startswith(("text/html", "application/json")):
        return False
    return True


def probe(url, timeout=TIMEOUT, header=None):
    """判定直播流是否真的能出片单/首片；HTTP 200 不再直接算活。"""
    if url.startswith("rtmp") or url.startswith("rtsp"):
        # 非 HTTP 协议当前环境无法判定；不能再默认为可用。
        return None, "protocol-not-http", -1
    headers = None
    if header:
        headers = {}
        for item in header.split("&"):
            if "=" in item:
                k, v = item.split("=", 1)
                if k and v:
                    headers[k] = v
    start = time.monotonic()
    try:
        status, ctype, body, final_url = request_prefix(url, timeout, headers)
        if status is None:
            return False, f"GET {ctype}", -1
        if status >= 400:
            return False, f"GET {status}", -1
        if body.lstrip().startswith(b"#EXTM3U"):
            text = body.decode("utf-8", "ignore")
            if "#EXT-X-STREAM-INF" in text:
                for variant in first_uris(final_url, text, 2):
                    v_status, v_ctype, v_body, v_url = request_prefix(variant, timeout, headers)
                    if not valid_body(v_status, v_ctype, v_body) or not v_body.lstrip().startswith(b"#EXTM3U"):
                        continue
                    for segment in first_uris(v_url, v_body.decode("utf-8", "ignore"), 2):
                        s_status, s_ctype, s_body, _ = request_prefix(segment, timeout, headers)
                        if valid_body(s_status, s_ctype, s_body):
                            return True, f"HLS {s_status} {s_ctype[:20]}", int((time.monotonic() - start) * 1000)
                return False, "HLS-no-playable-segment", -1
            for segment in first_uris(final_url, text, 2):
                s_status, s_ctype, s_body, _ = request_prefix(segment, timeout, headers)
                if valid_body(s_status, s_ctype, s_body):
                    return True, f"HLS {s_status} {s_ctype[:20]}", int((time.monotonic() - start) * 1000)
            return False, "HLS-no-playable-segment", -1
        if body[:3] == b"FLV" or ctype.startswith("video/"):
            return True, f"GET {status} {ctype[:20]}", int((time.monotonic() - start) * 1000)
        return False, f"not-stream {status} {ctype[:20]}", -1
    except Exception as e:
        return False, f"GET {type(e).__name__}", -1

def load_candidates(path):
    items = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            name, url = line.split("\t", 1)
            items.append((name.strip(), url.strip()))
        else:
            items.append(("", line))
    return items

def merge(channels):
    """同名频道合并多线路（最多 3 条），保留首次出现的元数据。"""
    m = {}
    for c in channels:
        if not c["name"] or not c["url"]:
            continue
        key = (c["group"], c["name"])
        if key not in m:
            m[key] = dict(c, urls=[{"url": c["url"], "header": c["header"]}])
        elif (len(m[key]["urls"]) < MAX_URLS_PER_CHANNEL
              and c["url"] not in [x["url"] for x in m[key]["urls"]]):
            m[key]["urls"].append({"url": c["url"], "header": c["header"]})
    return sorted(m.values(), key=lambda x: (x["group"], x["name"]))

def write_m3u(path, items):
    lines = ["#EXTM3U"]
    for c in items:
        attrs = [f'tvg-name="{c["name"]}"', f'group-title="{c["group"]}"']
        if c["logo"]: attrs.append(f'tvg-logo="{c["logo"]}"')
        if c["tvg_id"]: attrs.append(f'tvg-id="{c["tvg_id"]}"')
        if c["chno"]: attrs.append(f'tvg-chno="{c["chno"]}"')
        if c["catchup"]: attrs.append(f'catchup="{c["catchup"]}"')
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{c["name"]}')
        for item in c["urls"]:
            lines.append(item["url"] + (("|" + item["header"]) if item["header"] else ""))
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="live/sources.txt")
    ap.add_argument("--out", default="live/all.m3u")
    ap.add_argument("--report", default="live/report.json")
    ap.add_argument("--parse-only", action="store_true")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--timeout", type=int, default=TIMEOUT)
    args = ap.parse_args()

    cands = load_candidates(args.input)
    print(f"[1/4] 候选源 {len(cands)} 个")
    raw = []
    for name, url in cands:
        src = url.split("|")[0]
        try:
            if not src.lower().startswith(("http://", "https://")) and os.path.exists(src):
                text = open(src, encoding="utf-8", errors="ignore").read()
            else:
                text = fetch(src, args.timeout)
        except Exception as e:
            print(f"  ! 拉取失败 {name or url}: {type(e).__name__}")
            continue
        chans = parse_m3u(text)
        for c in chans:
            c["source"] = name or url
        raw.extend(chans)
        print(f"  + {name or url}: {len(chans)} 频道")

    print(f"[2/4] 解析出频道 {len(raw)} 条")
    merged = merge(raw)
    print(f"[3/4] 合并同名后 {len(merged)} 条")

    status = {}
    if not args.parse_only:
        jobs = [(c["name"], item["url"], item.get("header")) for c in merged for item in c["urls"]]
        print(f"  探测 {len(jobs)} 条线路…")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(probe, u, args.timeout, h): (n, u) for n, u, h in jobs}
            for f in as_completed(futs):
                n, u = futs[f]
                ok, msg, ms = f.result()
                status[u] = {"ok": ok, "msg": msg, "ms": ms}
        alive = []
        for c in merged:
            keep = [item for item in c["urls"] if status.get(item["url"], {}).get("ok") is True]
            if keep:
                keep.sort(key=lambda x: status.get(x["url"], {}).get("ms", 999999))
                c["urls"] = keep
                alive.append(c)
        dead = [u for u, s in status.items() if s["ok"] is not True]
        print(f"[4/4] 存活频道 {len(alive)} 条，失效线路 {len(dead)} 条")
        merged = alive

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_m3u(args.out, merged)
    json.dump({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channels": len(merged),
        "lines": sum(len(c["urls"]) for c in merged),
        "dead": [{"url": u, "reason": status[u]["msg"]} for u in status if not status[u]["ok"]],
        "fastest": min((s["ms"] for s in status.values() if s.get("ok") and s.get("ms", -1) >= 0), default=-1),
    }, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"写出 {args.out} 与 {args.report}")

if __name__ == "__main__":
    sys.exit(main())
