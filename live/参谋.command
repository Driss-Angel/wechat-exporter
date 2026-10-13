#!/bin/bash
# 双击启动「微信参谋」（监听 + 悬浮窗）。再次双击只会报告状态，不会重复启动。
cd "$(dirname "$0")" || exit 1
./ctl.sh start
echo; ./ctl.sh status
echo; read -r -p "按回车关闭此窗口（程序继续在后台运行；停止请运行 ctl.sh stop）…" _
