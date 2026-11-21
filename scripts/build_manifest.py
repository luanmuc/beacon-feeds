#!/usr/bin/env python3
"""生成 beacon-seed 的 manifest.json（源规模、更新时间、站点健康评分）。"""
import argparse, datetime, json, pathlib


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def health(site, dead=False):
    probe = site.get('probe') or {}
    state = probe.get('state') or ('dead' if dead else 'unknown')
    ms = probe.get('ms')
    score = 0 if state == 'dead' else (60 if state == 'skip' else 100)
    if score and isinstance(ms, (int, float)) and ms > 3000:
        score = max(50, score - 20)
    return {
        'key': site.get('key'),
        'name': site.get('name'),
        'state': state,
        'score': score,
        'ms': ms,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tvbox', default='tvbox.json')
    ap.add_argument('--report', default='live/report.json')
    ap.add_argument('--alive', default='config/sites.alive.json')
    ap.add_argument('--dead', default='config/sites.dead.json')
    ap.add_argument('--out', default='manifest.json')
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    tv = load(args.tvbox)
    report = load(args.report)
    alive = load(args.alive, [])
    dead = load(args.dead, [])
    sites = [s for s in tv.get('sites', []) if s.get('type') == 1 and not s.get('disabled')]
    merged = {}
    for item in (alive if isinstance(alive, list) else []):
        if item.get('key'):
            merged[item['key']] = health(item)
    for item in (dead if isinstance(dead, list) else []):
        if item.get('key'):
            merged[item['key']] = health(item, dead=True)
    rows = [merged.get(s.get('key')) for s in sites if s.get('key') in merged]
    lat = [r['ms'] for r in rows if r and isinstance(r.get('ms'), (int, float)) and r['state'] == 'ok']
    manifest = {
        'version': now.strftime('%Y.%m.%d'),
        'updated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'vod_sites': len(sites),
        'vod_ok': sum(1 for r in rows if r and r['state'] == 'ok'),
        'vod_skip': sum(1 for r in rows if r and r['state'] == 'skip'),
        'vod_dead': sum(1 for r in rows if r and r['state'] == 'dead'),
        'vod_avg_ms': int(sum(lat) / len(lat)) if lat else None,
        'vod_health': rows,
        'live_channels': report.get('channels', 0),
        'live_lines': report.get('lines', 0),
        'fastest': report.get('fastest'),
    }
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'vod_health'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
