[app]
title = 电路积木
package.name = circuitlab
package.domain = org.circuitlab
source.dir = .
source.include_exts = py,png,jpg,ttf,txt,svg,json
source.exclude_dirs = .git,.github,__pycache__,screenshots,tests
version = 1.0

# 【关键修改】将 pygame 替换为 pygame-ce，解决云端的编译兼容问题
requirements = python3,pygame-ce

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

[buildozer]
log_level = 2
warn_on_root = 1
