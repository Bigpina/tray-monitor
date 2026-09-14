"""tray-monitor 构建脚本
用法: python build.py [--open]
"""
import os
import re
import shutil
import subprocess
import sys

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)

# 读取版本号
with open(os.path.join("src", "tray_monitor.py"), encoding="utf-8-sig") as f:
    m = re.search(r'__version__\s*=\s*"(.+?)"', f.read())
if not m:
    print("[ERROR] 无法读取版本号")
    sys.exit(1)
VERSION = m.group(1)
print(f"\n{'='*50}")
print(f"  构建托盘监控 v{VERSION}")
print(f"{'='*50}\n")

# 清理旧构建
for d in ["build", "dist"]:
    if os.path.exists(d):
        shutil.rmtree(d)
        print(f"  清理 {d}/")

# 创建发布目录
release_dir = os.path.join("release", f"v{VERSION}")
os.makedirs(release_dir, exist_ok=True)

# PyInstaller 打包
print("[1/2] PyInstaller 打包中...")
ret = subprocess.run([
    "pyinstaller",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "tray_monitor",
    "--icon", "icons/lobster.ico",
    "--add-data", "icons;icons",
    "src/tray_monitor.py",
])
if ret.returncode != 0:
    print("[ERROR] PyInstaller 打包失败")
    sys.exit(1)

# 复制到发布目录
print(f"\n[2/2] 复制到 {release_dir}...")
shutil.copy2("dist/tray_monitor.exe", f"{release_dir}/tray_monitor.exe")
print(f"  tray_monitor.exe")

# 复制配置文件和文档
for src_file, required in [("config.json", False), ("config.example.json", False),
                            ("CHANGELOG.md", True), ("README.md", True),
                            ("start.vbs", False), ("start.bat", False)]:
    if os.path.exists(src_file):
        shutil.copy2(src_file, f"{release_dir}/{src_file}")
        print(f"  {src_file}")

# 清理构建临时文件
for d in ["build", "dist"]:
    if os.path.exists(d):
        shutil.rmtree(d)

# 生成的 spec 文件
if os.path.exists("tray_monitor.spec"):
    os.remove("tray_monitor.spec")

print(f"\n{'='*50}")
print(f"  构建完成!")
print(f"  输出: {release_dir}/tray_monitor.exe")
print(f"  版本: v{VERSION}")
print(f"{'='*50}\n")

if "--open" in sys.argv:
    os.startfile(release_dir)
