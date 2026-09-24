"""pystray 菜单机制测试：不可见默认项承接左键触发 + 右键渲染过滤。

背景（v4.3.2 设计依据，2026-09-24 实测 pystray 6.x / Windows）：
- 左键 WM_LBUTTONUP → Icon.__call__ → Menu.__call__ → 第一个 default=True 项
- 右键渲染 → Menu.__iter__ → _visible_items()（过滤 visible=False）
- pystray 无双击事件（WM_LBUTTONDBLCLK 被忽略），双击 = 两次 UP

用法: python scripts\\test_menu_default.py
"""

import pystray  # noqa: E402


def main():
    fired = []
    menu = pystray.Menu(
        pystray.MenuItem(
            "", lambda icon, item: fired.append("default"),
            default=True, visible=False,
        ),
        pystray.MenuItem("settings", lambda icon, item: fired.append("menu")),
    )

    # 模拟左键：Menu.__call__ 应命中不可见默认项
    menu(object())
    assert fired == ["default"], f"左键应触发不可见默认项, got {fired}"

    # 模拟右键渲染迭代：不可见项不得出现
    visible = [item.text for item in menu]
    assert visible == ["settings"], f"渲染应只见可见项, got {visible}"

    print(f"OK left_click={fired} rendered={visible}")


if __name__ == "__main__":
    main()
