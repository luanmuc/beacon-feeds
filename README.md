# 自用电视源订阅（tvbox.json）

一个固定 raw 链接喂给 FongMi/TV：`sites` 是影视接口、`lives` 是电视台 m3u；App 端自动拆成点播/直播两条配置，共用同一 URL。

## 目录

```
tvbox.json                  # ★ 唯一订阅入口，由 build_config.py 生成，不要手改
manifest.json               # 源规模/站点健康/直播统计（自动生成）
live-report.json            # App 设置页读取的直播存活统计（自动生成）
config/
  base.json                 # 订阅元信息（name/spider/lives/parses/flags），手改
  sites.json                # 影视接口候选（手改/追加）；disabled=true 的不会进产物
  sites.alive.json          # 探测后存活（自动生成）
  sites.dead.json           # 探测后失效（自动生成，人工复核用）
live.m3u                    # 合并后的直播清单（根文件，App 固定读取）
live/
  sources.txt               # 候选 m3u 清单（手改）
  all.m3u                   # 探测+合并后的产物（自动生成）
  report.json               # 本次探测统计与失效线路（自动生成）
scripts/
  probe_live.py             # 拉 m3u -> 解析 -> 逐路探测 -> 同名合并
  probe_vod.py              # 影视接口探测（type=3 爬虫无法离线探测，跳过）
  build_config.py           # 合并生成 tvbox.json + 必填校验
.github/workflows/
  probe-live.yml            # 每 6 小时
  probe-vod.yml             # 每天 03:00 CST
```

## 本地跑一遍

```bash
python3 scripts/probe_live.py --parse-only          # 只解析，不探测（改 sources.txt 后先这样验格式）
python3 scripts/probe_live.py                        # 完整探测
python3 scripts/probe_vod.py
RAW_BASE=https://raw.githubusercontent.com/<owner>/<repo>/stable python3 scripts/build_config.py
```

## 在 App 里用

把 `tvbox.json` 的 **stable raw 链接**填进 FongMi 的**点播配置**即可；因为文件里有 `lives`，App 会自动生成直播配置并共用该链接（已在源码中核实 `VodConfig.initLive()`）。

工作流每次探测成功后会提交生成物并强制移动 `stable` 标签，App 固定读取：

```text
https://raw.githubusercontent.com/luanmuc/beacon-feeds/stable/tvbox.json
https://raw.githubusercontent.com/luanmuc/beacon-feeds/stable/live.m3u
https://raw.githubusercontent.com/luanmuc/beacon-feeds/stable/manifest.json
https://raw.githubusercontent.com/luanmuc/beacon-feeds/stable/live-report.json
```

## 设计规则

1. **探测失败不删源**：只把失效线路记进 `report.json`、失效站点移进 `sites.dead.json`，避免一次网络抖动清空清单。
2. **同名频道自动合并多线路**（最多 3 条）：配合 App 的"失败自动换线"（`LiveSetting.isChange`）。
3. **只提交变化**：workflow 里 `git diff --cached --quiet` 判断，无变化不产生提交。
4. **产物必过校验**：`build_config.py` 校验 sites 的 `key/name/api` 与 lives 的 `name`，失败直接让 CI 变红。
5. **影视存活不是“能解析 JSON”**：首页/第一个分类必须能出非空 list；只有 `class` 分类壳的站点判失效。
6. **直播存活不是“HEAD 200”**：必须能取到 M3U8 片单/首片或 FLV 头；401/403/404/HTML 和 RTMP 未探测都不算存活。

## 私密性

- 本仓库建议 **private**；但 private 仓库的 raw 链接匿名访问会 404，App 拉不到。
- 若需要匿名可读：把仓库设为 public 并使用**随机仓库名**，或在 CI 里把 `tvbox.json` 推到对象存储。
- 不要在这个仓库放任何 token、付费接口密钥、私有镜像地址。
