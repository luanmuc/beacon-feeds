#!/usr/bin/env python3
"""直播源探测：拉取候选 m3u -> 解析频道 -> 逐路探测可用性 -> 合并同名频道 -> 输出 all.m3u。

用法：
    python3 scripts/probe_live.py --input live/sources.txt --out live/all.m3u --report live/report.json
    python3 scripts/probe_live.py --parse-only            # 只解析不探测（离线调试）
候选文件 sources.txt 每行：
    <名字>\t<m3u地址>   或直接写 <m3u地址>；# 开头为注释。
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error
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

def probe(url, timeout=TIMEOUT):
    """判定一条直播流是否可拉：HEAD 优先，失败退化为 Range GET，读取首包。"""
    if url.startswith("rtmp") or url.startswith("rtsp"):
        # 非 HTTP 协议无法用 urllib 判定，交给 App 端；这里视为"未知可用"
        return True, "protocol-not-http"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
            ctype = r.headers.get("Content-Type", "")
            if code < 400:
                return True, f"HEAD {code} {ctype[:24]}"
    except urllib.error.HTTPError as e:
        if e.code == 405:  # 不允许 HEAD，退化为 GET
            pass
        else:
            return False, f"HEAD {e.code}"
    except Exception as e:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1024"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(1024)
            return True, f"GET {r.status}"
    except Exception as e:
        return False, f"GET {type(e).__name__}"

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
        jobs = [(c["name"], item["url"]) for c in merged for item in c["urls"]]
        print(f"  探测 {len(jobs)} 条线路…")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(probe, u, args.timeout): (n, u) for n, u in jobs}
            for f in as_completed(futs):
                n, u = futs[f]
                ok, msg = f.result()
                status[u] = {"ok": ok, "msg": msg}
        alive = []
        for c in merged:
            keep = [item for item in c["urls"] if status.get(item["url"], {}).get("ok")]
            if keep:
                c["urls"] = keep
                alive.append(c)
        dead = [u for u, s in status.items() if not s["ok"]]
        print(f"[4/4] 存活频道 {len(alive)} 条，失效线路 {len(dead)} 条")
        merged = alive

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_m3u(args.out, merged)
    json.dump({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channels": len(merged),
        "lines": sum(len(c["urls"]) for c in merged),
        "dead": [{"url": u, "reason": status[u]["msg"]} for u in status if not status[u]["ok"]],
    }, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"写出 {args.out} 与 {args.report}")

if __name__ == "__main__":
    sys.exit(main())
