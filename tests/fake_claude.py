"""假 Claude 程序：用于确定性地测试 PtyHost，不依赖真 claude。

行为：
- 启动后打印 "Claude ready >"
- 等待一行输入；收到后打印 "working..."，停 0.5 秒，再打印 "done. Claude ready >"
- 收到 "perm" 时打印一条权限询问 "Do you want to proceed? (y/n)"
- 收到 "exit" 时以退出码 0 结束
"""
import sys
import time


def main():
    sys.stdout.write("Claude ready >")
    sys.stdout.flush()
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        cmd = line.strip()
        if cmd == "exit":
            sys.exit(0)
        if cmd == "crash":
            sys.exit(3)
        if cmd == "perm":
            sys.stdout.write("Do you want to proceed? (y/n)")
            sys.stdout.flush()
            continue
        sys.stdout.write("working...")
        sys.stdout.flush()
        time.sleep(0.5)
        sys.stdout.write("done. Claude ready >")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
