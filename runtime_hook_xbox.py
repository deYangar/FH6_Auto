# runtime_hook_xbox.py - PyInstaller 在 exe 启动时执行
# build.bat xbox 通过 --runtime-hook runtime_hook_xbox.py 把本文件嵌入 exe,
# 启动时自动设置 FH6_PLATFORM=xbox,无需用户在命令行手动指定 --platform
# 必须用直接赋值而非 setdefault,以防 build.bat all 中 steam build 残留的环境变量污染
import os
os.environ["FH6_PLATFORM"] = "xbox"