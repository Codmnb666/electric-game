@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo 没有找到 Python 命令。请先安装 Python 3.10 或更高版本，
    echo 安装时记得勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

python -c "import pygame" >nul 2>nul
if errorlevel 1 (
    echo.
    echo 还没有安装 pygame，正在尝试安装 pygame-ce ...
    python -m pip install pygame-ce
    if errorlevel 1 (
        echo.
        echo 安装失败。请手动运行： python -m pip install pygame-ce
        pause
        exit /b 1
    )
)

python circuit_game.py
if errorlevel 1 (
    echo.
    echo 游戏异常退出，错误信息见上方。
    pause
)
