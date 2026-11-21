# 项目二：源仓库（固定订阅链接 + CI 自动维护）

## 目录结构（建议）

```
tv-sources/
├── tvbox.json                 # ★ 唯一订阅入口：sites + lives 同文件
├── live/
│   ├── cctv.m3u               # 按来源分片，合并后进 tvbox.json 的 lives[].url
│   ├──卫视.m3u
│   └── epg.xml.gz             # 节目表（可选，按需生成）
├── sites/
│   └── spider.json            # 影视接口清单（CI 探测后可用的写这里）
├── scripts/
│   ├── probe_live.py          # 拉流探测：m3u8 取前几片/RTMP 握手
│   └── probe_vod.py           # 影视接口探测：按 Site.api 打一次首页/搜索
└── .github/workflows/
    ├── probe-live.yml         # 每 6h：探测 → 更新 live/*.m3u + tvbox.json
    └── probe-vod.yml          # 每天：探测 → 更新 sites/spider.json + tvbox.json
```

## tvbox.json 骨架（字段已从代码核实）

```json
{
  "name": "订阅",
  "spider": "https://raw.githubusercontent.com/<你>/tv-spider/main/spider.jar",
  "sites": [
    {"key":"demo","name":"示例站","type":3,"api":"csp_Xxx","searchable":1,"quickSearch":1,"filterable":1}
  ],
  "lives": [
    {"name":"电视台","type":0,"url":"https://raw.githubusercontent.com/<你>/tv-sources/main/live/all.m3u","epg":"...","ua":"..."}
  ],
  "parses": [],
  "flags": []
}
```

## CI 设计要点

- **只提交变化**：探测结果与上次比对，diff 为空就不 commit（避免刷历史）。
- **失败即保留**：某路探测失败不删源，只标记（`#DEAD` 注释或移入 `live/dead.m3u`），避免"一次网络抖动把台删光"。
- **内容级判定**：影视要求分类页出非空 list；直播要求拿到 M3U8 片单/首片或 FLV 头，HTTP 200/HEAD 200 本身不够。
- **未探协议不冒充存活**：RTMP/RTSP 当前不探测，不能默认算 ok。
- **多线路合并**：同一频道探测到多条可用 URL → `频道名,url1#url2`（FongMi 自动换线）。
- **产物可校验**：`tvbox.json` 生成后跑一次 `jsonlint` + 必填字段校验（`name`/`url` 缺失即失败）。
- **定时**：直播 6h 一次（流地址掉得快）；影视 24h 一次（接口稳定些）。
- **Secrets**：探测用的代理/UA 放 repo secrets，不写进文件。

## 关键约束
- 这个仓库的产物**必须是一个永不变化的 raw 链接**，App 端只认它。
- 探测脚本用 Python 标准库为主（`urllib` + `http.client`），少装依赖，Actions 跑得快。
