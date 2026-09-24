async function render() {
  const d = await chrome.storage.local.get(["lastOk", "lastErr", "count", "lastAt"]);
  const status = document.getElementById("status");
  const detail = document.getElementById("detail");
  if (d.lastErr) {
    status.textContent = "推送失败";
    status.className = "err";
    const t = d.lastAt ? new Date(d.lastAt).toLocaleTimeString() : "";
    detail.textContent = t ? `${d.lastErr}（${t}）` : d.lastErr;
  } else if (d.lastOk) {
    status.textContent = "正常";
    status.className = "ok";
    const t = new Date(d.lastOk).toLocaleTimeString();
    const src = d.source ? ` · ${d.source}` : "";
    detail.textContent = `上次推送 ${t} · ${d.count ?? "?"} 个 Cookie${src}`;
  } else {
    status.textContent = "等待首次推送";
    detail.textContent = "打开 platform.xiaomimimo.com 并登录";
  }
}

document.getElementById("btn").addEventListener("click", async () => {
  await chrome.runtime.sendMessage("sync");
  setTimeout(render, 400);
});

render();
