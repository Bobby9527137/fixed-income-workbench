#!/bin/bash
# 给 macOS 用户双击用的外壳，实际动作都在 run.sh 里。
# 首次双击如果提示没有权限，先在终端里执行：chmod +x 启动.command run.sh

cd "$(cd "$(dirname "$0")" && pwd)"
exec bash ./run.sh "$@"
