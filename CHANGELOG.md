# 更新日志

所有版本的变更说明。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [4.3.3] - 2026-09-24

### 变更
- **移除 cookie.txt 兜底**：用量查询 Cookie 唯一来源改为 Edge 扩展推送的 cookie_autosync.txt——兜底文件在新设备上不存在、内容也大概率已 401，回退无意义。删除 `usage_cookie_file` 配置字段与设置窗「Cookie 文件」输入（说明改为「Cookie 由 Edge 扩展自动推送，无需手动配置」）；扩展未推送时用量行降级并提示安装/登录扩展，不再回退配置文件

## [4.3.2] - 2026-09-24

### 变更
- **右键菜单精简**：移除顶部状态/用量多行文本（菜单过长），仅保留操作项：暂停监控 / 设置 / 更新说明 / 退出；状态与用量改由悬停提示与设置窗展示
- **设置窗新增当前用量**：Token Plan 分组顶部实时显示「用量 · 来源 · 更新时间」，窗口打开期间每 5 秒自动同步托盘运行状态（窗口高度 770→800）
- **左键双击开设置**：不可见默认项承接 WM_LBUTTONUP + 500ms 去抖（pystray 在 Windows 无双击事件，双击=两次 UP）；单击无动作，双击打开设置窗；新增 `scripts/test_menu_default.py` 锁定该机制

## [4.3.1] - 2026-09-24

### 改进
- **用量行简化**：去掉「套餐xx.xx%」显示，改为「用量: 本月74.96% (28.48B/38.00B)」——接口的套餐 percent 为整数粒度（74.00/75.00）、与本月几乎重复，token 用量括号本就与本月百分比对应；超额提醒仍按原字段计算，行为不变

## [4.3.0] - 2026-09-24

### 新增
- **Cookie 自动同步**：配套 Edge 扩展（`edge-extension/`）自动把 `platform.xiaomimimo.com` 登录态推送给托盘内置的 127.0.0.1 监听（`usage_sync_port`，默认 39247）；浏览器登录/轮换 Cookie 后托盘自动跟上，无需手工复制 cookie.txt
- 查询优先级：扩展推送（cookie_autosync.txt）> 配置的 cookie.txt，前者 401 自动回退后者；推送新 Cookie 经 Event 唤醒立即刷新用量（不等下个轮询周期）
- 扩展弹窗显示推送状态/错误/手动同步按钮
- **双通路取 Cookie**：cookies API 4 过滤并集 + `webRequest` 捕获页面请求头（本机 Edge 实测 getAll 时而返回空，捕获通路兕底）；扩展 fetch 跨源响应补 CORS（ACAO + OPTIONS 预检）；监听拒收分支记 WARNING（仅原因与 cookie 名，不记值）

### 安全
- 监听仅绑定 127.0.0.1；校验 Origin（缺省或 chrome-extension://，其余 403）；请求体上限 64KB；必须含 `api-platform_serviceToken` + `userId` 才落盘；日志绝不打印 Cookie 内容
- `cookie_autosync.txt`（凭证）已加入 .gitignore

## [4.2.0] - 2026-09-24

### 新增
- **Token Plan 用量显示**：托盘悬停/状态行新增「用量: 套餐74.00% 本月73.81% (28.05B/38.00B)」，独立后台线程查询，间隔与服务监控解耦（默认 600s，下限 60s 防接口风控）
- 用量接口调用 `platform.xiaomimimo.com/api/v1/tokenPlan/usage`（小米账号 Cookie 鉴权，非 tp- API Key）；401/网络异常仅显示「Cookie失效/未配置/查询失败」，不影响 Gateway/Syncthing 监控
- 设置窗口新增「Token Plan 用量」分组：Cookie 文件路径（浏览）、查询间隔、超额提醒阈值（默认 90%，触发日志警告+弹窗提醒，用量回落阈值内后可再次触发）
- 新增本地模块 `src/usage_client.py`（与主程序解耦，可独立测试），配套 `scripts/test_usage_client.py`

## [4.1.0] - 2026-09-18

### 改进
- **设置窗口 UI 重构**：新增设计系统（配色/字体常量），用 ttk.LabelFrame 分组（当前状态、服务路径、监控策略、日志、高级设置），整体风格更现代
- **更新说明窗口 UI 重构**：卡片式布局，版本徽标，富文本标签着色，视觉层次更清晰
- 设置窗口显示当前 Gateway/Syncthing 状态指示灯

## [4.0.0] - 2026-09-14

### 新增
- 版本管理系统：代码内 `__version__` 常量 + `CHANGELOG.md`
- 托盘菜单「更新说明」：点击可查看各版本变更历史
- **暂停监控**：右键菜单「暂停监控 / 恢复监控」，暂停后停止自动检测和重启，图标变灰

### 改进
- **Gateway 启动方式改为官方推荐**：使用 `openclaw gateway start` / `restart` 管理系统服务，不再直接 `gateway run`；已运行时安全重启（排空工作），未运行时启动服务
