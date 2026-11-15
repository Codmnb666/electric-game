[app]
title = 电路积木
package.name = circuitlab
package.domain = org.circuitlab
source.dir = .
source.include_exts = py,png,jpg,ttf,txt,svg,json
source.exclude_dirs = .git,.github,__pycache__,screenshots,tests
version = 1.0
requirements = python3,pygame
orientation = landscape
fullscreen = 1
presplash.color = #0f1116
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.entrypoint = org.kivy.android.PythonActivity
p4a.bootstrap = sdl2
p4a.source_dir = .
# 说明：
# 1) 本文件用于 buildozer 打包 APK，必须在 Linux（WSL2 Ubuntu / Docker）或 CI 上执行。
# 2) 首次构建下载 Android SDK/NDK，需要联网且耗时 10-30 分钟。
# 3) 构建命令：buildozer -v android debug
[buildozer]
log_level = 2
warn_on_root = 1
