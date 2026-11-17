#!/usr/bin/env python3
"""从 live/report.json、vod/report.json 生成 docs/index.html 健康看板。"""
import json, html, pathlib, datetime


def rows(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                out.append((k, v.get("ok", v.get("status", "")), v.get("latency", v.get("ms", "")))
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict):
                out.append((v.get("name", v.get("url", "")), v.get("ok", v.get("status", "")), v.get("latency", v.get("ms", "")))


def main():
    rep = {}
    for f in ("live/report.json", "vod/report.json"):
        p = pathlib.Path(f)
        if p.exists():
            try:
                rep[f] = json.loads(p.read_text())
            except Exception:
                rep[f] = {}
    body = []
    for f, obj in rep.items():
        body.append(f"<h2>{html.escape(f)}</h2><table><tr><th>源</th><th>状态</th><th>延迟</th></tr>")
        for n, ok, lat in rows(obj)[:200]:
            body.append(f"<tr><td>{html.escape(str(n))}</td><td>{html.escape(str(ok))}</td><td>{html.escape(str(lat))}</td></tr>")
        body.append("</table>")
    page = ("<!doctype html><html><head><meta charset='utf-8'><title>源健康</title>"
            "<style>body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #ddd;padding:6px;font-size:13px}th{background:#f6f6f6}</style></head>"
            f"<body><h1>源健康报告</h1><p>生成时间：{datetime.datetime.utcnow():%Y-%m-%d %H:%M UTC}</p>{''.join(body)}</body></html>")
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
