# 更新日志

所有版本的变更说明。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

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
