"""
托盘监控程序
监控 OpenClaw Gateway 和 Syncthing 运行状态，异常自动重启。
纯托盘程序，无主窗口。双击 start.vbs 无窗口启动。
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# 本地模块（与 tray_monitor.py 同目录）
from usage_client import UsageError, format_status, query_usage, summarize

# ---------------------------------------------------------------------------
# 版本号
# ---------------------------------------------------------------------------
__version__ = "4.3.4"

import psutil
import pystray
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# 路径常量：区分打包环境与开发环境
# ---------------------------------------------------------------------------
def get_base_path() -> Path:
    """获取基础路径（打包后用 exe 所在目录，开发时用项目根目录）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent.parent


def get_resource_path() -> Path:
    """获取打包资源路径（图标等，打包后在临时目录 _MEIPASS）"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_base_path()
CONFIG_PATH = PROJECT_ROOT / "config.json"
CHANGELOG_PATH = PROJECT_ROOT / "CHANGELOG.md"
ICON_PATH = get_resource_path() / "icons" / "lobster.png"

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "syncthing_exe": r"C:\Program Files\syncthing-windows-amd64-v2.1.2\syncthing.exe",
    "openclaw_cmd": "openclaw",
    "node_exe": r"C:\Program Files\nodejs\node.exe",
    "openclaw_mjs": r"C:\Users\LiYuanbo\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs",
    "check_interval": 5,
    "max_fail_count": 3,
    "cooldown_seconds": 60,
    "dot_radius": 16,
    "log_level": "INFO",
    "gateway_url": "http://127.0.0.1:18789",
    "gateway_token_file": r"C:\Users\LiYuanbo\.openclaw\openclaw.json",
    "usage_interval": 600,
    "usage_alert_percent": 90,
    "usage_sync_port": 39247,
}

# ---------------------------------------------------------------------------
# 全局配置（运行时可热更新）
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """从 config.json 加载配置，缺失项使用默认值。"""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
        except Exception as e:
            print(f"[WARN] 读取 config.json 失败，使用默认配置: {e}")
    return cfg


def save_config(cfg: dict):
    """保存配置到 config.json。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


CONFIG = load_config()

# ---------------------------------------------------------------------------
# Syncthing 自动发现
# ---------------------------------------------------------------------------

def _find_syncthing_candidates() -> list[str]:
    """扫描常见路径，返回所有 syncthing.exe 候选（降序排列，版本号新的在前）。"""
    import glob
    candidates = []
    for pattern in [
        r"D:\APP\syncthing-*\syncthing.exe",
        r"C:\Program Files\syncthing-*\syncthing.exe",
        r"C:\Program Files\Syncthing\syncthing.exe",
        r"C:\Program Files (x86)\syncthing-*\syncthing.exe",
        r"C:\Program Files (x86)\Syncthing\syncthing.exe",
        os.path.expanduser(r"~\AppData\Local\Syncthing\syncthing.exe"),
    ]:
        for p in glob.glob(pattern):
            if p not in candidates:
                candidates.append(p)
    # PATH
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(dir_path.strip('"'), "syncthing.exe")
        if os.path.isfile(p) and p not in candidates:
            candidates.append(p)
    candidates.sort(reverse=True)
    return candidates


def _auto_detect_syncthing():
    """启动时自动检测 syncthing 路径。

    - 配置路径无效 → 扫描并写入最新版本
    - 配置路径有效但扫描到更新版本 → 自动升级并写入
    - 配置路径已是最新 → 不动
    """
    exe = CONFIG.get("syncthing_exe", "")
    candidates = _find_syncthing_candidates()

    if not candidates:
        if not exe or not Path(exe).exists():
            log.warning("自动扫描未找到 syncthing.exe")
        else:
            log.info("Syncthing 路径有效: %s", exe)
        return

    best = candidates[0]  # 降序排列，第一个是最新版本

    # 路径有效且已是最新 → 跳过
    if exe and Path(exe).exists():
        if os.path.normcase(os.path.normpath(exe)) == os.path.normcase(os.path.normpath(best)):
            log.info("Syncthing 路径已是最新: %s", exe)
            return
        # 扫描到更新版本
        log.info("发现更新版本 Syncthing: %s (当前: %s)", best, exe)
    else:
        log.info("syncthing_exe 路径不存在或未配置，自动扫描中...")

    log.info("自动设置 Syncthing: %s", best)
    CONFIG["syncthing_exe"] = best
    try:
        save_config(CONFIG)
        log.info("已写入 config.json")
    except Exception as e:
        log.error("写入 config.json 失败: %s", e)


# _auto_detect_syncthing()  # 移到日志初始化之后

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

_file_handler = TimedRotatingFileHandler(
    LOG_DIR / "tray_monitor.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
_file_handler.suffix = "%Y-%m-%d"
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))

logging.basicConfig(level=getattr(logging, CONFIG["log_level"].upper(), logging.INFO), handlers=[_file_handler, _console_handler])
log = logging.getLogger("tray-monitor")

# 日志就绪后再执行自动检测
_auto_detect_syncthing()

# ---------------------------------------------------------------------------
# 共享 Tk UI 根
# 在 pystray 旁边于临时线程里反复 tk.Tk() 容易在 Windows 上原生崩溃，
# 且 pythonw 下看不到 traceback。改为进程内单一隐藏根 + 专用 UI 线程。
# ---------------------------------------------------------------------------
_ui_root = None
_ui_root_ready = threading.Event()
_ui_root_lock = threading.Lock()
_icon_lock = threading.Lock()


def get_ui_root():
    """返回进程内唯一的隐藏 Tk 根（UI 线程上运行 mainloop）。

    线程安全约束（2026-09-26 死锁修复）：锁内绝不做任何 Tk 调用。
    tkinter 跨线程调用（如 winfo_exists）会阻塞等待 UI 线程服务，
    而 UI 线程打开设置窗时也要来取这把锁——双方互等形成 AB-BA 死锁，
    表现为左键双击无反应、右键菜单随后失效（py-spy 两次复现确认）。
    根的存活改由 UI 线程退出 mainloop 时在 finally 里清理，本函数
    只读 Python 引用，不碰 Tk。
    """
    global _ui_root
    with _ui_root_lock:
        if _ui_root is not None:
            return _ui_root

        def _ui_main():
            global _ui_root
            created = None
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                created = root
                _ui_root = root
                _ui_root_ready.set()
                log.info("UI 线程 Tk 根已启动")
                root.mainloop()
            except Exception:
                log.exception("UI 线程崩溃")
                _ui_root_ready.set()
            finally:
                # 只清理本线程创建的根：若退出时 _ui_root 已是新线程
                # 的新根（启动竞态），不能误清
                with _ui_root_lock:
                    if _ui_root is created:
                        _ui_root = None

        _ui_root_ready.clear()
        threading.Thread(target=_ui_main, daemon=True, name="tray-ui").start()
        if not _ui_root_ready.wait(timeout=8):
            log.error("UI 线程启动超时")
            return None
        return _ui_root


def run_on_ui(fn, *args, **kwargs):
    """把调用调度到 UI 线程执行；异常写入日志而不是让进程消失。"""
    root = get_ui_root()
    if root is None:
        log.error("UI 根不可用，无法调度 %s", getattr(fn, "__name__", fn))
        return

    def _call():
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("UI 回调异常: %s", getattr(fn, "__name__", fn))

    try:
        root.after(0, _call)
    except Exception:
        log.exception("调度到 UI 线程失败: %s", getattr(fn, "__name__", fn))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
CHECK_INTERVAL = CONFIG["check_interval"]
MAX_FAIL_COUNT = CONFIG["max_fail_count"]
COOLDOWN_SECONDS = CONFIG["cooldown_seconds"]
DOT_RADIUS = CONFIG["dot_radius"]  # 保留兼容，图标绘制使用 COMPOSITE_DOT_RADIUS

# 颜色
COLOR_GREEN = (0, 200, 80)
COLOR_BLUE = (50, 120, 255)
COLOR_RED = (220, 50, 50)
COLOR_GRAY = (128, 128, 128)
COLOR_TRANSPARENT = (0, 0, 0, 0)

TRAY_ICON_SIZE = (48, 48)  # 传给 pystray 的最终尺寸
COMPOSITE_SIZE = (128, 128)  # 合成时的工作尺寸（大一点画圆点更精细）

# 指示灯半径：优先使用配置值，确保与 config.json 同步
COMPOSITE_DOT_RADIUS = CONFIG.get("dot_radius", 16)

# ---------------------------------------------------------------------------
# 图标生成
# ---------------------------------------------------------------------------

def load_base_icon() -> Image.Image:
    """尝试加载 lobster.ico 作为基础图标，失败则生成纯色底图。"""
    if ICON_PATH.exists():
        try:
            return Image.open(ICON_PATH).convert("RGBA")
        except Exception as e:
            log.warning("加载图标失败: %s", e)
    img = Image.new("RGBA", (64, 64), (80, 80, 80, 255))
    return img


ICON_BASE = load_base_icon()


def build_status_icon(gw_ok: bool, st_ok: bool, paused: bool = False) -> Image.Image:
    """根据状态在基础图标上绘制指示灯，最终输出适合托盘的尺寸。
    pystray 在 Windows 上可以处理 RGBA 图像，这里直接返回 RGBA。
    paused=True 时显示灰色圆点表示暂停。
    """
    dr = COMPOSITE_DOT_RADIUS
    # 深色背景 + 虾合成
    bg = ICON_BASE.copy().resize(COMPOSITE_SIZE, Image.Resampling.LANCZOS).convert('RGBA')
    draw = ImageDraw.Draw(bg)
    margin = 2
    gap = 4
    cy = COMPOSITE_SIZE[1] - margin - dr
    bx = COMPOSITE_SIZE[0] - margin - dr
    gx = bx - dr * 2 - gap

    if paused:
        # 暂停状态：两个灰色圆点
        draw.ellipse([gx - dr, cy - dr, gx + dr, cy + dr], fill=COLOR_GRAY)
        draw.ellipse([bx - dr, cy - dr, bx + dr, cy + dr], fill=COLOR_GRAY)
    else:
        if gw_ok:
            draw.ellipse(
                [gx - dr, cy - dr, gx + dr, cy + dr],
                fill=COLOR_GREEN,
            )
        if st_ok:
            draw.ellipse(
                [bx - dr, cy - dr, bx + dr, cy + dr],
                fill=COLOR_BLUE,
            )
    # 缩小到托盘尺寸，转 RGB
    return bg.resize(TRAY_ICON_SIZE, Image.Resampling.LANCZOS)

# ---------------------------------------------------------------------------
# 进程检测
# ---------------------------------------------------------------------------

def is_process_running(name_pattern: str) -> bool:
    """检查是否有进程名包含指定字符串。"""
    for proc in psutil.process_iter(["name"]):
        try:
            if name_pattern.lower() in (proc.info["name"] or "").lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _get_openclaw_cmd() -> list[str]:
    """返回 openclaw CLI 命令列表。优先用 node.exe + openclaw.mjs，否则自动探测。"""
    node_exe = CONFIG.get("node_exe", "")
    openclaw_mjs = CONFIG.get("openclaw_mjs", "")
    if node_exe and openclaw_mjs and Path(node_exe).exists() and Path(openclaw_mjs).exists():
        return [node_exe, openclaw_mjs]
    # 自动探测：在 PATH 上找 openclaw，处理 .cmd/.bat 的情况
    openclaw_cmd = CONFIG.get("openclaw_cmd", "openclaw")
    resolved = _resolve_cmd(openclaw_cmd)
    return resolved


def _resolve_cmd(cmd: str) -> list[str]:
    """解析命令路径。Windows 上 .cmd/.bat 需要通过 cmd /c 调用。"""
    import shutil
    found = shutil.which(cmd)
    if found:
        # Windows 上 .cmd/.bat 不能直接被 subprocess.Popen 找到，需要 cmd /c
        if found.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/c", found]
        return [found]
    # shutil.which 没找到，尝试直接用（让 subprocess 自己报错）
    return [cmd]


def _describe_openclaw_cli(openclaw_cmd=None, node_exe=None, openclaw_mjs=None) -> tuple[bool, str]:
    """返回 (是否解析成功, 设置窗展示文本)。参数为 None 时读 CONFIG。"""
    oc = openclaw_cmd if openclaw_cmd is not None else CONFIG.get("openclaw_cmd", "openclaw")
    oc = (oc or "openclaw").strip() or "openclaw"
    node = node_exe if node_exe is not None else CONFIG.get("node_exe", "")
    mjs = openclaw_mjs if openclaw_mjs is not None else CONFIG.get("openclaw_mjs", "")

    if node and mjs and Path(node).exists() and Path(mjs).exists():
        return True, f"{node} {mjs}\nnode 直调 · openclaw_cmd=「{oc}」"

    resolved = _resolve_cmd(oc)
    if len(resolved) >= 2 and resolved[0].lower() == "cmd":
        path = resolved[-1]
        if Path(path).exists():
            return True, f"{path}\n经 cmd /c 调用 · openclaw_cmd=「{oc}」"
        return False, f"未找到「{oc}」，请安装到 PATH 或手动指定"

    path = resolved[0]
    if Path(path).exists() or shutil.which(path):
        return True, f"{path}\n经 PATH 解析 · openclaw_cmd=「{oc}」"
    return False, f"未在 PATH 中找到「{oc}」，请安装或手动指定"


def _check_gateway_via_cli() -> bool | None:
    """尝试运行 openclaw gateway status，返回 True/False/None。"""
    cmd = _get_openclaw_cmd()
    try:
        result = subprocess.run(
            cmd + ["gateway", "status"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = (result.stdout + result.stderr).lower()
        # 注意："not running" 包含子串 "running"，必须先匹配更具体的状态词
        if "not running" in output or "stopped" in output:
            return False
        if "running" in output:
            return True
        return None
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def _check_gateway_via_http() -> bool | None:
    """通过 HTTP health 端点检测 Gateway 是否运行。"""
    url = CONFIG.get("gateway_url", "http://127.0.0.1:18789")
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok") is True
    except Exception:
        return None


def _check_gateway_via_process() -> bool:
    """扫描 node 进程的命令行，检查是否包含 openclaw gateway 监听进程。
    支持两种启动方式：
    - gateway run（手动/旧方式）
    - gateway --port（服务方式，由 Task Scheduler 启动）
    """
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = (proc.info["name"] or "").lower()
            if "node" not in name:
                continue
            cmdline_parts = [p.lower() for p in proc.cmdline()]
            has_openclaw = any("openclaw" in p for p in cmdline_parts)
            has_gateway = any(p == "gateway" for p in cmdline_parts)
            # 匹配 gateway run（手动）或 gateway + --port（服务）
            has_run = any(p == "run" for p in cmdline_parts)
            has_port = any(p.startswith("--port") for p in cmdline_parts)
            if has_openclaw and has_gateway and (has_run or has_port):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


def is_gateway_running() -> bool:
    """检测 Gateway 是否运行。优先 HTTP，次选 CLI，兜底扫描进程。"""
    # 方式1（首选）：HTTP health 端点
    http_result = _check_gateway_via_http()
    if http_result is not None:
        return http_result
    # 方式2（次选）：CLI 命令
    cli_result = _check_gateway_via_cli()
    if cli_result is not None:
        return cli_result
    # 方式3（最后兜底）：进程扫描
    return _check_gateway_via_process()


def is_syncthing_running() -> bool:
    return is_process_running("syncthing")

# ---------------------------------------------------------------------------
# Agent 信息获取
# ---------------------------------------------------------------------------

def _read_gateway_token() -> str | None:
    """从 openclaw.json 中读取 gateway.auth.token。"""
    token_file = CONFIG.get("gateway_token_file", "")
    if not token_file or not Path(token_file).exists():
        return None
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            content = f.read()
        # 用正则提取 token 值，避免 JSON5 解析问题
        m = re.search(r'"token"\s*:\s*"([^"]+)"', content)
        if m:
            return m.group(1)
    except Exception as e:
        log.debug("读取 gateway token 失败: %s", e)
    return None


def fetch_agents() -> list[dict]:
    """调用 admin-http-rpc 获取 agent 列表。返回 agent 字典列表，失败返回空列表。
    每个 agent dict 添加 _healthy 字段：检查 workspace/agentDir 是否存在。"""
    url = CONFIG.get("gateway_url", "")
    if not url:
        return []
    token = _read_gateway_token()
    if not token:
        log.debug("无 gateway token，跳过 agent 获取")
        return []
    try:
        payload = json.dumps({"method": "agents.list", "params": {}}).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/api/v1/admin/rpc",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            agents = data.get("payload", {}).get("agents", [])
            # 健康检查：workspace 和 agentDir 是否存在
            for a in agents:
                healthy = True
                ws = a.get("workspace", "")
                ad = a.get("agentDir", "")
                if ws and not Path(ws).exists():
                    healthy = False
                if ad and not Path(ad).exists():
                    healthy = False
                a["_healthy"] = healthy
            return agents
    except Exception as e:
        log.debug("获取 agent 列表失败: %s", e)
    return []


def _format_agents_line(agents: list[dict]) -> str:
    """将 agent 列表格式化为一行文本。只显示 _healthy=True 的 agent。"""
    if not agents:
        return ""
    parts = []
    for a in agents:
        if not a.get("_healthy", True):
            continue
        emoji = a.get("identity", {}).get("emoji", "")
        name = a.get("name", a.get("id", "?"))
        parts.append(f"{emoji}{name}")
    if not parts:
        return ""
    return "Agents: " + " ".join(parts)

# ---------------------------------------------------------------------------
# 直接启动服务（替代 VBS 脚本）
# ---------------------------------------------------------------------------

def start_syncthing() -> bool:
    """直接启动 Syncthing（无窗口）。"""
    exe = CONFIG.get("syncthing_exe", "")
    if not exe or not Path(exe).exists():
        log.error("Syncthing 可执行文件不存在: %s", exe)
        return False
    try:
        subprocess.Popen(
            [exe, "serve", "--no-browser"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.info("已启动 Syncthing: %s", exe)
        return True
    except Exception as e:
        log.error("启动 Syncthing 失败: %s", e)
        return False


def restart_gateway() -> bool:
    """通过官方推荐方式管理 Gateway 服务。
    - 已运行时：gateway restart（安全排空后重启）
    - 未运行时：gateway start（启动服务）
    """
    cmd = _get_openclaw_cmd()
    # 先判断 Gateway 是否在运行，决定用 start 还是 restart
    running = _check_gateway_via_http() or _check_gateway_via_process()
    subcmd = "restart" if running else "start"
    try:
        result = subprocess.run(
            cmd + ["gateway", subcmd],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            log.info("Gateway %s 成功", subcmd)
            return True
        else:
            log.error("Gateway %s 失败 (exit=%d): %s", subcmd, result.returncode, result.stderr.strip())
            return False
    except subprocess.TimeoutExpired:
        log.error("Gateway %s 超时", subcmd)
        return False
    except Exception as e:
        log.error("Gateway %s 异常: %s", subcmd, e)
        return False

# ---------------------------------------------------------------------------
# 监控状态
# ---------------------------------------------------------------------------

class MonitorState:
    """跟踪各服务的监控状态。"""

    def __init__(self):
        self.paused = False
        self.gateway_fails = 0
        self.syncthing_fails = 0
        self.gateway_cooldown_until = 0.0
        self.syncthing_cooldown_until = 0.0

    def toggle_pause(self):
        """切换暂停状态。"""
        self.paused = not self.paused
        return self.paused

    def gateway_check(self) -> str:
        now = time.time()
        if now < self.gateway_cooldown_until:
            return "cooldown"
        if is_gateway_running():
            self.gateway_fails = 0
            return "ok"
        self.gateway_fails += 1
        if self.gateway_fails >= CONFIG["max_fail_count"]:
            self.gateway_cooldown_until = now + CONFIG["cooldown_seconds"]
            self.gateway_fails = 0
            log.warning("Gateway 连续失败 %d 次，进入冷却 %ds",
                        CONFIG["max_fail_count"], CONFIG["cooldown_seconds"])
            return "cooldown"
        return "restart"

    def syncthing_check(self) -> str:
        now = time.time()
        if now < self.syncthing_cooldown_until:
            return "cooldown"
        if is_syncthing_running():
            self.syncthing_fails = 0
            return "ok"
        self.syncthing_fails += 1
        if self.syncthing_fails >= CONFIG["max_fail_count"]:
            self.syncthing_cooldown_until = now + CONFIG["cooldown_seconds"]
            self.syncthing_fails = 0
            log.warning("Syncthing 连续失败 %d 次，进入冷却 %ds",
                        CONFIG["max_fail_count"], CONFIG["cooldown_seconds"])
            return "cooldown"
        return "restart"

# ---------------------------------------------------------------------------
# 设置窗口
# ---------------------------------------------------------------------------

class SettingsWindow:
    """tkinter 配置窗口（分组布局 + OpenClaw CLI 自动探测）。"""

    CLR_OK_BG = "#E8F6EE"
    CLR_OK_FG = "#0F5C32"
    CLR_WARN_BG = "#FEF3C7"
    CLR_WARN_FG = "#854F0B"
    CLR_CARD_BG = "#FFFFFF"
    CLR_MUTED = "#616161"
    CLR_ACCENT = "#C4281C"
    FONT_UI = ("Microsoft YaHei UI", 9)
    FONT_UI_BOLD = ("Microsoft YaHei UI", 9, "bold")
    FONT_MONO = ("Consolas", 9)
    FONT_GROUP = ("Microsoft YaHei UI", 8, "bold")

    def __init__(self, on_save_callback=None, monitor=None):
        self.on_save_callback = on_save_callback
        self.monitor = monitor
        self.win = None

    def show(self):
        def _open():
            if self.win is not None:
                try:
                    if self.win.winfo_exists():
                        self.win.deiconify()
                        self.win.lift()
                        self.win.focus_force()
                        return
                except Exception:
                    pass
                self.win = None
            self._build_window()
        run_on_ui(_open)

    def _usage_display_text(self) -> str:
        """当前用量一行文本（设置窗状态区显示用）。"""
        m = self.monitor
        if m is None:
            return "用量: 未连接"
        line = m._usage_line or "用量: 查询中..."
        if m._usage_ok and m._usage_source:
            line += f"  [{m._usage_source}]"
        if m._usage_updated_at:
            line += f"  · 更新 {m._usage_updated_at}"
        return line

    def _build_window(self):
        import tkinter as tk
        from tkinter import ttk

        root = get_ui_root()
        if root is None:
            log.error("无法打开设置窗：UI 根不可用")
            return

        self.win = tk.Toplevel(root)
        self.win.title(f"设置 · 托盘监控 v{__version__}")
        self.win.geometry("560x770")
        self.win.minsize(520, 560)
        self.win.configure(bg="#F3F3F3")

        cfg = dict(CONFIG)
        outer = ttk.Frame(self.win, padding=(12, 10, 12, 12))
        outer.pack(fill="both", expand=True)

        # --- 顶部状态条 ---
        status = ttk.LabelFrame(outer, text=" 当前状态 ", padding=8)
        status.pack(fill="x", pady=(0, 10))
        gw_ok = bool(_check_gateway_via_process())
        st_ok = is_syncthing_running()
        gw_txt = f"Gateway  {'正常' if gw_ok else '未检测到'}"
        st_txt = f"Syncthing  {'正常' if st_ok else '未检测到'}"
        ttk.Label(status, text=f"●  {gw_txt}", foreground="#1F9D55" if gw_ok else self.CLR_MUTED,
                  font=self.FONT_UI).pack(side="left", padx=(0, 16))
        ttk.Label(status, text=f"●  {st_txt}", foreground="#2B6CB0" if st_ok else self.CLR_MUTED,
                  font=self.FONT_UI).pack(side="left")
        ttk.Label(status, text=cfg.get("gateway_url", ""), foreground=self.CLR_MUTED,
                  font=self.FONT_MONO).pack(side="right")

        # --- 服务路径 ---
        g_path = ttk.LabelFrame(outer, text=" 服务路径 ", padding=10)
        g_path.pack(fill="x", pady=(0, 10))
        g_path.columnconfigure(1, weight=1)

        ttk.Label(g_path, text="Syncthing 可执行文件", font=self.FONT_UI,
                  foreground=self.CLR_MUTED).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        var_st = tk.StringVar(value=cfg.get("syncthing_exe", ""))
        ent_st = ttk.Entry(g_path, textvariable=var_st, font=self.FONT_MONO)
        ent_st.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 6))
        st_btns = ttk.Frame(g_path)
        st_btns.grid(row=1, column=2, sticky="e")
        ttk.Button(st_btns, text="浏览", width=6,
                   command=lambda: self._browse_file(var_st)).pack(side="left", padx=(0, 4))
        ttk.Button(st_btns, text="扫描", width=6,
                   command=lambda: self._scan_syncthing(var_st)).pack(side="left")

        ttk.Separator(g_path, orient="horizontal").grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=10)

        ttk.Label(g_path, text="OpenClaw CLI（自动探测）", font=self.FONT_UI,
                  foreground=self.CLR_MUTED).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))

        # CLI 状态面板（找到 / 未找到 两种态）
        self._cli_host = tk.Frame(g_path, bd=0, highlightthickness=0)
        self._cli_host.grid(row=4, column=0, columnspan=3, sticky="ew")

        # --- 监控策略 ---
        g_mon = ttk.LabelFrame(outer, text=" 监控策略 ", padding=10)
        g_mon.pack(fill="x", pady=(0, 10))
        for i in range(3):
            g_mon.columnconfigure(i, weight=1)

        var_interval = tk.StringVar(value=str(cfg.get("check_interval", 10)))
        var_maxfail = tk.StringVar(value=str(cfg.get("max_fail_count", 3)))
        var_cooldown = tk.StringVar(value=str(cfg.get("cooldown_seconds", 120)))

        for col, (label, var) in enumerate([
            ("检测间隔（秒）", var_interval),
            ("失败次数上限", var_maxfail),
            ("冷却时长（秒）", var_cooldown),
        ]):
            cell = ttk.Frame(g_mon)
            cell.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            ttk.Label(cell, text=label, font=self.FONT_UI,
                      foreground=self.CLR_MUTED).pack(anchor="w", pady=(0, 4))
            ttk.Entry(cell, textvariable=var, font=self.FONT_UI).pack(fill="x")

        # --- Token Plan 用量 ---
        g_usage = ttk.LabelFrame(outer, text=" Token Plan 用量 ", padding=10)
        g_usage.pack(fill="x", pady=(0, 10))
        for _c in (0, 1):
            g_usage.columnconfigure(_c, weight=1)

        # 当前用量（来自托盘运行状态，每 5 秒刷新）
        self._usage_var = tk.StringVar(value=self._usage_display_text())
        ttk.Label(g_usage, textvariable=self._usage_var, font=self.FONT_UI).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(g_usage,
                  text="Cookie 由 Edge 扩展自动推送（cookie_autosync.txt），无需手动配置",
                  font=self.FONT_UI, foreground=self.CLR_MUTED).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 4))

        var_usage_interval = tk.StringVar(value=str(cfg.get("usage_interval", 600)))
        var_usage_alert = tk.StringVar(value=str(cfg.get("usage_alert_percent", 90)))
        for col, (label, var) in enumerate([
            ("查询间隔（秒, ≥60）", var_usage_interval),
            ("超额提醒阈值（%, 0=关）", var_usage_alert),
        ]):
            cell = ttk.Frame(g_usage)
            cell.grid(row=2, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0), pady=(8, 0))
            ttk.Label(cell, text=label, font=self.FONT_UI,
                      foreground=self.CLR_MUTED).pack(anchor="w", pady=(0, 4))
            ttk.Entry(cell, textvariable=var, font=self.FONT_UI).pack(fill="x")

        # --- 日志 ---
        g_log = ttk.LabelFrame(outer, text=" 日志 ", padding=10)
        g_log.pack(fill="x", pady=(0, 10))
        ttk.Label(g_log, text="日志级别", font=self.FONT_UI,
                  foreground=self.CLR_MUTED).pack(anchor="w", pady=(0, 4))
        var_loglevel = tk.StringVar(value=cfg.get("log_level", "INFO"))
        ttk.Combobox(g_log, textvariable=var_loglevel, state="readonly",
                     values=["DEBUG", "INFO", "WARNING", "ERROR"], width=12,
                     font=self.FONT_UI).pack(anchor="w")

        # --- 高级（默认折叠）---
        show_adv = tk.BooleanVar(value=False)
        adv_wrap = ttk.Frame(outer)
        adv_wrap.pack(fill="x", pady=(0, 10))

        def _toggle_adv():
            if show_adv.get():
                adv_frame.pack(fill="x", pady=(6, 0))
            else:
                adv_frame.pack_forget()

        ttk.Checkbutton(
            adv_wrap, text="高级 · 命令解析覆盖",
            variable=show_adv, command=_toggle_adv,
            style="TCheckbutton",
        ).pack(anchor="w")

        adv_frame = ttk.LabelFrame(adv_wrap, text=" 一般无需修改 ", padding=10)
        adv_frame.columnconfigure(1, weight=1)

        ttk.Label(adv_frame, text="留空 node / mjs 则走 PATH 自动探测；openclaw_cmd 为回退命令名。",
                  font=self.FONT_UI, foreground=self.CLR_MUTED,
                  wraplength=480, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        var_node = tk.StringVar(value=cfg.get("node_exe", ""))
        var_mjs = tk.StringVar(value=cfg.get("openclaw_mjs", ""))
        var_oc = tk.StringVar(value=cfg.get("openclaw_cmd", "openclaw") or "openclaw")

        def _add_adv_row(row, label, var, browse=False):
            ttk.Label(adv_frame, text=label, font=self.FONT_UI).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            ent = ttk.Entry(adv_frame, textvariable=var, font=self.FONT_MONO)
            ent.grid(row=row, column=1, sticky="ew", pady=3)
            if browse:
                ttk.Button(adv_frame, text="浏览", width=6,
                           command=lambda: self._browse_file(var)).grid(
                    row=row, column=2, padx=(6, 0), pady=3)

        _add_adv_row(1, "node.exe", var_node, browse=True)
        _add_adv_row(2, "openclaw.mjs", var_mjs, browse=True)
        _add_adv_row(3, "openclaw_cmd", var_oc, browse=True)

        # 供 CLI 面板刷新时读取未保存的高级值
        self._adv_vars = {"oc": var_oc, "node": var_node, "mjs": var_mjs}
        self._render_cli_panel()

        # --- 底部按钮 ---
        footer = ttk.Frame(outer)
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, text="保存后立即生效", font=self.FONT_UI,
                  foreground=self.CLR_MUTED).pack(side="left")
        btns = ttk.Frame(footer)
        btns.pack(side="right")
        ttk.Button(btns, text="恢复默认", width=10,
                   command=lambda: self._restore_defaults(
                       var_st, var_oc, var_node, var_mjs,
                       var_interval, var_maxfail, var_cooldown, var_loglevel,
                       var_usage_interval, var_usage_alert,
                       self._render_cli_panel)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="取消", width=8, command=self._cancel).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="保存", width=8,
                   command=lambda: self._save(
                       var_st, var_oc, var_node, var_mjs,
                       var_interval, var_maxfail, var_cooldown, var_loglevel,
                       var_usage_file, var_usage_interval, var_usage_alert)).pack(side="left")

        # 用量动态刷新：窗口存活期间每 5 秒同步一次托盘运行状态
        usage_win = self.win

        def _refresh_usage():
            if self.win is not usage_win or not usage_win.winfo_exists():
                return
            self._usage_var.set(self._usage_display_text())
            usage_win.after(5000, _refresh_usage)

        usage_win.after(5000, _refresh_usage)

        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.focus_force()

    def _render_cli_panel(self):
        """根据当前配置/高级输入重绘 OpenClaw CLI 探测面板。"""
        import tkinter as tk

        for child in self._cli_host.winfo_children():
            child.destroy()

        adv = getattr(self, "_adv_vars", None)
        oc = adv["oc"].get() if adv else None
        node = adv["node"].get() if adv else None
        mjs = adv["mjs"].get() if adv else None
        ok, text = _describe_openclaw_cli(
            openclaw_cmd=oc or None,
            node_exe=node or None,
            openclaw_mjs=mjs or None,
        )

        bg = self.CLR_OK_BG if ok else self.CLR_WARN_BG
        fg = self.CLR_OK_FG if ok else self.CLR_WARN_FG
        panel = tk.Frame(self._cli_host, bg=bg, padx=10, pady=8)
        panel.pack(fill="x")

        head = "✓ 已自动解析" if ok else "! 未找到 CLI"
        tk.Label(panel, text=head, bg=bg, fg=fg, font=self.FONT_UI_BOLD,
                 anchor="w", justify="left").pack(anchor="w")
        tk.Label(panel, text=text, bg=bg, fg="#1A1A1A", font=self.FONT_MONO,
                 anchor="w", justify="left", wraplength=460).pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(panel, bg=bg)
        actions.pack(anchor="e", pady=(6, 0))
        tk.Button(
            actions, text="重新检测", font=self.FONT_UI, relief="flat",
            activebackground=bg, bg=bg, fg=fg, bd=0, cursor="hand2",
            command=self._render_cli_panel,
        ).pack(side="right")

        if not ok:
            manual = tk.Frame(panel, bg=bg)
            manual.pack(fill="x", pady=(8, 0))
            tk.Label(manual, text="手动指定", bg=bg, fg=fg, font=self.FONT_UI).pack(side="left")
            var_manual = tk.StringVar(value="")
            tk.Entry(manual, textvariable=var_manual, font=self.FONT_MONO).pack(
                side="left", fill="x", expand=True, padx=6)

            def _apply_manual():
                val = var_manual.get().strip()
                if not val:
                    return
                self._adv_vars["oc"].set(val)
                self._render_cli_panel()

            tk.Button(manual, text="应用", font=self.FONT_UI, command=_apply_manual).pack(side="left")

    def _browse_file(self, var):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择可执行文件",
            filetypes=[("可执行文件", "*.exe;*.cmd;*.bat;*.ps1"), ("所有文件", "*.*")])
        if path:
            var.set(path)

    def _scan_syncthing(self, var):
        from tkinter import messagebox
        candidates = _find_syncthing_candidates()

        if not candidates:
            messagebox.showinfo(
                "扫描结果",
                "未找到 syncthing.exe。\n请确认已安装 Syncthing，或使用「浏览」手动选择。")
            return

        if len(candidates) == 1:
            if messagebox.askyesno("扫描结果", f"找到 Syncthing：\n{candidates[0]}\n\n是否使用此路径？"):
                var.set(candidates[0])
            return

        self._show_scan_result(candidates, var)

    def _show_scan_result(self, candidates, var):
        import tkinter as tk
        from tkinter import messagebox

        win = tk.Toplevel(self.win)
        win.title("扫描结果 - 选择 Syncthing")
        win.geometry("520x300")
        win.resizable(False, False)
        win.transient(self.win)
        win.grab_set()

        tk.Label(win, text=f"找到 {len(candidates)} 个 Syncthing，请选择：").pack(
            anchor="w", padx=10, pady=(10, 5))

        listbox = tk.Listbox(win, height=8, font=self.FONT_MONO)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)
        for p in candidates:
            listbox.insert(tk.END, p)
        listbox.selection_set(0)

        def confirm():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("提示", "请先选择一个路径。", parent=win)
                return
            var.set(candidates[sel[0]])
            win.destroy()

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=(5, 10))
        tk.Button(btn_frame, text="确定", width=10, command=confirm).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", width=10, command=win.destroy).pack(side="left", padx=5)

    def _save(self, var_st, var_oc, var_node, var_mjs,
              var_interval, var_maxfail, var_cooldown, var_loglevel,
              var_usage_file, var_usage_interval, var_usage_alert):
        from tkinter import messagebox
        try:
            interval = int(var_interval.get())
            maxfail = int(var_maxfail.get())
            cooldown = int(var_cooldown.get())
            if interval < 1 or maxfail < 1 or cooldown < 1:
                raise ValueError("数值必须 >= 1")
            usage_interval = int(var_usage_interval.get())
            usage_alert = float(var_usage_alert.get())
            if usage_interval < 60:
                raise ValueError("用量查询间隔必须 >= 60 秒")
            if not 0 <= usage_alert <= 100:
                raise ValueError("用量提醒阈值需在 0~100 之间")
            if usage_alert == int(usage_alert):
                usage_alert = int(usage_alert)
        except ValueError as e:
            messagebox.showerror("参数错误", f"请输入有效的数值。\n{e}")
            return

        new_cfg = {
            "syncthing_exe": var_st.get().strip(),
            "openclaw_cmd": var_oc.get().strip() or "openclaw",
            "node_exe": var_node.get().strip(),
            "openclaw_mjs": var_mjs.get().strip(),
            "check_interval": interval,
            "max_fail_count": maxfail,
            "cooldown_seconds": cooldown,
            "dot_radius": CONFIG.get("dot_radius", 16),
            "log_level": var_loglevel.get(),
            "gateway_url": CONFIG.get("gateway_url", ""),
            "gateway_token_file": CONFIG.get("gateway_token_file", ""),
            "usage_interval": usage_interval,
            "usage_alert_percent": usage_alert,
        }

        save_config(new_cfg)
        CONFIG.clear()
        CONFIG.update(new_cfg)

        global CHECK_INTERVAL, MAX_FAIL_COUNT, COOLDOWN_SECONDS, DOT_RADIUS, COMPOSITE_DOT_RADIUS
        CHECK_INTERVAL = interval
        MAX_FAIL_COUNT = maxfail
        COOLDOWN_SECONDS = cooldown
        DOT_RADIUS = new_cfg.get("dot_radius", 16)
        COMPOSITE_DOT_RADIUS = new_cfg.get("dot_radius", 16)

        logging.getLogger("tray-monitor").setLevel(
            getattr(logging, new_cfg["log_level"].upper(), logging.INFO))

        log.info("配置已保存并生效")

        if self.on_save_callback:
            self.on_save_callback()

        self._close()

    def _cancel(self):
        self._close()

    def _restore_defaults(self, var_st, var_oc, var_node, var_mjs,
                          var_interval, var_maxfail, var_cooldown, var_loglevel,
                          var_usage_interval, var_usage_alert,
                          refresh_cli=None):
        var_st.set(DEFAULT_CONFIG["syncthing_exe"])
        var_oc.set(DEFAULT_CONFIG["openclaw_cmd"])
        var_node.set(DEFAULT_CONFIG.get("node_exe", ""))
        var_mjs.set(DEFAULT_CONFIG.get("openclaw_mjs", ""))
        var_interval.set(str(DEFAULT_CONFIG["check_interval"]))
        var_maxfail.set(str(DEFAULT_CONFIG["max_fail_count"]))
        var_cooldown.set(str(DEFAULT_CONFIG["cooldown_seconds"]))
        var_loglevel.set(DEFAULT_CONFIG["log_level"])
        var_usage_interval.set(str(DEFAULT_CONFIG.get("usage_interval", 600)))
        var_usage_alert.set(str(DEFAULT_CONFIG.get("usage_alert_percent", 90)))
        if refresh_cli:
            refresh_cli()

    def _close(self):
        win, self.win = self.win, None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

# ---------------------------------------------------------------------------
# 更新说明窗口
# ---------------------------------------------------------------------------

class ChangelogWindow:
    """显示版本更新说明的窗口（Markdown 子集渲染）。"""

    CLR_BG = "#F3F3F3"
    CLR_CARD = "#FFFFFF"
    CLR_INK = "#1A1A1A"
    CLR_MUTED = "#616161"
    CLR_ACCENT = "#C4281C"
    CLR_ACCENT_SOFT = "#FCEBEA"
    CLR_LINE = "#E0E0E0"
    FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")
    FONT_SUB = ("Microsoft YaHei UI", 9)
    FONT_BODY = ("Microsoft YaHei UI", 9)
    FONT_MONO = ("Consolas", 9)
    FONT_VER = ("Microsoft YaHei UI", 11, "bold")
    FONT_SEC = ("Microsoft YaHei UI", 9, "bold")

    def __init__(self):
        self.win = None

    def show(self):
        def _open():
            if self.win is not None:
                try:
                    if self.win.winfo_exists():
                        self.win.deiconify()
                        self.win.lift()
                        self.win.focus_force()
                        return
                except Exception:
                    pass
                self.win = None
            self._build_window()
        run_on_ui(_open)

    def _build_window(self):
        import tkinter as tk
        from tkinter import ttk

        root = get_ui_root()
        if root is None:
            log.error("无法打开更新说明：UI 根不可用")
            return

        self.win = tk.Toplevel(root)
        self.win.title(f"更新说明 · 托盘监控 v{__version__}")
        self.win.geometry("580x520")
        self.win.minsize(420, 360)
        self.win.configure(bg=self.CLR_BG)

        outer = ttk.Frame(self.win, padding=(12, 10, 12, 12))
        outer.pack(fill="both", expand=True)

        # --- 头部 ---
        header = tk.Frame(outer, bg=self.CLR_CARD, padx=12, pady=12)
        header.pack(fill="x", pady=(0, 10))

        left = tk.Frame(header, bg=self.CLR_CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=f"托盘监控 v{__version__}", bg=self.CLR_CARD, fg=self.CLR_INK,
                 font=self.FONT_TITLE, anchor="w").pack(anchor="w")
        tk.Label(left, text="版本变更历史 · 格式基于 Keep a Changelog", bg=self.CLR_CARD,
                 fg=self.CLR_MUTED, font=self.FONT_SUB, anchor="w").pack(anchor="w", pady=(4, 0))

        badge = tk.Label(header, text="当前版本", bg=self.CLR_ACCENT_SOFT, fg=self.CLR_ACCENT,
                         font=self.FONT_SUB, padx=8, pady=3)
        badge.pack(side="right", anchor="n")

        # --- 正文 ---
        body = tk.Frame(outer, bg=self.CLR_CARD)
        body.pack(fill="both", expand=True)

        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")

        text = tk.Text(
            body, wrap="word", relief="flat", bd=0,
            font=self.FONT_BODY, fg=self.CLR_INK, bg=self.CLR_CARD,
            padx=14, pady=12, spacing1=2, spacing3=4,
            yscrollcommand=scroll.set, state="disabled",
            cursor="arrow",
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)

        self._configure_tags(text)
        self._render_markdown(text, self._load_changelog())
        text.config(state="disabled")

        # --- 底部 ---
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(footer, text=f"文件：{CHANGELOG_PATH.name}", font=self.FONT_SUB,
                  foreground=self.CLR_MUTED).pack(side="left")
        ttk.Button(footer, text="关闭", width=8, command=self._close).pack(side="right")

        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.focus_force()

    def _configure_tags(self, text):
        text.tag_configure("h1", font=self.FONT_TITLE, foreground=self.CLR_INK,
                           spacing1=8, spacing3=6)
        text.tag_configure("intro", font=self.FONT_SUB, foreground=self.CLR_MUTED,
                           spacing3=10, lmargin1=0, lmargin2=0)
        text.tag_configure("version", font=self.FONT_VER, foreground=self.CLR_ACCENT,
                           background=self.CLR_ACCENT_SOFT,
                           spacing1=12, spacing3=6,
                           lmargin1=8, lmargin2=8, rmargin=8)
        text.tag_configure("section", font=self.FONT_SEC, foreground=self.CLR_INK,
                           spacing1=10, spacing3=4)
        text.tag_configure("bullet", font=self.FONT_BODY, foreground=self.CLR_INK,
                           lmargin1=18, lmargin2=32, spacing3=3)
        text.tag_configure("bold", font=("Microsoft YaHei UI", 9, "bold"))
        text.tag_configure("code", font=self.FONT_MONO, background="#F0F0F0")
        text.tag_configure("hr", font=self.FONT_SUB, foreground=self.CLR_LINE,
                           spacing1=8, spacing3=8)

    def _load_changelog(self) -> str:
        if CHANGELOG_PATH.exists():
            try:
                return CHANGELOG_PATH.read_text(encoding="utf-8")
            except Exception as e:
                return f"# 读取失败\n\n读取 CHANGELOG.md 失败: {e}"
        return "# 未找到\n\n未找到 CHANGELOG.md 文件。"

    def _render_markdown(self, text, content: str):
        """渲染 Markdown 子集：H1 / 版本标题 / 小节 / 列表 / 粗体 / 行内代码。"""
        text.config(state="normal")
        text.delete("1.0", "end")

        lines = content.splitlines()
        i = 0
        seen_version = False
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            if stripped.startswith("# "):
                text.insert("end", stripped[2:].strip() + "\n", "h1")
            elif stripped.startswith("## [") or stripped.startswith("## "):
                title = stripped[2:].strip()
                text.insert("end", f"\n  {title}\n", "version")
                seen_version = True
            elif stripped.startswith("### "):
                text.insert("end", stripped[4:].strip() + "\n", "section")
            elif stripped.startswith("---"):
                text.insert("end", "— — —\n", "hr")
            elif stripped.startswith("- ") or stripped.startswith("* "):
                self._insert_rich_bullet(text, stripped[2:].strip())
            else:
                # 引言/说明段：版本区之前用 muted，之后用正文
                tag = "intro" if not seen_version else "bullet"
                self._insert_rich_line(text, stripped, base_tag=tag)
                text.insert("end", "\n", tag)
            i += 1

        text.insert("end", "\n")

    def _insert_rich_line(self, text, line: str, base_tag: str = "bullet"):
        """插入一行，解析 **粗体** 与 `代码`。"""
        # 按 ** 和 ` 切分
        pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
        pos = 0
        for m in pattern.finditer(line):
            if m.start() > pos:
                text.insert("end", line[pos:m.start()], base_tag)
            token = m.group(0)
            if token.startswith("**") and token.endswith("**"):
                text.insert("end", token[2:-2], (base_tag, "bold"))
            elif token.startswith("`") and token.endswith("`"):
                text.insert("end", token[1:-1], (base_tag, "code"))
            pos = m.end()
        if pos < len(line):
            text.insert("end", line[pos:], base_tag)

    def _insert_rich_bullet(self, text, body: str):
        text.insert("end", "•  ", "bullet")
        self._insert_rich_line(text, body, base_tag="bullet")
        text.insert("end", "\n", "bullet")

    def _close(self):
        win, self.win = self.win, None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

# ---------------------------------------------------------------------------
# 托盘程序主逻辑
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cookie 自动同步监听（Edge 扩展 → 127.0.0.1）
# ---------------------------------------------------------------------------
AUTOSYNC_PATH = str(PROJECT_ROOT / "cookie_autosync.txt")
_MAX_COOKIE_BODY = 64 * 1024
_REQUIRED_COOKIE_NAMES = {"api-platform_serviceToken", "userId"}


def _parse_cookie_names(cookie: str) -> set[str]:
    """从 'a=1; b=2' 中提取 cookie 名集合（不保留值）。"""
    names = set()
    for part in cookie.split(";"):
        if "=" in part:
            names.add(part.split("=", 1)[0].strip())
    return names


def _write_autosync(content: str) -> bool:
    """原子写入 cookie_autosync.txt；内容无变化返回 False。"""
    try:
        with open(AUTOSYNC_PATH, "r", encoding="utf-8") as f:
            if f.read().strip() == content:
                return False
    except OSError:
        pass
    tmp = AUTOSYNC_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, AUTOSYNC_PATH)
    return True


class _AutosyncHandler(BaseHTTPRequestHandler):
    """接收 Edge 扩展的 Cookie 推送。

    安全约束：仅绑定 127.0.0.1；Origin 必须缺省（本机工具）或
    chrome-extension://（浏览器扩展），其余一律 403；请求体 ≤64KB；
    必须含必需 Cookie 名才落盘。日志绝不打印 Cookie 内容。
    """
    on_cookie = None  # 由监听线程注入: fn(new_content: str) -> None

    def log_message(self, fmt, *args):
        """静默默认访问日志（避免刷屏/泄漏）。"""

    def _reply(self, code: int, msg: str):
        try:
            body = msg.encode("utf-8")
            origin = self.headers.get("Origin") or ""
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if origin.startswith("chrome-extension://"):
                # 扩展 fetch 跨源读取，不回 ACAO 扩展侧会 Failed to fetch
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        """CORS 预检（text/plain 简单请求通常不触发，防御性支持）。"""
        origin = self.headers.get("Origin") or ""
        if not origin.startswith("chrome-extension://"):
            self._reply(403, "bad origin")
            return
        try:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()
        except Exception:
            pass

    def do_POST(self):
        if self.path != "/cookie":
            log.warning("同步请求路径错误: %s", self.path)
            self._reply(404, "not found")
            return
        origin = self.headers.get("Origin") or ""
        if origin and not origin.startswith("chrome-extension://"):
            log.warning("同步请求被拒 [origin]: %s", origin)
            self._reply(403, "bad origin")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_COOKIE_BODY:
            log.warning("同步请求被拒 [bad length]: %s", length)
            self._reply(400, "bad length")
            return
        body = self.rfile.read(length).decode("utf-8", "replace").strip()
        if not body:
            log.warning("同步请求被拒 [empty body]")
            self._reply(400, "empty")
            return
        names = _parse_cookie_names(body)
        if not _REQUIRED_COOKIE_NAMES <= names:
            log.warning("同步请求被拒 [missing cookies]: 收到 %d 个, 缺 %s",
                        len(names), sorted(_REQUIRED_COOKIE_NAMES - names))
            self._reply(400, "missing required cookies")
            return
        try:
            changed = _write_autosync(body)
        except OSError as e:
            log.error("写入 cookie_autosync.txt 失败: %s", e)
            self._reply(500, "write failed")
            return
        if changed and self.on_cookie is not None:
            try:
                self.on_cookie(body)
            except Exception:
                log.exception("Cookie 推送回调异常")
        self._reply(200, "ok" if changed else "unchanged")


class TrayMonitor:
    def __init__(self):
        self.state = MonitorState()
        self.icon: pystray.Icon | None = None
        self._running = True
        self._status_text = "初始化中..."
        self._settings_window: SettingsWindow | None = None
        self._changelog_window: ChangelogWindow | None = None
        self._agents: list[dict] = []
        # Token Plan 用量状态
        self._last_gw: str | None = None
        self._last_st: str | None = None
        self._usage_line = "用量: 查询中..."
        self._usage_ok = False
        self._usage_last_err: str | None = None
        self._usage_alerted = False
        self._usage_data: dict | None = None
        self._usage_source = ""
        self._usage_updated_at = ""            # 上次成功查询时间 HH:MM:SS
        self._usage_wake = threading.Event()   # 扩展推送新 Cookie 时唤醒用量线程
        self._usage_sync_server: HTTPServer | None = None
        self._last_left_click = 0.0            # 左键双击判定时间戳

    # --- 图标更新 ---

    def _interruptible_sleep(self, seconds: int):
        """可中断的睡眠，每秒检查 _running 标志。"""
        for _ in range(seconds):
            if not self._running:
                break
            time.sleep(1)

    def _pick_icon(self, gw: str, st: str) -> Image.Image:
        if self.state.paused:
            return build_status_icon(False, False, paused=True)
        gw_ok = (gw == "ok")
        st_ok = (st == "ok")
        return build_status_icon(gw_ok, st_ok)

    def _compose_status_text(self, gw: str | None, st: str | None) -> str:
        if self.state.paused:
            line1 = "⏸ 监控已暂停"
        elif gw is None or st is None:
            line1 = "启动中..."
        else:
            gw_label = {"ok": "正常", "restart": "重启中", "cooldown": "冷却中"}.get(gw, gw)
            st_label = {"ok": "正常", "restart": "重启中", "cooldown": "冷却中"}.get(st, st)
            line1 = f"Gateway: {gw_label} | Syncthing: {st_label}"
        parts = [line1]
        line2 = _format_agents_line(self._agents)
        if line2:
            parts.append(line2)
        if self._usage_line:
            parts.append(self._usage_line)
        return "\n".join(parts)

    def _apply_status(self):
        """按最近一次 gw/st 重建状态文本并刷新托盘（用量线程也走这里）。"""
        self._status_text = self._compose_status_text(self._last_gw, self._last_st)
        if not self.icon:
            return
        with _icon_lock:
            try:
                if self._last_gw is not None:
                    self.icon.icon = self._pick_icon(self._last_gw, self._last_st)
                self.icon.title = self._status_text
                self.icon.update_menu()
            except Exception:
                log.exception("更新托盘图标/菜单失败")

    def _update_icon(self, gw: str, st: str):
        self._last_gw, self._last_st = gw, st
        self._apply_status()

    # --- 监控循环 ---

    def _monitor_loop(self):
        """后台监控线程。"""
        RESTART_WAIT = 60  # 重启后等待秒数
        while self._running:
            try:
                # 暂停时跳过检测，只刷新图标
                if self.state.paused:
                    self._update_icon("paused", "paused")
                    self._interruptible_sleep(CONFIG["check_interval"])
                    continue

                gw = self.state.gateway_check()
                st = self.state.syncthing_check()

                restart_happened = False

                if gw == "restart":
                    log.info("Gateway 未运行，尝试重启...")
                    restart_gateway()
                    restart_happened = True

                if st == "restart":
                    log.info("Syncthing 未运行，尝试启动...")
                    start_syncthing()
                    restart_happened = True

                self._update_icon(gw, st)

                if restart_happened:
                    log.info("重启已发送，等待 %ds 后再检测...", RESTART_WAIT)
                    self._interruptible_sleep(RESTART_WAIT)
                else:
                    self._interruptible_sleep(CONFIG["check_interval"])
            except Exception:
                log.exception("监控循环异常，稍后重试")
                self._interruptible_sleep(max(5, int(CONFIG.get("check_interval", 10))))

    # --- Token Plan 用量 ---

    def _usage_refresh_once(self):
        """查询一次用量并刷新状态行。任何异常都只降级用量行，绝不影响服务监控。"""
        try:
            data, source = query_usage(AUTOSYNC_PATH)
            s = summarize(data)
            new_line = format_status(s)
            changed = ((not self._usage_ok) or (new_line != self._usage_line)
                       or (source != self._usage_source))
            self._usage_source = source
            self._usage_ok = True
            self._usage_last_err = None
            self._usage_data = s
            self._usage_line = new_line
            self._usage_updated_at = time.strftime("%H:%M:%S")

            # 超额提醒：跨过阈值触发一次，降回阈值内后允许再次触发
            threshold = float(CONFIG.get("usage_alert_percent", 0) or 0)
            pct = s["plan_percent"] * 100
            if threshold > 0 and pct >= threshold:
                if not self._usage_alerted:
                    self._usage_alerted = True
                    log.warning("用量已达阈值: %.2f%% (阈值 %s%%)", pct, threshold)
                    self._notify_usage(pct, threshold)
            elif self._usage_alerted and pct < threshold:
                self._usage_alerted = False

            if changed:
                log.info("用量已更新 [%s]: %s", source, new_line)
            self._apply_status()
        except UsageError as e:
            self._usage_ok = False
            label = {"auth": "Cookie失效", "nocookie": "未配置",
                     "net": "查询失败", "http": "查询失败", "shape": "响应异常"}.get(
                         e.kind, "查询失败")
            self._usage_line = f"用量: {label}"
            if e.kind != self._usage_last_err:
                self._usage_last_err = e.kind
                log.warning("用量查询失败 [%s]: %s", e.kind, e)
            self._apply_status()
        except Exception:
            self._usage_ok = False
            self._usage_line = "用量: 查询失败"
            if self._usage_last_err != "unknown":
                self._usage_last_err = "unknown"
                log.exception("用量查询异常")
            self._apply_status()

    def _notify_usage(self, pct: float, threshold: float):
        """阈值提醒弹窗（失败只记日志，不影响运行）。"""
        def _show():
            try:
                import tkinter.messagebox as mb
                root = get_ui_root()
                if root is not None:
                    mb.showwarning(
                        "MiMo 用量提醒",
                        f"Token Plan 套餐用量已达 {pct:.2f}%\n（提醒阈值 {threshold:g}%）",
                        parent=root)
            except Exception:
                log.exception("用量提醒弹窗失败")

        try:
            run_on_ui(_show)
        except Exception:
            log.exception("提交用量提醒失败")

    def _usage_loop(self):
        """后台线程：独立轮询 Token Plan 用量（与 check_interval 解耦，下限 60s 防风控）。
        扩展推送新 Cookie 时经 _usage_wake 立即唤醒，不等下个周期。"""
        while self._running:
            self._usage_wake.clear()  # 刷新前清标志：刷新期间的推送会穿透到 wait
            try:
                self._usage_refresh_once()
            except Exception:
                log.exception("用量循环异常")
            try:
                interval = int(CONFIG.get("usage_interval", 600) or 600)
            except (TypeError, ValueError):
                interval = 600
            if self._running:
                self._usage_wake.wait(timeout=max(60, interval))

    # --- Cookie 自动同步监听（Edge 扩展推送） ---

    def _usage_sync_loop(self):
        """后台线程：127.0.0.1 监听 Edge 扩展推送的 Cookie。启动失败只告警不影响主功能。"""
        try:
            port = int(CONFIG.get("usage_sync_port", 39247) or 0)
        except (TypeError, ValueError):
            port = 39247
        if port <= 0:
            log.info("Cookie 自动同步监听已禁用 (usage_sync_port=0)")
            return
        handler = type("AutosyncHandler", (_AutosyncHandler,),
                       {"on_cookie": self._on_cookie_pushed})
        try:
            server = HTTPServer(("127.0.0.1", port), handler)
        except OSError as e:
            log.warning("Cookie 自动同步监听启动失败 (端口 %d): %s", port, e)
            return
        self._usage_sync_server = server
        log.info("Cookie 自动同步监听已启动: http://127.0.0.1:%d/cookie", port)
        try:
            server.serve_forever(poll_interval=1.0)
        finally:
            server.server_close()

    def _on_cookie_pushed(self, content: str):
        """扩展推送了新 Cookie：记日志并立即唤醒用量查询。"""
        log.info("收到扩展 Cookie 推送 (%d 字节)，立即刷新用量", len(content))
        self._usage_wake.set()

    # --- 菜单 ---

    def _on_left_click(self, icon, item):
        """左键双击打开设置。pystray 在 Windows 只回调 WM_LBUTTONUP（无双击事件），
        500ms 内第二次抬起视为双击，单击不动作。"""
        now = time.monotonic()
        if now - self._last_left_click <= 0.5:
            self._last_left_click = 0.0
            self._menu_settings(icon, item)
        else:
            self._last_left_click = now

    def _menu_settings(self, icon, item):
        """打开设置窗口。"""
        try:
            if self._settings_window is None:
                self._settings_window = SettingsWindow(monitor=self)
            self._settings_window.show()
        except Exception:
            log.exception("打开设置窗失败")

    def _menu_changelog(self, icon, item):
        """打开更新说明窗口。"""
        try:
            if self._changelog_window is None:
                self._changelog_window = ChangelogWindow()
            self._changelog_window.show()
        except Exception:
            log.exception("打开更新说明失败")

    def _menu_toggle_pause(self, icon, item):
        """切换暂停/恢复监控。"""
        is_paused = self.state.toggle_pause()
        if is_paused:
            log.info("用户暂停监控")
            self._update_icon("paused", "paused")
        else:
            log.info("用户恢复监控")
            # 立刻做一次检测并刷新图标，避免恢复后长时间灰点
            try:
                gw = self.state.gateway_check()
                st = self.state.syncthing_check()
                self._update_icon(gw, st)
            except Exception:
                log.exception("恢复监控后刷新状态失败")
                self._update_icon("restart", "restart")

    def _menu_exit(self, icon, item):
        """退出程序。"""
        log.info("用户退出")
        self._running = False
        if self._settings_window:
            self._settings_window._close()
        if self.icon:
            self.icon.stop()

    def _build_menu(self):
        # 菜单只放操作项（状态/用量已移除：见悬停提示与设置窗）；
        # 不可见默认项承接左键 WM_LBUTTONUP → 双击判定开设置
        return pystray.Menu(
            pystray.MenuItem("", self._on_left_click, default=True, visible=False),
            pystray.MenuItem(lambda item: "恢复监控" if self.state.paused else "暂停监控",
                             self._menu_toggle_pause),
            pystray.MenuItem("设置", self._menu_settings),
            pystray.MenuItem(f"更新说明 (v{__version__})", self._menu_changelog),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._menu_exit),
        )

    # --- 启动 ---

    def _agent_refresh_loop(self):
        """后台线程：定期刷新 agent 列表。"""
        # 启动时立即获取一次
        try:
            self._agents = fetch_agents()
            log.info("初始 agent 列表: %d 个", len(self._agents))
        except Exception:
            log.exception("初始 agent 列表获取失败")
        while self._running:
            time.sleep(60)
            try:
                self._agents = fetch_agents()
            except Exception as e:
                log.debug("agent 刷新异常: %s", e)

    def run(self):
        log.info("托盘监控 v%s 启动 (项目根: %s)", __version__, PROJECT_ROOT)
        log.info("检查间隔: %ds | 失败上限: %d | 冷却: %ds | 圆点半径: %dpx",
                 CONFIG["check_interval"], CONFIG["max_fail_count"],
                 CONFIG["cooldown_seconds"], CONFIG["dot_radius"])
        log.info("Syncthing: %s | OpenClaw: %s",
                 CONFIG["syncthing_exe"], CONFIG["openclaw_cmd"])

        # 预启动 UI 线程，避免首次打开设置时再抢建 Tk
        get_ui_root()

        self.icon = pystray.Icon(
            name="tray-monitor",
            icon=ICON_BASE.resize(TRAY_ICON_SIZE, Image.Resampling.LANCZOS),
            title="托盘监控 - 启动中...",
            menu=self._build_menu(),
        )

        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name="monitor")
        monitor_thread.start()

        agent_thread = threading.Thread(target=self._agent_refresh_loop, daemon=True, name="agents")
        agent_thread.start()

        usage_thread = threading.Thread(target=self._usage_loop, daemon=True, name="usage")
        usage_thread.start()

        sync_thread = threading.Thread(target=self._usage_sync_loop, daemon=True, name="usage-sync")
        sync_thread.start()

        self.icon.run()

        # 退出收尾：关闭 Cookie 同步监听
        if self._usage_sync_server is not None:
            try:
                self._usage_sync_server.shutdown()
                self._usage_sync_server.server_close()
            except Exception:
                pass

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    monitor = TrayMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
