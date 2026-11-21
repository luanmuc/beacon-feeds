// beacon-live.js：电视直播聚合 QuickJS 源。
// 读取源仓 CI 生成的 live/channels.json，输出 FongMi 可解析的 M3U。
// 同名频道保留多线路，播放失败由 App 播放层切换，源负责线路顺序与健康。

import { Spider } from "catvod";

const DEFAULT_CHANNELS_URL = "https://raw.githubusercontent.com/luanmuc/beacon-feeds/release/live/channels.json";
const DEFAULT_M3U_URL = "https://raw.githubusercontent.com/luanmuc/beacon-feeds/release/live/all.m3u";
const DEFAULT_REPORT_URL = "https://raw.githubusercontent.com/luanmuc/beacon-feeds/release/live-report.json";
const CACHE_MS = 5 * 60 * 1000;
const REQUEST_TIMEOUT = 15000;
const MAX_URLS = 3;

function parseExt(value) {
    if (value && typeof value === "object") return value;
    if (typeof value !== "string" || !value.trim()) return {};
    try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) {
        return {};
    }
}

function text(value, fallback = "") {
    if (value === undefined || value === null) return fallback;
    return String(value);
}

function num(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

function normalizeUrl(value) {
    if (!value) return null;
    if (typeof value === "string") return value ? { url: value, header: "" } : null;
    if (typeof value === "object" && value.url) {
        return { url: text(value.url), header: text(value.header) };
    }
    return null;
}

function parseM3U(raw) {
    const channels = [];
    let current = null;
    for (const line of text(raw).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n")) {
        const value = line.trim();
        if (!value) continue;
        if (value.startsWith("#EXTINF")) {
            const attrs = {};
            const attrRe = /([a-zA-Z0-9-]+)="([^"]*)"/g;
            let match;
            while ((match = attrRe.exec(value)) !== null) attrs[match[1].toLowerCase()] = match[2];
            const comma = value.lastIndexOf(",");
            current = {
                name: comma >= 0 ? value.slice(comma + 1).trim() : "",
                group: attrs["group-title"] || "未分组",
                logo: attrs["tvg-logo"] || "",
                tvg_id: attrs["tvg-id"] || "",
                chno: attrs["tvg-chno"] || "",
                catchup: attrs["catchup"] || "",
                urls: [],
            };
            channels.push(current);
        } else if (!value.startsWith("#") && current) {
            const parts = value.split("|", 2);
            const item = normalizeUrl(parts[0]);
            if (item) {
                item.header = parts.length > 1 ? parts[1] : "";
                current.urls.push(item);
            }
        }
    }
    return channels;
}

function mergeChannels(items) {
    const map = {};
    for (const item of items) {
        const name = text(item.name).trim();
        if (!name) continue;
        const key = `${text(item.group, "未分组")}\u0001${name}`;
        if (!map[key]) {
            map[key] = {
                name,
                group: text(item.group, "未分组"),
                logo: text(item.logo),
                tvg_id: text(item.tvg_id || item.tvgId),
                chno: text(item.chno || item.tvg_chno),
                catchup: text(item.catchup),
                urls: [],
            };
        }
        for (const url of item.urls || []) {
            const itemUrl = normalizeUrl(url);
            if (!itemUrl || !/^https?:\/\//i.test(itemUrl.url)) continue;
            if (map[key].urls.length >= MAX_URLS) break;
            if (!map[key].urls.some((x) => x.url === itemUrl.url)) map[key].urls.push(itemUrl);
        }
    }
    return Object.values(map).filter((item) => item.urls.length);
}

export default class BeaconLive extends Spider {
    init(extend = "") {
        this.ext = parseExt(extend);
        this.channelsUrl = text(this.ext.channels_url || this.ext.channelsUrl || DEFAULT_CHANNELS_URL);
        this.m3uUrl = text(this.ext.m3u_url || this.ext.m3uUrl || DEFAULT_M3U_URL);
        this.reportUrl = text(this.ext.report_url || this.ext.reportUrl || DEFAULT_REPORT_URL);
        this.channels = [];
        this.loadedAt = 0;
        this.health = {};
        this.disabled = {};
        this.probeLimit = num(this.ext.probe_limit, 24);
    }

    async loadChannels(force = false) {
        if (!force && this.channels.length && Date.now() - this.loadedAt < CACHE_MS) return this.channels;
        try {
            const data = await this.net.json(this.channelsUrl, { timeout: REQUEST_TIMEOUT });
            const rows = Array.isArray(data) ? data : (data && Array.isArray(data.channels) ? data.channels : []);
            this.channels = mergeChannels(rows.map((item) => ({
                name: item.name,
                group: item.group,
                logo: item.logo,
                tvg_id: item.tvg_id || item.tvgId,
                chno: item.chno || item.tvg_chno,
                catchup: item.catchup,
                urls: item.urls || [],
            })));
            this.loadedAt = Date.now();
        } catch (e) {
            const res = await this.net.req(this.m3uUrl, { timeout: REQUEST_TIMEOUT });
            if (res && !res.error && res.code < 400 && res.content) {
                this.channels = mergeChannels(parseM3U(res.content));
                this.loadedAt = Date.now();
            } else if (!this.channels.length) {
                throw e;
            }
        }
        return this.channels;
    }

    activeChannels() {
        return this.channels.filter((item) => !this.disabled[item.name]);
    }

    buildM3U(items) {
        const lines = ["#EXTM3U"];
        for (const item of items) {
            let meta = `#EXTINF:-1 tvg-name="${item.name}" group-title="${item.group}"`;
            if (item.logo) meta += ` tvg-logo="${item.logo}"`;
            if (item.tvg_id) meta += ` tvg-id="${item.tvg_id}"`;
            if (item.chno) meta += ` tvg-chno="${item.chno}"`;
            if (item.catchup) meta += ` catchup="${item.catchup}"`;
            lines.push(`${meta},${item.name}`);
            for (const url of item.urls) {
                lines.push(url.url + (url.header ? `|${url.header}` : ""));
            }
        }
        return lines.join("\n") + "\n";
    }

    async liveContent(url) {
        if (url && /^https?:\/\//i.test(text(url)) && text(url).split("?")[0].toLowerCase().match(/\.(m3u|m3u8)$/)) {
            const res = await this.net.req(text(url), { timeout: REQUEST_TIMEOUT });
            if (res && !res.error && res.code < 400 && res.content) return res.content;
        }
        await this.loadChannels();
        return this.buildM3U(this.activeChannels());
    }

    mark(item, ok, ms, why = "") {
        this.health[item.name] = {
            name: item.name,
            state: ok ? "ok" : "dead",
            ms: num(ms, -1),
            why,
            at: new Date().toISOString(),
        };
    }

    async probeOne(item) {
        const start = Date.now();
        const url = item.urls[0];
        if (!url) {
            this.mark(item, false, -1, "no-url");
            return false;
        }
        try {
            const res = await this.net.req(url.url, {
                timeout: 8000,
                headers: { Range: "bytes=0-2047", ...(url.header ? parseHeader(url.header) : {}) },
            });
            const body = res && typeof res.content === "string" ? res.content : "";
            const contentType = res ? text(res.contentType) : "";
            const good = !!res && !res.error && res.code < 400 && (
                body.includes("#EXTM3U") ||
                contentType.startsWith("video/") ||
                contentType.includes("mpegurl") ||
                /^FLV/.test(body)
            );
            this.mark(item, good, Date.now() - start, good ? `http-ok ${contentType}` : `code=${res && res.code}`);
            return good;
        } catch (e) {
            this.mark(item, false, Date.now() - start, text(e && e.message, "probe failed"));
            return false;
        }
    }

    async probeAll() {
        await this.loadChannels();
        const items = this.activeChannels().slice(0, this.probeLimit);
        await Promise.all(items.map((item) => this.probeOne(item)));
        return this.healthPayload();
    }

    async reportHealth() {
        try {
            const report = await this.net.json(this.reportUrl, { timeout: REQUEST_TIMEOUT });
            return {
                source: "beacon-live",
                generated_at: text(report.generated_at, new Date().toISOString()),
                summary: {
                    channels: num(report.channels, this.channels.length),
                    lines: num(report.lines, 0),
                    dead: Array.isArray(report.dead) ? report.dead.length : 0,
                },
                report: true,
            };
        } catch (e) {
            return this.healthPayload();
        }
    }

    healthPayload() {
        const rows = this.channels.map((item) => {
            const h = this.health[item.name] || {};
            return {
                name: item.name,
                group: item.group,
                state: this.disabled[item.name] ? "disabled" : (h.state || "unknown"),
                lines: item.urls.length,
                ms: h.ms ?? -1,
                why: h.why || "",
                at: h.at || "",
            };
        });
        return {
            source: "beacon-live",
            generated_at: new Date().toISOString(),
            summary: {
                channels: rows.length,
                ok: rows.filter((r) => r.state === "ok").length,
                dead: rows.filter((r) => r.state === "dead").length,
                disabled: rows.filter((r) => r.state === "disabled").length,
                lines: rows.reduce((sum, r) => sum + r.lines, 0),
            },
            channels: rows,
        };
    }

    async action(action) {
        const raw = text(action, "health");
        const command = raw.split(":")[0];
        const key = raw.includes(":") ? raw.slice(raw.indexOf(":") + 1) : "";
        await this.loadChannels();
        if (command === "health") return await this.reportHealth();
        if (command === "probe") {
            if (key) {
                const item = this.channels.find((x) => x.name === key);
                if (item) await this.probeOne(item);
                return this.healthPayload();
            }
            return await this.probeAll();
        }
        if (command === "toggle" && key) {
            this.disabled[key] = !this.disabled[key];
            return this.healthPayload();
        }
        return { source: "beacon-live", msg: `unknown action: ${raw}` };
    }
}

function parseHeader(value) {
    const headers = {};
    for (const item of text(value).split("&")) {
        if (!item.includes("=")) continue;
        const [key, ...rest] = item.split("=");
        if (key) headers[key] = rest.join("=");
    }
    return headers;
}
