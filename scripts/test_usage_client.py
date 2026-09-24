"""usage_client 独立测试：真实调用一次用量接口（需有效 Cookie 文件）。

用法:
    python scripts\\test_usage_client.py <cookie文件路径>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import usage_client as uc  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts\\test_usage_client.py <cookie文件路径>")
        sys.exit(2)
    cookie = uc.load_cookie(sys.argv[1])
    data = uc.fetch_usage(cookie)
    s = uc.summarize(data)

    # 结构断言
    assert 0 <= s["plan_percent"] <= 1, s
    assert 0 <= s["month_percent"] <= 1, s
    assert s["limit"] > 0, s

    print("OK")
    print("status:", uc.format_status(s))
    print("summary:", s)


if __name__ == "__main__":
    try:
        main()
    except uc.UsageError as e:
        print(f"UsageError kind={e.kind}: {e}")
        sys.exit(1)
