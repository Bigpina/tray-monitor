# 托盘监控程序 v4

监控 OpenClaw Gateway 和 Syncthing 运行状态的 Windows 托盘程序。异常时自动重启，纯后台运行，无主窗口。

## 功能

- 🟢 **绿灯**：Gateway 正常
- 🔵 **蓝灯**：Syncthing 正常
- 🔴 **两灯都不亮**：均异常
- ⚪ **冷却中**：连续失败后暂停重启
- ⏸ **暂停监控**：手动暂停检测和重启
- 🔄 **自动重启**：检测到进程退出后自动拉起（通过系统服务）
- 🛡️ **失败保护**：连续失败 N 次后冷却，避免无限重启
- 📈 **Token Plan 用量**：设置窗口显示本月用量百分比与 token 用量（托盘悬停提示同步显示），超额提醒（默认 90% 触发日志+弹窗）
- 🍪 **Cookie 自动同步**：Edge 扩展定时/登录态变化时推送 Cookie，浏览器重登或轮换后托盘自动跟上，无需手工复制
- 🖱️ **左键双击**：双击托盘图标打开设置；右键菜单精简为纯操作项（状态/用量见悬停提示与设置窗）
- 📋 **更新说明**：右键菜单查看版本变更历史

## 文件结构

```
tray-monitor/
├── src/
│   ├── tray_monitor.py          # 主程序
│   └── usage_client.py          # Token Plan 用量查询（独立可测）
├── edge-extension/              # Edge 扩展：Cookie 自动同步推送
│   ├── manifest.json
│   ├── background.js            # 定时/登录态变化时推送 Cookie
│   └── popup.html / popup.js    # 状态弹窗
├── icons/
│   ├── lobster.ico              # 托盘图标
│   └── lobster.png
├── scripts/
│   └── gen_icon.py              # 图标生成脚本（开发用）
├── config.example.json          # 配置模板（首次使用复制为 config.json）
├── CHANGELOG.md                 # 版本变更日志
├── check_version.py             # 版本管理检查工具
├── build.bat                    # 一键构建脚本
├── start.vbs                    # 双击无窗口启动
├── start.bat                    # 双击带控制台启动（调试用）
├── setup.bat                    # 一键安装依赖
├── requirements.txt             # Python 依赖
└── README.md
```

## 安装

### 前置条件

- Python 3.8+（需在 PATH 中）
- pip

### 一键安装

双击运行 `setup.bat`，或手动执行：

```bash
pip install -r requirements.txt
```

## 配置

首次使用，复制配置模板并按需修改：

```bash
copy config.example.json config.json
```

或直接启动程序后，通过右键菜单 → **设置** 进行可视化配置。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| Syncthing 可执行文件 | syncthing.exe 的完整路径 | 自动扫描 |
| OpenClaw 命令路径 | openclaw 命令或完整路径 | `openclaw` |
| 检测间隔（秒） | 多久检查一次服务状态 | `10` |
| 失败次数上限 | 连续失败几次后进入冷却 | `3` |
| 冷却时长（秒） | 冷却期持续多久 | `120` |
| 日志级别 | DEBUG / INFO / WARNING / ERROR | `INFO` |
| Gateway URL | Gateway HTTP 地址 | `http://127.0.0.1:18789` |
| Gateway Token 文件 | openclaw.json 路径 | 自动检测 |
| Cookie 文件 | MiMo 用量接口的登录 Cookie 存放文件 | 程序目录 cookie.txt（可配） |
| 用量查询间隔（秒） | 多久查一次 Token Plan 用量（≥60） | `600` |
| 超额提醒阈值（%） | 用量达到该百分比时提醒，0=关闭 | `90` |
| 同步监听端口 | 扩展推送 Cookie 的本地端口，0=关闭 | `39247` |

## Cookie 自动同步（Edge 扩展，推荐）

手动复制的 Cookie 会过期，推荐安装配套扩展实现全自动同步：

1. Edge 打开 `edge://extensions/`，开启「开发人员模式」
2. 点「加载解压缩的扩展」，选择本仓库的 `edge-extension/` 文件夹
3. 确保已在 Edge 登录 [platform.xiaomimimo.com](https://platform.xiaomimimo.com/console/plan-manage)
4. 扩展每分钟（及登录态变化时防抖 2s 后）把 Cookie POST 到 `http://127.0.0.1:39247/cookie`，
   托盘写入 `cookie_autosync.txt` 并立即刷新用量

查询优先级：**扩展推送（cookie_autosync.txt）> 配置的 cookie.txt**，前者 401 自动回退后者。
不想用时在 config.json 设 `"usage_sync_port": 0` 关闭监听。

安全约束：监听仅绑定 127.0.0.1；校验 Origin（仅 `chrome-extension://` 或缺省，其余 403）；
请求体 ≤64KB；必须含必需 Cookie 名才落盘；日志绝不打印 Cookie 内容。

## 启动

### 无窗口启动（推荐）

双击 `start.vbs`，程序在后台静默运行，仅显示托盘图标。

### 带控制台启动（调试）

双击 `start.bat`，可以看到日志输出。

### 命令行启动

```bash
python src\tray_monitor.py
```

## 托盘菜单

右键托盘图标：

- **状态信息**：显示 Gateway / Syncthing / Agent 状态
- **暂停监控 / 恢复监控**：手动暂停/恢复自动检测
- **设置**：可视化修改配置（保存后立即生效）
- **更新说明 (v4.x.x)**：查看版本变更历史
- **退出**

## 构建 exe

```bash
build.bat
```

产物输出到 `release/v4.0.0/`，包含 exe、配置模板、文档。

## 版本管理

```bash
python check_version.py    # 检查版本一致性
git tag                    # 查看所有版本标签
git log --oneline          # 查看提交历史
```

## 技术说明

- **Gateway 检测**：HTTP health 端点 → CLI 命令 → 进程扫描，三级降级
- **Gateway 管理**：通过 `openclaw gateway start/restart` 管理系统服务
- **Syncthing 检测**：`psutil` 遍历进程列表匹配进程名
- **图标**：基础图标 + 右下角状态圆点叠加（绿/蓝/灰）
- **线程模型**：主线程运行托盘事件循环，后台守护线程执行监控
- **配置窗口**：tkinter（Python 内置），在独立线程中运行
- **用量查询**：标准库 urllib 直调控制台用量接口（Cookie 文件鉴权），独立守护线程轮询，与服务监控完全隔离，失败只降级显示不干扰监控
- **Cookie 自动同步**：内置 127.0.0.1 HTTP 监听接收 Edge 扩展推送，Origin 校验 + 必需 Cookie 名校验，原子落盘，Event 唤醒用量线程即时刷新
