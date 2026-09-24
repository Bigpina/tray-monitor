"""usage_client: Xiaomi MiMo Token Plan 用量查询（独立模块）

tray-monitor v4.2.0 新增功能。与主程序解耦，便于单独测试（import 无副作用）。

接口:  GET https://platform.xiaomimimo.com/api/v1/tokenPlan/usage
鉴权:  小米账号登录态 Cookie（api-platform_serviceToken + userId），非 tp- API Key
响应:  percent 为 0~1 小数（2026-09-24 实测），接口直接给出百分比，无需自算
"""

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

ENDPOINT = "https://platform.xiaomimimo.com/api/v1/tokenPlan/usage"
ALLOWED_HOST = "platform.xiaomimimo.com"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class UsageError(Exception):
    """kind: auth=401失效 | nocookie=Cookie缺失/不可读 | net=网络错误
    | http=非预期状态码 | shape=响应结构不符"""

    def __init__(self, kind: str, message: str = ""):
        self.kind = kind
        super().__init__(message or kind)


def load_cookie(path: str) -> str:
    """读取 Cookie 文件（单行纯文本）。异常消息绝不包含 cookie 内容。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            val = f.read().strip()
    except OSError as e:
        raise UsageError("nocookie", f"无法读取 Cookie 文件: {e}")
    if not val:
        raise UsageError("nocookie", f"Cookie 文件为空: {path}")
    return val


def fetch_usage(cookie: str) -> dict:
    """调用量接口，返回解析后的 data 字段。失败抛 UsageError（消息不含 cookie）。"""
    # 安全阀：防止未来改动把凭证发错地方
    if urlparse(ENDPOINT).hostname != ALLOWED_HOST:
        raise UsageError("net", "endpoint host 校验失败，拒绝发送")
    req = urllib.request.Request(
        ENDPOINT,
        headers={
            "Cookie": cookie,
            "Accept": "application/json",
            "User-Agent": BROWSER_UA,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status, body = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise UsageError("net", str(getattr(e, "reason", e)))
    except OSError as e:
        raise UsageError("net", str(e))

    if status == 401:
        raise UsageError("auth", "Cookie 已失效")
    if status != 200:
        raise UsageError("http", f"HTTP {status}: {body[:200]}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise UsageError("shape", "响应不是 JSON")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise UsageError("shape", "缺少 data 字段")
    usage = data.get("usage")
    month = data.get("monthUsage")
    if not isinstance(usage, dict) or not isinstance(month, dict):
        raise UsageError("shape", "缺少 usage/monthUsage")
    if not isinstance(usage.get("percent"), (int, float)):
        raise UsageError("shape", "缺少 percent")
    return data


def _plan_item(usage: dict) -> dict:
    """从 usage.items 里取 plan_total_token 分项，缺失时退回第一个分项。"""
    items = usage.get("items") or []
    for it in items:
        if isinstance(it, dict) and it.get("name") == "plan_total_token":
            return it
    for it in items:
        if isinstance(it, dict):
            return it
    return {}


def summarize(data: dict) -> dict:
    """提取展示所需字段。"""
    usage = data.get("usage") or {}
    month = data.get("monthUsage") or {}
    item = _plan_item(usage)
    return {
        "plan_percent": float(usage.get("percent") or 0),
        "month_percent": float(month.get("percent") or 0),
        "used": int(item.get("used") or 0),
        "limit": int(item.get("limit") or 0),
    }


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return str(n)


def format_status(s: dict) -> str:
    """一行状态文本: 用量: 本月74.96% (28.48B/38.00B)"""
    return (
        f"用量: 本月{s['month_percent']:.2%} "
        f"({_fmt_tokens(s['used'])}/{_fmt_tokens(s['limit'])})"
    )


def query_usage_candidates(
    autosync_path: str | None, configured_path: str | None
) -> tuple[dict, str]:
    """按优先级尝试候选 Cookie：扩展自动推送(cookie_autosync.txt)优先，
    配置的 cookie.txt 兜底。返回 (data, 来源标签)。
    候选逐一尝试：401 换下一个，其他错误立即抛出。消息绝不含 cookie 内容。"""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, path in (("扩展推送", autosync_path), ("配置文件", configured_path)):
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                val = f.read().strip()
        except OSError:
            continue
        if val and val not in seen:
            seen.add(val)
            pairs.append((label, val))
    if not pairs:
        raise UsageError(
            "nocookie", "Cookie 文件均不可读或为空 (cookie_autosync.txt / cookie.txt)"
        )
    last_auth: UsageError | None = None
    for label, val in pairs:
        try:
            return fetch_usage(val), label
        except UsageError as e:
            if e.kind == "auth":
                last_auth = e  # 该来源已 401，换下一个候选
                continue
            raise
    raise last_auth if last_auth else UsageError("auth", "Cookie 已失效")
