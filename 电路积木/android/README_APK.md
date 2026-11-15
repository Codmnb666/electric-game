# 打包 Android APK（手机版）

游戏本体已完整支持手机：窗口自适应缩放、单指拖拽零件、端点连线、双击旋转、触控命中放大、内置中文字体（`fonts/NotoSansSC-Subset.ttf`，不依赖系统字体）。剩下只有一步：把 Python 代码打成 APK 包。

> 本仓库所在机器是 Windows，只装了 JDK 1.8、没有 Android SDK，也没有 Linux 环境，所以**没法在本机直接编译 APK**。下面三种方式任选一种，产出物都是 `bin/circuitlab-1.0-*.apk`。

## 方式一：GitHub Actions（推荐，零环境配置）

仓库已自带 `.github/workflows/build-apk.yml`：

1. 把 `电路积木` 文件夹的内容推到一个 GitHub 仓库（`buildozer.spec`、`main.py`、`.github/` 都要在仓库根目录）；
2. 打开仓库的 **Actions** → **Build Android APK** → **Run workflow**；
3. 等 15-30 分钟（首次要下载 Android SDK/NDK），在运行结果页面底部下载 `circuitlab-apk` 工件，里面的 `.apk` 直接装到手机上。

## 方式二：WSL2 Ubuntu

```bash
# Windows 里先装 WSL2 + Ubuntu（管理员 PowerShell）：
wsl --install -d Ubuntu

# Ubuntu 里：
sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk autoconf libtool \
    pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo6 cmake libffi-dev libssl-dev python3-pip
python3 -m pip install buildozer cython==0.29.36

cd /mnt/d/Users/Lenovo/Documents/deepseek-harness/default-workspace/电路积木
buildozer -v android debug
```

## 方式三：Docker（Linux 原生体验）

```bash
cd 电路积木
docker run --rm -v "$PWD":/home/user/hostcwd kivy/buildozer -v android debug
```

## 安装与运行

- 首次构建会下载 SDK/NDK（约 2-3GB），耐心等待；
- 生成的 APK 在 `bin/` 下，`adb install bin/xxx.apk` 或用文件管理器传到手机安装；
- 手机横屏游玩；触控操作见游戏内 F1 帮助的「触屏」一行；
- 若要发布签名版：`buildozer android release` 并按 buildozer 文档配置 keystore。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `buildozer: command not found` | `pip install buildozer`，或改用 Docker 方式 |
| 下载 SDK 卡住 / 超时 | 重试一次；或在能访问 dl.google.com 的网络环境下构建 |
| 中文显示为方框 | 确认 `fonts/NotoSansSC-Subset.ttf` 已包含在 APK 内（`source.include_exts` 含 `ttf`） |
| 屏幕比例不对 | 游戏会自动等比缩放，留黑边是正常的 |
| 触屏点位偏移 | 已在 `_logical_pos()` 里按缩放换算；若仍偏移请提 issue |
