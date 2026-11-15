"""手机 / 桌面统一入口：buildozer(python-for-android) 默认从这里启动。

桌面直接双击「启动游戏.bat」也可以，两者跑的是同一个 App。
"""
from circuit_game import main

if __name__ == "__main__":
    main()
