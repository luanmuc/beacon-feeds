#!/usr/bin/env python3
"""生成 beacon-seed 的 manifest.json（源规模与更新时间）。"""
import argparse, datetime, json, pathlib


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tvbox', default='tvbox.json')
    ap.add_argument('--report', default='live/report.json')
    ap.add_argument('--out', default='manifest.json')
    args = ap.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc)
    tv = load(args.tvbox)
    report = load(args.report)
    sites = [s for s in tv.get('sites', []) if s.get('type') == 1 and not s.get('disabled')]
    manifest = {
        'version': now.strftime('%Y.%m.%d'),
        'updated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'vod_sites': len(sites),
        'live_channels': report.get('channels', 0),
        'live_lines': report.get('lines', 0),
        'fastest': report.get('fastest'),
    }
    pathlib.Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
