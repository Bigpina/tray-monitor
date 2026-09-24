// MiMo Cookie Sync — 把 platform.xiaomimimo.com 的 Cookie 推给本机 tray-monitor
// 通路①：cookies API 多过滤并集（闹钟/事件/手动触发）——核心通路
// 通路②：webRequest 捕获页面真实请求的 Cookie 头（可选增强，注册失败不得影响核心）
// 仅读取登录态 Cookie 并 POST 到 127.0.0.1，不接触账号密码，不发往任何外部地址。
const SYNC_URL = "http://127.0.0.1:39247/cookie";
const API_URL = "https://platform.xiaomimimo.com/api/v1/tokenPlan/usage";
const ORIGIN_URL = "https://platform.xiaomimimo.com/";
const ALARM = "mimo-cookie-sync";
const DEBOUNCE_MS = 2000;
const REQUIRED = ["api-platform_serviceToken", "userId"];

let pending = null;
let lastPushed = "";

function hasRequired(header) {
  const names = new Set(header.split(";").map((p) => (p.split("=")[0] || "").trim()));
  return REQUIRED.every((n) => names.has(n));
}

async function pushHeader(header, source) {
  if (!header || header === lastPushed) return false;
  const resp = await fetch(SYNC_URL, {
    method: "POST",
    headers: { "Content-Type": "text/plain" },
    body: header,
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
  lastPushed = header;
  await chrome.storage.local.set({
    lastOk: Date.now(),
    lastErr: "",
    source,
    count: header.split(";").length,
  });
  return true;
}

async function gatherCookies() {
  // 4 种过滤取并集：API 精确 url（防 Cookie path 过滤）+ 根 url + 父域/本域 domain（无 path 维度）
  const queries = [
    { url: API_URL },
    { url: ORIGIN_URL },
    { domain: "xiaomimimo.com" },
    { domain: "platform.xiaomimimo.com" },
  ];
  const seen = new Map();
  for (const q of queries) {
    try {
      const list = await chrome.cookies.getAll(q);
      for (const c of list) seen.set(`${c.name}\u0000${c.value}`, c);
    } catch (e) {
      // 单个过滤器失败不影响其余
    }
  }
  return [...seen.values()];
}

async function syncNow() {
  try {
    const cookies = await gatherCookies();
    const header = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    if (!header || !hasRequired(header)) {
      // getAll 偶发为空：只要成功过（lastOk 存在）就静默，避免把可用状态盖成“推送失败”
      const st = await chrome.storage.local.get(["lastOk"]);
      if (!st.lastOk) {
        await chrome.storage.local.set({
          lastErr: header
            ? `cookies API 只查到 ${cookies.length} 个但缺必需项`
            : "cookies API 查询为 0（已试 4 种过滤），等页面请求捕获",
          lastAt: Date.now(),
          count: cookies.length,
        });
      }
      return;
    }
    await pushHeader(header, `cookies-api(${cookies.length})`);
  } catch (e) {
    await chrome.storage.local.set({
      lastErr: String((e && e.message) || e),
      lastAt: Date.now(),
    });
  }
}

function scheduleSync() {
  if (pending) clearTimeout(pending);
  pending = setTimeout(() => {
    pending = null;
    syncNow();
  }, DEBOUNCE_MS);
}

// ============ 核心监听器（前置：任何后续代码失败都不得影响这里） ============

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg === "sync") {
    syncNow().then(() => sendResponse({ ok: true }));
    return true;
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
  scheduleSync();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
  scheduleSync();
});

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === ALARM) syncNow();
});

chrome.cookies.onChanged.addListener((info) => {
  const domain = info.cookie.domain.replace(/^\./, "");
  if (domain.endsWith("xiaomimimo.com")) scheduleSync();
});

// ============ 可选增强：webRequest 捕获页面请求的 Cookie 头 ============
// 特性检测 + try/catch：权限未生效时静默降级，绝不影响上面的核心通路。
try {
  if (chrome.webRequest && chrome.webRequest.onBeforeSendHeaders) {
    chrome.webRequest.onBeforeSendHeaders.addListener(
      (details) => {
        try {
          const hdrs = details.requestHeaders || [];
          const ck = hdrs.find((h) => (h.name || "").toLowerCase() === "cookie");
          if (ck && ck.value && ck.value.includes("api-platform_serviceToken")) {
            pushHeader(ck.value, "page-request").catch((e) =>
              chrome.storage.local.set({
                lastErr: String((e && e.message) || e),
                lastAt: Date.now(),
              })
            );
          }
        } catch (e) {
          // 忽略单次解析异常
        }
      },
      { urls: ["https://platform.xiaomimimo.com/*"] },
      ["requestHeaders", "extraHeaders"]
    );
  }
} catch (e) {
  // webRequest 不可用：仅记录状态，核心通路①不受影响
  chrome.storage.local.set({ wrErr: String((e && e.message) || e) });
}
