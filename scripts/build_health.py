#!/usr/bin/env python3
"""从 live/report.json、vod/report.json 生成 docs/index.html 源健康看板。"""
import json
import html
import pathlib
import datetime


def rows(obj):
    out = []
    items = obj.items() if isinstance(obj, dict) else enumerate(obj or [])
    for key, value in items:
        if isinstance(value, dict):
            name = value.get("name", value.get("url", key))
            status = value.get("ok", value.get("status", ""))
            latency = value.get("latency", value.get("ms", ""))
            out.append((name, status, latency))
    return out


def main():
    rep = {}
    for path in ("live/report.json", "vod/report.json"):
        p = pathlib.Path(path)
        if p.exists():
            try:
                rep[path] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                rep[path] = {}
    parts = []
    for name, obj in rep.items():
        parts.append("<h2>%s</h2><table><tr><th>源</th><th>状态</th><th>延迟</th></tr>" % html.escape(name))
        for row_name, status, latency in rows(obj)[:200]:
            parts.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (html.escape(str(row_name)), html.escape(str(status)), html.escape(str(latency)))
            )
        parts.append("</table>")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = (
        "<!doctype html><html><head><meta charset='utf-8'><title>源健康</title>"
        "<style>body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ddd;padding:6px;font-size:13px}th{background:#f6f6f6}</style></head>"
        "<body><h1>源健康报告</h1><p>生成时间：" + stamp + "</p>" + "".join(parts) + "</body></html>"
    )
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
