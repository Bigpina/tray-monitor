# 托盘监控程序 v4

监控 OpenClaw Gateway 和 Syncthing 运行状态的 Windows 托盘程序。异常时自动重启，纯后台运行，无主窗口。

## 新功能（v4）

- 📋 **更新说明**：右键菜单 → 更新说明，查看各版本变更历史
- 🔢 **版本管理**：语义化版本号（SemVer），代码内 `__version__` + `CHANGELOG.md`

## 历史功能（v3）

- ⚙️ **设置窗口**：右键菜单 → 设置，可视化修改所有配置
- 🚀 **双击启动**：`start.vbs` 无窗口启动，`start.bat` 带控制台调试
- 🔧 **直接调用**：不再依赖 VBS 脚本，Python 直接调用 exe/命令
- 🔥 **热更新**：保存配置后立即生效，无需重启

## 功能

- 🟢 **绿灯**：Gateway 正常
- 🔵 **蓝灯**：Syncthing 正常
- 🔴 **两灯都不亮**：均异常
- ⚪ **冷却中**：连续失败后暂停重启
- 🔄 **自动重启**：检测到进程退出后自动拉起
- 🛡️ **失败保护**：连续失败 N 次后冷却，避免无限重启

## 文件结构

```
tray-monitor/
├── icons/
│   ├── lobster.ico              # 托盘图标
│   └── lobster.png
├── src/
│   └── tray_monitor.py          # 主程序
├── config.json                  # 配置文件（可通过设置窗口修改）
├── start.vbs                    # 双击无窗口启动
├── start.bat                    # 双击带控制台启动（调试用）
├── requirements.txt             # Python 依赖
├── setup.bat                    # 一键安装依赖
└── README.md
```

## 安装

### 前置条件

- Python 3.8+
- pip

### 一键安装

双击运行 `setup.bat`，或手动执行：

```bash
pip install -r requirements.txt
```

## 启动

### 无窗口启动（推荐）

双击 `start.vbs`，程序在后台静默运行，仅显示托盘图标。

### 带控制台启动（调试）

双击 `start.bat`，可以看到日志输出。

### 命令行启动

```bash
python src\tray_monitor.py
```

## 配置

### 通过设置窗口（推荐）

右键托盘图标 → **设置**，可修改：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| Syncthing 可执行文件 | syncthing.exe 的完整路径 | `D:\APP\syncthing-windows-amd64-v2.1.0\syncthing.exe` |
| OpenClaw 命令路径 | openclaw 命令或完整路径 | `openclaw` |
| Node.js 路径 | node.exe 完整路径（优先于 openclaw_cmd） | 自动检测 |
| OpenClaw mjs 路径 | openclaw.mjs 完整路径 | 自动检测 |
| 检测间隔（秒） | 多久检查一次服务状态 | `5` |
| 失败次数上限 | 连续失败几次后进入冷却 | `3` |
| 冷却时长（秒） | 冷却期持续多久 | `60` |
| 日志级别 | DEBUG / INFO / WARNING / ERROR | `INFO` |
| Gateway URL | Gateway HTTP 地址 | `http://127.0.0.1:18789` |
| Gateway Token 文件 | openclaw.json 路径，用于读取认证 token | `~/.openclaw/openclaw.json` |

**保存后立即生效，无需重启程序。**

### 手动编辑 config.json

```json
{
  "syncthing_exe": "D:\\APP\\syncthing-windows-amd64-v2.1.0\\syncthing.exe",
  "openclaw_cmd": "openclaw",
  "node_exe": "C:\\Users\\...\\node.exe",
  "openclaw_mjs": "C:\\Users\\...\\openclaw.mjs",
  "check_interval": 5,
  "max_fail_count": 3,
  "cooldown_seconds": 60,
  "dot_radius": 16,
  "log_level": "INFO",
  "gateway_url": "http://127.0.0.1:18789",
  "gateway_token_file": "C:\\Users\\...\\.openclaw\\openclaw.json"
}
```

## 开机自启（可选）

将 `start.vbs` 的快捷方式放入启动文件夹：

```
Win+R → shell:startup
```

## 技术说明

- **检测方式**：通过 `psutil` 遍历进程列表，匹配进程名
- **重启方式**：Python 直接调用 subprocess（`CREATE_NO_WINDOW` 无窗口）
- **图标**：基础图标 `lobster.ico` + 右下角状态圆点叠加
- **线程模型**：主线程运行托盘事件循环，后台守护线程执行监控
- **配置窗口**：tkinter（Python 内置），在独立线程中运行
