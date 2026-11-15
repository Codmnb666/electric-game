name: Build Android APK

on:
  push:
    branches: [ "main", "master" ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
    - name: 1. 获取仓库代码
      uses: actions/checkout@v4

    - name: 2. 设置 Python 环境
      uses: actions/setup-python@v5
      with:
        python-version: '3.10'

    - name: 3. 设置 Java 环境
      uses: actions/setup-java@v4
      with:
        distribution: 'temurin'
        java-version: '17'

    - name: 4. 安装系统依赖和 Buildozer
      run: |
        sudo apt-get update
        # 安装编译所需的底层库
        sudo apt-get install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
        # 升级 pip 并安装打包工具
        pip3 install --upgrade buildozer cython virtualenv

    - name: 5. 执行 Buildozer 打包
      run: |
        # 清理可能的缓存
        rm -rf ~/.buildozer
        # 开始打包 (首次运行需要下载 SDK/NDK，大约需要 20-30 分钟)
        buildozer -v android debug

    - name: 6. 上传生成的 APK
      uses: actions/upload-artifact@v4
      with:
        name: CircuitLab-APK
        # 自动抓取 bin 目录下生成的 apk 文件
        path: bin/*.apk
        if-no-files-found: error
        
