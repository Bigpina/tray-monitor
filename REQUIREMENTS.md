# 托盘监控程序 - 需求文档 v4

## 项目路径
`D:\openclaw\alpha\tray-monitor\`

## 文件结构
```
tray-monitor/
├── icons/
│   ├── lobster.ico
│   └── lobster.png
├── src/
│   └── tray_monitor.py          # 主程序（含设置窗口）
├── config.json                   # 配置文件（热更新）
├── start.vbs                     # 双击无窗口启动
├── start.bat                     # 双击带控制台启动
├── requirements.txt
├── setup.bat
└── README.md
```

## v3 改进

### 1. 双击启动
- `start.vbs`：使用 pythonw.exe 无窗口启动，相对路径可移植
- `start.bat`：带控制台启动，用于调试

### 2. 设置窗口
- 右键托盘菜单添加"设置"选项
- 使用 tkinter（Python 内置）
- 配置项：Syncthing 路径、OpenClaw 路径、检测间隔、失败上限、冷却时长、日志级别
- 路径输入框旁有"浏览"按钮（filedialog）
- "保存"写入 config.json 并立即生效
- "取消"关闭不保存
- "恢复默认"重置为默认值

### 3. 去掉 VBS 脚本依赖
- Python 直接用 subprocess 调用 exe/命令
- CREATE_NO_WINDOW 标志实现无窗口
- 配置中的 syncthing_exe 和 openclaw_cmd 可通过设置窗口修改

### 4. 配置热更新
- 保存配置后立即更新运行时变量
- 无需重启程序

## 配置文件 config.json
```json
{
  "syncthing_exe": "D:\\APP\\syncthing-windows-amd64-v2.1.0\\syncthing.exe",
  "openclaw_cmd": "openclaw",
  "check_interval": 15,
  "max_fail_count": 3,
  "cooldown_seconds": 300,
  "dot_radius": 12,
  "log_level": "INFO"
}
```

## 依赖
- Python 3.8+
- pystray>=0.19
- Pillow>=9.0
- psutil>=5.9
- tkinter（Python 内置）
