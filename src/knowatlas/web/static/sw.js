/* 知道 KnowAtlas —— PWA 壳 Service Worker（2026-10-29 批 98）
 *
 * 职责边界（写死在开头，改前先看工单 docs/design/变更工单-2026-10-29-响应式与PWA壳.md）：
 *   1) 应用外壳（4 张 HTML + CSS/JS/图标）离线可打开；
 *   2) 只读 GET /api/** 走「网络优先 + 缓存回落」，**只缓存 JSON**，上限 120 条；
 *   3) 原文代理 /api/entries/<id>/file 一律不进缓存（可能是几十 MB 的 PDF）；
 *   4) 非 GET（所有写操作）**完全不拦截**——离线写必须失败得明明白白，不做静默排队。
 *
 * 安全上下文限制：http://<内网 IP> 下浏览器不注册 SW，此时页面仍可「添加到主屏幕」，
 * 但没有离线缓存。真要手机离线，先做局域网 TLS（TODO P2 反向代理）。
 */

const VERSION = "ka-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const API_CACHE = `${VERSION}-api`;
const API_MAX_ENTRIES = 120;

const SHELL_FILES = [
  "/index.html",
  "/graph.html",
  "/thread.html",
  "/tokens.css",
  "/components.css",
  "/ui.css",
  "/ui.js",
  "/vendor/echarts.min.js",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/apple-touch-icon.png",
];
const SHELL_HTML = new Set(["/", "/index.html", "/graph.html", "/thread.html"]);

// ---------- 安装：预缓存外壳（逐个 add，任一失败不拖垮整批）----------
self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await Promise.all(SHELL_FILES.map(async (url) => {
      try {
        const res = await fetch(new Request(url, { cache: "reload" }));
        if (res.ok) await cache.put(url, res);
      } catch (_) { /* 离线安装/单文件失败：留待首次访问时补 */ }
    }));
    await self.skipWaiting();
  })());
});

// ---------- 激活：清掉旧版本缓存，接管已打开页面 ----------
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

// ---------- 手动注销（回滚通道：页面 postMessage({type:"UNREGISTER"}) 或 DevTools 执行）----------
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "UNREGISTER") {
    event.waitUntil((async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith("ka-")).map((k) => caches.delete(k)));
      await self.registration.unregister();
    })());
  }
});

// ---------- 缓存裁剪：按写入顺序淘汰最旧（Cache.keys 的顺序即插入顺序）----------
async function trimApiCache(cache) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - API_MAX_ENTRIES; i += 1) await cache.delete(keys[i]);
}

const OFFLINE_JSON = () => new Response(
  JSON.stringify({ offline: true, error: { code: "OFFLINE", message: "离线只读：这条内容还没缓存过" } }),
  { status: 503, headers: { "Content-Type": "application/json; charset=utf-8", "X-KnowAtlas-Offline": "1" } },
);

const OFFLINE_HTML = `<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>离线 · 知道 KnowAtlas</title>
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#12151C;color:#E6E9EF;font-family:system-ui,'Microsoft YaHei',sans-serif">
<div style="text-align:center;padding:24px">
  <div style="font-size:15px;margin-bottom:8px">离线，且这一页还没缓存过</div>
  <div style="font-size:12px;color:#8A93A6;margin-bottom:16px">
    已缓存的页面（工作台 / 关系图 / 线索库）可以读；写操作与未缓存内容需要联网。</div>
  <a href="/index.html" style="color:#5B8DEF;font-size:13px">回工作台</a>
</div></body></html>`;

// ---------- 策略一：只读 API（网络优先 + 缓存回落）----------
async function apiNetworkFirst(request) {
  const cache = await caches.open(API_CACHE);
  try {
    const res = await fetch(request);
    const isJson = (res.headers.get("content-type") || "").includes("json");
    if (res.ok && isJson) {
      await cache.put(request, res.clone());
      await trimApiCache(cache);
    }
    return res;
  } catch (_) {
    const hit = await cache.match(request, { ignoreSearch: false });
    if (hit) return hit;
    return OFFLINE_JSON();
  }
}

// ---------- 策略二：HTML 入口（网络优先；离线回落缓存；再没有给离线页）----------
async function htmlNetworkFirst(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const res = await fetch(request);
    if (res.ok) {
      // 统一用 pathname 作键（"?fresh=…" 这类探测请求不另存一份）
      const key = new URL(request.url).pathname;
      await cache.put(key, res.clone());
    }
    return res;
  } catch (_) {
    const hit = await cache.match(new URL(request.url).pathname)
      || await cache.match("/index.html");
    if (hit) return hit;
    return new Response(OFFLINE_HTML, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
}

// ---------- 策略三：静态资源（stale-while-revalidate）----------
async function assetStaleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const key = new URL(request.url).pathname;
  const hit = await cache.match(key);
  const network = fetch(request).then(async (res) => {
    if (res.ok) await cache.put(key, res.clone());
    return res;
  }).catch(() => null);
  if (hit) return hit;                     // 先给缓存，网络在后台更新
  const fresh = await network;
  return fresh || OFFLINE_JSON();
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;                 // 写操作直通网络（离线必失败，不排队）

  let url;
  try { url = new URL(request.url); } catch (_) { return; }
  if (url.origin !== self.location.origin) return;      // 跨域（原文外链）不插手

  const path = url.pathname;

  // 原文代理不进缓存：可能是大文件，且带二进制/附件语义
  if (path.startsWith("/api/entries/") && path.endsWith("/file")) return;

  if (path.startsWith("/api/")) {
    event.respondWith(apiNetworkFirst(request));
    return;
  }
  if (SHELL_HTML.has(path)) {
    event.respondWith(htmlNetworkFirst(request));
    return;
  }
  if (path.startsWith("/vendor/") || /\.(css|js|png|ico|svg|webmanifest|woff2?)$/.test(path)) {
    event.respondWith(assetStaleWhileRevalidate(request));
    return;
  }
  // 其余（未知路径、导出下载等）直通网络
});