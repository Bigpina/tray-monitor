"""
托盘监控程序
监控 OpenClaw Gateway 和 Syncthing 运行状态，异常自动重启。
纯托盘程序，无主窗口。双击 start.vbs 无窗口启动。
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import urllib.error
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

# ---------------------------------------------------------------------------
# 版本号
# ---------------------------------------------------------------------------
__version__ = "4.0.0"

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
    """tkinter 配置窗口。"""

    def __init__(self, on_save_callback=None):
        self.on_save_callback = on_save_callback
        self.win = None

    def show(self):
        """弹出设置窗口（在新线程中运行 tkinter）。"""
        if self.win is not None:
            # 窗口已打开，提到前台
            try:
                self.win.lift()
                self.win.focus_force()
            except Exception:
                pass
            return

        thread = threading.Thread(target=self._run_window, daemon=True)
        thread.start()

    def _run_window(self):
        """在独立线程中运行 tkinter 窗口。"""
        self.win = tk.Tk()
        self.win.title("托盘监控 - 设置")
        self.win.geometry("520x380")
        self.win.resizable(False, False)

        # 让窗口居中
        self.win.update_idletasks()

        cfg = dict(CONFIG)

        # --- Syncthing 路径 ---
        row = 0
        tk.Label(self.win, text="Syncthing 可执行文件:").grid(
            row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        frame_st = tk.Frame(self.win)
        frame_st.grid(row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=2)
        frame_st.columnconfigure(0, weight=1)
        var_st = tk.StringVar(value=cfg.get("syncthing_exe", ""))
        tk.Entry(frame_st, textvariable=var_st, width=50).grid(row=0, column=0, sticky="ew")
        tk.Button(frame_st, text="浏览...", command=lambda: self._browse_file(var_st)).grid(
            row=0, column=1, padx=(5, 0))
        tk.Button(frame_st, text="扫描", command=lambda: self._scan_syncthing(var_st)).grid(
            row=0, column=2, padx=(5, 0))

        # --- OpenClaw 命令路径 ---
        row += 1
        tk.Label(self.win, text="OpenClaw 命令路径:").grid(
            row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        frame_oc = tk.Frame(self.win)
        frame_oc.grid(row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=2)
        frame_oc.columnconfigure(0, weight=1)
        var_oc = tk.StringVar(value=cfg.get("openclaw_cmd", "openclaw"))
        tk.Entry(frame_oc, textvariable=var_oc, width=50).grid(row=0, column=0, sticky="ew")
        tk.Button(frame_oc, text="浏览...", command=lambda: self._browse_file(var_oc)).grid(
            row=0, column=1, padx=(5, 0))

        # --- 检测间隔 ---
        row += 1
        tk.Label(self.win, text="检测间隔（秒）:").grid(
            row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        var_interval = tk.StringVar(value=str(cfg.get("check_interval", 15)))
        tk.Entry(self.win, textvariable=var_interval, width=10).grid(
            row=row, column=1, sticky="w", padx=10, pady=(10, 2))

        # --- 失败次数上限 ---
        row += 1
        tk.Label(self.win, text="失败次数上限:").grid(
            row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        var_maxfail = tk.StringVar(value=str(cfg.get("max_fail_count", 3)))
        tk.Entry(self.win, textvariable=var_maxfail, width=10).grid(
            row=row, column=1, sticky="w", padx=10, pady=(10, 2))

        # --- 冷却时长 ---
        row += 1
        tk.Label(self.win, text="冷却时长（秒）:").grid(
            row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        var_cooldown = tk.StringVar(value=str(cfg.get("cooldown_seconds", 300)))
        tk.Entry(self.win, textvariable=var_cooldown, width=10).grid(
            row=row, column=1, sticky="w", padx=10, pady=(10, 2))

        # --- 日志级别 ---
        row += 1
        tk.Label(self.win, text="日志级别:").grid(
            row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        var_loglevel = tk.StringVar(value=cfg.get("log_level", "INFO"))
        combo = ttk.Combobox(self.win, textvariable=var_loglevel, values=[
            "DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", width=10)
        combo.grid(row=row, column=1, sticky="w", padx=10, pady=(10, 2))

        # --- 按钮 ---
        row += 1
        btn_frame = tk.Frame(self.win)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=(20, 10))

        tk.Button(btn_frame, text="保存", width=10, command=lambda: self._save(
            var_st, var_oc, var_interval, var_maxfail, var_cooldown, var_loglevel
        )).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", width=10, command=self._cancel).pack(side="left", padx=5)
        tk.Button(btn_frame, text="恢复默认", width=10, command=lambda: self._restore_defaults(
            var_st, var_oc, var_interval, var_maxfail, var_cooldown, var_loglevel
        )).pack(side="left", padx=5)

        # 关闭窗口时清理引用
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.mainloop()

    def _browse_file(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            title="选择可执行文件",
            filetypes=[("可执行文件", "*.exe;*.cmd;*.bat;*.ps1"), ("所有文件", "*.*")])
        if path:
            var.set(path)


    def _scan_syncthing(self, var: tk.StringVar):
        """扫描常见路径查找 syncthing.exe，找到后弹出确认窗口。"""
        candidates = _find_syncthing_candidates()

        if not candidates:
            messagebox.showinfo("扫描结果", "未找到 syncthing.exe。\n请确认已安装 Syncthing，或使用「浏览」手动选择。")
            return

        if len(candidates) == 1:
            if messagebox.askyesno("扫描结果", f"找到 Syncthing：\n{candidates[0]}\n\n是否使用此路径？"):
                var.set(candidates[0])
            return

        # 多个结果，弹出选择窗口
        self._show_scan_result(candidates, var)

    def _show_scan_result(self, candidates: list[str], var: tk.StringVar):
        """弹出扫描结果选择窗口。"""
        win = tk.Toplevel(self.win)
        win.title("扫描结果 - 选择 Syncthing")
        win.geometry("520x300")
        win.resizable(False, False)
        win.transient(self.win)
        win.grab_set()

        tk.Label(win, text=f"找到 {len(candidates)} 个 Syncthing，请选择：").pack(
            anchor="w", padx=10, pady=(10, 5))

        listbox = tk.Listbox(win, height=8, font=("Consolas", 9))
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

    def _save(self, var_st, var_oc, var_interval, var_maxfail, var_cooldown, var_loglevel):
        """验证并保存配置。"""
        try:
            interval = int(var_interval.get())
            maxfail = int(var_maxfail.get())
            cooldown = int(var_cooldown.get())
            if interval < 1 or maxfail < 1 or cooldown < 1:
                raise ValueError("数值必须 >= 1")
        except ValueError as e:
            messagebox.showerror("参数错误", f"请输入有效的正整数。\n{e}")
            return

        new_cfg = {
            "syncthing_exe": var_st.get().strip(),
            "openclaw_cmd": var_oc.get().strip() or "openclaw",
            "node_exe": CONFIG.get("node_exe", ""),
            "openclaw_mjs": CONFIG.get("openclaw_mjs", ""),
            "check_interval": interval,
            "max_fail_count": maxfail,
            "cooldown_seconds": cooldown,
            "dot_radius": CONFIG.get("dot_radius", 12),
            "log_level": var_loglevel.get(),
            "gateway_url": CONFIG.get("gateway_url", ""),
            "gateway_token_file": CONFIG.get("gateway_token_file", ""),
        }

        # 保存到文件
        save_config(new_cfg)

        # 热更新运行时配置
        CONFIG.clear()
        CONFIG.update(new_cfg)

        # 更新模块级变量
        global CHECK_INTERVAL, MAX_FAIL_COUNT, COOLDOWN_SECONDS, DOT_RADIUS, COMPOSITE_DOT_RADIUS
        CHECK_INTERVAL = interval
        MAX_FAIL_COUNT = maxfail
        COOLDOWN_SECONDS = cooldown
        DOT_RADIUS = new_cfg.get("dot_radius", 16)
        COMPOSITE_DOT_RADIUS = new_cfg.get("dot_radius", 16)

        # 更新日志级别
        logging.getLogger("tray-monitor").setLevel(
            getattr(logging, new_cfg["log_level"].upper(), logging.INFO))

        log.info("配置已保存并生效")

        if self.on_save_callback:
            self.on_save_callback()

        self._close()

    def _cancel(self):
        self._close()

    def _restore_defaults(self, var_st, var_oc, var_interval, var_maxfail, var_cooldown, var_loglevel):
        var_st.set(DEFAULT_CONFIG["syncthing_exe"])
        var_oc.set(DEFAULT_CONFIG["openclaw_cmd"])
        var_interval.set(str(DEFAULT_CONFIG["check_interval"]))
        var_maxfail.set(str(DEFAULT_CONFIG["max_fail_count"]))
        var_cooldown.set(str(DEFAULT_CONFIG["cooldown_seconds"]))
        var_loglevel.set(DEFAULT_CONFIG["log_level"])

    def _close(self):
        if self.win is not None:
            try:
                self.win.quit()
                self.win.destroy()
            except Exception:
                pass
            self.win = None

# ---------------------------------------------------------------------------
# 更新说明窗口
# ---------------------------------------------------------------------------

class ChangelogWindow:
    """显示版本更新说明的窗口。"""

    def __init__(self):
        self.win = None

    def show(self):
        if self.win is not None:
            try:
                self.win.lift()
                self.win.focus_force()
            except Exception:
                pass
            return
        thread = threading.Thread(target=self._run_window, daemon=True)
        thread.start()

    def _run_window(self):
        self.win = tk.Tk()
        self.win.title(f"更新说明 - 托盘监控 v{__version__}")
        self.win.geometry("560x480")
        self.win.resizable(True, True)
        self.win.minsize(400, 300)

        # 顶部版本信息
        header = tk.Frame(self.win)
        header.pack(fill="x", padx=10, pady=(10, 5))
        tk.Label(header, text=f"托盘监控 v{__version__}",
                 font=("Microsoft YaHei", 14, "bold")).pack(side="left")

        # 文本区域
        text_frame = tk.Frame(self.win)
        text_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        text_widget = tk.Text(text_frame, wrap="word", font=("Consolas", 10),
                              yscrollcommand=scrollbar.set, state="disabled",
                              bg="#fafafa", padx=8, pady=8)
        text_widget.pack(fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)

        # 加载并渲染 CHANGELOG.md
        content = self._load_changelog()
        text_widget.config(state="normal")
        text_widget.insert("1.0", content)
        # 简单样式：版本号加粗
        text_widget.tag_configure("version", font=("Consolas", 11, "bold"))
        text_widget.tag_configure("section", font=("Consolas", 10, "bold"))
        self._apply_tags(text_widget)
        text_widget.config(state="disabled")

        # 关闭按钮
        btn_frame = tk.Frame(self.win)
        btn_frame.pack(pady=(0, 10))
        tk.Button(btn_frame, text="关闭", width=10,
                  command=self._close).pack()

        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.mainloop()

    def _load_changelog(self) -> str:
        if CHANGELOG_PATH.exists():
            try:
                return CHANGELOG_PATH.read_text(encoding="utf-8")
            except Exception as e:
                return f"读取 CHANGELOG.md 失败: {e}"
        return "未找到 CHANGELOG.md 文件。"

    def _apply_tags(self, text_widget: tk.Text):
        """给版本号标题和小节标题加样式。"""
        content = text_widget.get("1.0", "end")
        for match in re.finditer(r"^(## \[.+?\].*)$", content, re.MULTILINE):
            start_idx = f"1.0+{match.start()}c"
            end_idx = f"1.0+{match.end()}c"
            text_widget.tag_add("version", start_idx, end_idx)
        for match in re.finditer(r"^(### .+)$", content, re.MULTILINE):
            start_idx = f"1.0+{match.start()}c"
            end_idx = f"1.0+{match.end()}c"
            text_widget.tag_add("section", start_idx, end_idx)

    def _close(self):
        if self.win is not None:
            try:
                self.win.quit()
                self.win.destroy()
            except Exception:
                pass
            self.win = None

# ---------------------------------------------------------------------------
# 托盘程序主逻辑
# ---------------------------------------------------------------------------

class TrayMonitor:
    def __init__(self):
        self.state = MonitorState()
        self.icon: pystray.Icon | None = None
        self._running = True
        self._status_text = "初始化中..."
        self._settings_window: SettingsWindow | None = None
        self._changelog_window: ChangelogWindow | None = None
        self._agents: list[dict] = []

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

    def _update_icon(self, gw: str, st: str):
        if self.state.paused:
            line1 = "⏸ 监控已暂停"
        else:
            gw_label = {"ok": "正常", "restart": "重启中", "cooldown": "冷却中"}.get(gw, gw)
            st_label = {"ok": "正常", "restart": "重启中", "cooldown": "冷却中"}.get(st, st)
            line1 = f"Gateway: {gw_label} | Syncthing: {st_label}"
        line2 = _format_agents_line(self._agents)
        self._status_text = line1 + ("\n" + line2 if line2 else "")
        if self.icon:
            self.icon.icon = self._pick_icon(gw, st)
            self.icon.title = self._status_text
            try:
                self.icon.update_menu()
            except Exception:
                pass

    # --- 监控循环 ---

    def _monitor_loop(self):
        """后台监控线程。"""
        RESTART_WAIT = 60  # 重启后等待秒数
        while self._running:
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

    # --- 菜单 ---

    def _menu_status(self, icon, item):
        """显示当前状态。"""
        log.info("状态: %s", self._status_text)

    def _menu_settings(self, icon, item):
        """打开设置窗口。"""
        if self._settings_window is None:
            self._settings_window = SettingsWindow()
        self._settings_window.show()

    def _menu_changelog(self, icon, item):
        """打开更新说明窗口。"""
        if self._changelog_window is None:
            self._changelog_window = ChangelogWindow()
        self._changelog_window.show()

    def _menu_toggle_pause(self, icon, item):
        """切换暂停/恢复监控。"""
        is_paused = self.state.toggle_pause()
        if is_paused:
            log.info("用户暂停监控")
            self._update_icon("paused", "paused")
        else:
            log.info("用户恢复监控")

    def _menu_exit(self, icon, item):
        """退出程序。"""
        log.info("用户退出")
        self._running = False
        if self._settings_window:
            self._settings_window._close()
        if self.icon:
            self.icon.stop()

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda item: self._status_text, self._menu_status, default=True),
            pystray.Menu.SEPARATOR,
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
        self._agents = fetch_agents()
        log.info("初始 agent 列表: %d 个", len(self._agents))
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

        self.icon = pystray.Icon(
            name="tray-monitor",
            icon=ICON_BASE.resize(TRAY_ICON_SIZE, Image.Resampling.LANCZOS),
            title="托盘监控 - 启动中...",
            menu=self._build_menu(),
        )

        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()

        agent_thread = threading.Thread(target=self._agent_refresh_loop, daemon=True)
        agent_thread.start()

        self.icon.run()

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    monitor = TrayMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
