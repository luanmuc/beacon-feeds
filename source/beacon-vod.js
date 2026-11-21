// beacon-vod.js：影视聚合 QuickJS 源。
// 只调用 TVBox type=1 JSON 接口；站点清单由源仓 CI 探测后写入 vod-sites.json。
// 运行在 App 内，不依赖常驻服务器。

import { Spider } from "catvod";

const DEFAULT_SITES_URL = "https://raw.githubusercontent.com/luanmuc/beacon-feeds/release/vod-sites.json";
const CACHE_MS = 5 * 60 * 1000;
const REQUEST_TIMEOUT = 15000;

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

function withQuery(base, params) {
    const url = new URL(base);
    for (const [key, value] of Object.entries(params || {})) {
        if (value === undefined || value === null || value === "") continue;
        url.searchParams.set(key, String(value));
    }
    return url.toString();
}

function text(value, fallback = "") {
    if (value === undefined || value === null) return fallback;
    return String(value);
}

function num(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

function splitSiteId(value) {
    const raw = text(value);
    const at = raw.indexOf("::");
    if (at < 0) return { site: "", id: raw };
    return { site: raw.slice(0, at), id: raw.slice(at + 2) };
}

export default class BeaconVod extends Spider {
    init(extend = "") {
        this.ext = parseExt(extend);
        this.sitesUrl = text(this.ext.sites_url || this.ext.sitesUrl || DEFAULT_SITES_URL);
        this.sites = [];
        this.loadedAt = 0;
        this.health = {};
        this.disabled = {};
    }

    async ensureSites(force = false) {
        if (!force && this.sites.length && Date.now() - this.loadedAt < CACHE_MS) return this.sites;
        try {
            const data = await this.net.json(this.sitesUrl, { timeout: REQUEST_TIMEOUT });
            const rows = Array.isArray(data) ? data : (data && Array.isArray(data.sites) ? data.sites : []);
            this.sites = rows
                .filter((s) => s && s.key && s.name && /^https?:\/\//i.test(text(s.api)))
                .map((s) => ({
                    key: text(s.key),
                    name: text(s.name),
                    api: text(s.api),
                    searchable: num(s.searchable, 1),
                    quickSearch: num(s.quickSearch, 1),
                    header: s.header && typeof s.header === "object" ? s.header : {},
                }));
            this.loadedAt = Date.now();
        } catch (e) {
            if (!this.sites.length) throw e;
        }
        return this.sites;
    }

    siteByKey(key) {
        return this.sites.find((s) => s.key === key);
    }

    activeSites() {
        return this.sites.filter((s) => !this.disabled[s.key]);
    }

    mark(key, ok, ms, why = "") {
        this.health[key] = {
            key,
            state: ok ? "ok" : "dead",
            ms: num(ms, -1),
            why,
            at: new Date().toISOString(),
        };
    }

    async requestJson(site, params) {
        const url = withQuery(site.api, params);
        return await this.net.json(url, {
            timeout: REQUEST_TIMEOUT,
            headers: site.header || {},
        });
    }

    normalize(item, site) {
        const rawId = text(item.vod_id ?? item.id ?? item.vodId);
        if (!rawId) return null;
        const row = {
            vod_id: `${site.key}::${rawId}`,
            vod_name: text(item.vod_name ?? item.name),
            vod_pic: text(item.vod_pic ?? item.pic),
            vod_remarks: text(item.vod_remarks ?? item.remarks ?? item.note),
            type_name: text(item.type_name ?? item.typeName),
            vod_year: text(item.vod_year ?? item.year),
            vod_area: text(item.vod_area ?? item.area),
            vod_lang: text(item.vod_lang ?? item.lang),
            vod_actor: text(item.vod_actor ?? item.actor),
            vod_director: text(item.vod_director ?? item.director),
            vod_content: text(item.vod_content ?? item.content ?? item.desc),
            vod_play_from: text(item.vod_play_from ?? item.play_from),
            vod_play_url: text(item.vod_play_url ?? item.play_url),
        };
        if (!row.vod_play_from && row.vod_play_url) row.vod_play_from = site.name;
        return row;
    }

    async homeOne(site) {
        const start = Date.now();
        try {
            const data = await this.requestJson(site, { ac: "list" });
            const classes = data.class || data.categories || [];
            const list = Array.isArray(data.list) ? data.list : [];
            this.mark(site.key, true, Date.now() - start, "home");
            return {
                classes: classes.map((c) => ({
                    type_id: `${site.key}::${text(c.type_id ?? c.typeId ?? c.id)}`,
                    type_name: `${site.name}｜${text(c.type_name ?? c.typeName ?? c.name)}`,
                })),
                list: list.map((v) => this.normalize(v, site)).filter(Boolean),
            };
        } catch (e) {
            this.mark(site.key, false, Date.now() - start, text(e && e.message, "home failed"));
            return { classes: [], list: [] };
        }
    }

    async homeContent(filter) {
        await this.ensureSites();
        const results = await Promise.all(this.activeSites().map((s) => this.homeOne(s)));
        const classes = [];
        const seen = {};
        for (const r of results) {
            for (const c of r.classes) {
                if (!seen[c.type_id]) {
                    seen[c.type_id] = true;
                    classes.push(c);
                }
            }
        }
        const list = results.flatMap((r) => r.list);
        return { class: classes, list };
    }

    homeVideoContent() {
        return { list: [] };
    }

    async categoryContent(tid, pg, filter, extend) {
        await this.ensureSites();
        const parsed = splitSiteId(tid);
        const site = this.siteByKey(parsed.site);
        if (!site || this.disabled[site.key]) return { list: [] };
        if (parsed.id === "_all" || !parsed.id) {
            return { list: (await this.homeOne(site)).list };
        }
        try {
            const params = { ac: "detail", t: parsed.id, pg: text(pg, "1") };
            if (extend && typeof extend === "object" && Object.keys(extend).length) {
                params.f = JSON.stringify(extend);
            }
            const data = await this.requestJson(site, params);
            const rows = Array.isArray(data.list) ? data.list : [];
            return { list: rows.map((v) => this.normalize(v, site)).filter(Boolean) };
        } catch (e) {
            this.mark(site.key, false, -1, text(e && e.message, "category failed"));
            return { list: [] };
        }
    }

    async searchOne(site, keyword, page) {
        if (!site.searchable && !site.quickSearch) return [];
        try {
            const data = await this.requestJson(site, { ac: "detail", wd: keyword, pg: page });
            const rows = Array.isArray(data.list) ? data.list : [];
            return rows.map((v) => this.normalize(v, site)).filter(Boolean);
        } catch (e) {
            this.mark(site.key, false, -1, text(e && e.message, "search failed"));
            return [];
        }
    }

    async searchContent(keyword, quick, pg = "1") {
        await this.ensureSites();
        const page = text(pg, "1");
        const lists = await Promise.all(this.activeSites().map((s) => this.searchOne(s, keyword, page)));
        return { list: lists.flat() };
    }

    async detailContent(ids) {
        await this.ensureSites();
        const values = Array.isArray(ids) ? ids : [ids];
        const out = [];
        for (const value of values) {
            const parsed = splitSiteId(value);
            const site = this.siteByKey(parsed.site);
            if (!site || this.disabled[site.key] || !parsed.id) continue;
            try {
                const data = await this.requestJson(site, { ac: "detail", ids: parsed.id });
                const rows = Array.isArray(data.list) ? data.list : [];
                for (const row of rows) {
                    const item = this.normalize(row, site);
                    if (item) out.push(item);
                }
            } catch (e) {
                this.mark(site.key, false, -1, text(e && e.message, "detail failed"));
            }
        }
        return { list: out };
    }

    playerContent(flag, id, vipFlags) {
        const raw = text(id);
        if (/^https?:\/\//i.test(raw) || raw.startsWith("magnet:") || raw.startsWith("rtmp")) {
            // 上游返回的网页播放页交给 WebView 嗅探；直链媒体直接播。
            const media = /\.(m3u8|mpd|mp4|mkv|flv|mp3|m4a|aac)(\?|#|$)/i.test(raw);
            return { parse: media ? 0 : 1, jx: 0, url: raw, flag: text(flag) };
        }
        if (raw.startsWith("beacon://")) {
            try {
                const value = decodeURIComponent(raw.slice("beacon://".length));
                if (/^https?:\/\//i.test(value)) return { parse: 0, jx: 0, url: value, flag: text(flag) };
            } catch (e) {
            }
        }
        return { parse: 0, jx: 0, url: raw, flag: text(flag) };
    }

    async probeOne(site) {
        const start = Date.now();
        try {
            const data = await this.requestJson(site, { ac: "list" });
            const classes = data.class || data.categories || [];
            const list = Array.isArray(data.list) ? data.list : [];
            if (classes.length || list.length) {
                this.mark(site.key, true, Date.now() - start, `class=${classes.length} list=${list.length}`);
                return true;
            }
            this.mark(site.key, false, Date.now() - start, "empty class/list");
            return false;
        } catch (e) {
            this.mark(site.key, false, Date.now() - start, text(e && e.message, "probe failed"));
            return false;
        }
    }

    async probeAll() {
        await this.ensureSites();
        await Promise.all(this.sites.map((s) => this.probeOne(s)));
        return this.healthPayload();
    }

    healthPayload() {
        const rows = this.sites.map((site) => {
            const h = this.health[site.key] || {};
            return {
                key: site.key,
                name: site.name,
                state: this.disabled[site.key] ? "disabled" : (h.state || "unknown"),
                ms: h.ms ?? -1,
                why: h.why || "",
                at: h.at || "",
            };
        });
        return {
            source: "beacon-vod",
            generated_at: new Date().toISOString(),
            summary: {
                total: rows.length,
                ok: rows.filter((r) => r.state === "ok").length,
                dead: rows.filter((r) => r.state === "dead").length,
                disabled: rows.filter((r) => r.state === "disabled").length,
            },
            sites: rows,
        };
    }

    async action(action) {
        const raw = text(action, "health");
        const command = raw.split(":")[0];
        const key = raw.includes(":") ? raw.slice(raw.indexOf(":") + 1) : "";
        if (command === "health") {
            await this.ensureSites();
            return this.healthPayload();
        }
        if (command === "probe") {
            if (key) {
                await this.ensureSites();
                const site = this.siteByKey(key);
                if (site) await this.probeOne(site);
                return this.healthPayload();
            }
            return await this.probeAll();
        }
        if (command === "toggle" && key) {
            this.disabled[key] = !this.disabled[key];
            return this.healthPayload();
        }
        return { source: "beacon-vod", msg: `unknown action: ${raw}` };
    }
}
