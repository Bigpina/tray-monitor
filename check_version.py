"""版本管理检查脚本"""
import re
import subprocess
import os
import sys

# 修复 Windows 控制台编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PROJ = os.path.dirname(os.path.abspath(__file__))

print("=" * 50)
print("  tray-monitor 版本管理检查报告")
print("=" * 50)

# 1. 代码版本号
with open(os.path.join(PROJ, "src", "tray_monitor.py"), encoding="utf-8-sig") as f:
    src = f.read()
m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
code_ver = m.group(1) if m else "未找到"
print(f"\n[1] 代码版本号:     v{code_ver}")

# 2. CHANGELOG 版本
with open(os.path.join(PROJ, "CHANGELOG.md"), encoding="utf-8") as f:
    cl = f.read()
versions = re.findall(r"## \[(.+?)\]", cl)
cl_ver = versions[0] if versions else "未找到"
print(f"[2] CHANGELOG 版本: v{cl_ver}")

# 3. Git 标签
tags = subprocess.check_output(["git", "tag", "-l"], cwd=PROJ).decode().strip()
tag_list = [t for t in tags.split("\n") if t] if tags else []
print(f"[3] Git 标签:       {', '.join(tag_list) if tag_list else '无'}")

# 4. Git 提交历史
log = subprocess.check_output(["git", "log", "--oneline", "--decorate"], cwd=PROJ).decode().strip()
print(f"\n[4] Git 提交历史:")
for line in log.split("\n"):
    print(f"    {line}")

# 5. 一致性检查
print(f"\n[5] 一致性检查:")
tag_ver = tag_list[-1].replace("v", "") if tag_list else "N/A"
all_match = code_ver == cl_ver == tag_ver
print(f"    代码: v{code_ver}")
print(f"    CHANGELOG: v{cl_ver}")
print(f"    Git标签: {tag_list[-1] if tag_list else 'N/A'}")
print(f"    => {'✅ 三者一致' if all_match else '❌ 不一致'}")

# 6. 工作区状态
status = subprocess.check_output(["git", "status", "--short"], cwd=PROJ).decode().strip()
print(f"\n[6] 工作区状态: {'✅ 干净' if not status else '⚠️ 有未提交的改动:'}")
if status:
    for line in status.split("\n"):
        print(f"    {line}")

# 7. 构建产物检查
release_dir = os.path.join(PROJ, "release", f"v{code_ver}")
exe_path = os.path.join(release_dir, "tray_monitor.exe")
print(f"\n[7] 构建产物: {'✅ ' + exe_path if os.path.exists(exe_path) else '❌ 未构建 (运行 build.bat)'}")

print("\n" + "=" * 50)
