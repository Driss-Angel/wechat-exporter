#!/bin/bash
# 微信参谋 控制脚本：start | stop | restart | status | log
# 用法: live/ctl.sh start [--no-dock] [--contact <wxid|备注>] [--style <key>]
#       live/ctl.sh stop | restart | status | log
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
RUN="$HOME/.wechat_live"; LOG="$RUN/logs"; mkdir -p "$LOG"

find_py() {
  for v in "$ROOT/.venv" "$HOME/.wechat_exporter/venv"; do
    for p in python python3; do [ -x "$v/bin/$p" ] && { echo "$v/bin/$p"; return 0; }; done
  done; return 1
}
PY="$(find_py)" || { echo "✗ 没找到虚拟环境，请先双击仓库根目录的 启动.command 安装依赖"; exit 1; }

ensure_deps() {
  "$PY" -c "import sqlcipher3, zstandard" 2>/dev/null || { echo "✗ 虚拟环境缺导出器依赖，先运行 启动.command"; exit 1; }
  "$PY" -c "import AppKit, WebKit, Quartz" 2>/dev/null || { echo "• 安装悬浮窗依赖 pyobjc…"; "$PY" -m pip install -q "pyobjc-framework-Cocoa==11.1" "pyobjc-framework-Quartz==11.1" "pyobjc-framework-WebKit==11.1" || exit 1; }
}
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
start_one() {  # name script args...
  local name="$1"; shift
  if alive "$name"; then echo "• $name 已在运行 (pid $(cat "$RUN/$name.pid"))"; return 0; fi
  (cd "$HERE" && nohup "$PY" -u "$@" >>"$LOG/$name.log" 2>&1 & echo $! >"$RUN/$name.pid")
  sleep 1; alive "$name" && echo "✓ $name 已启动 (pid $(cat "$RUN/$name.pid"))，日志 $LOG/$name.log" || { echo "✗ $name 启动失败，看日志："; tail -5 "$LOG/$name.log"; return 1; }
}
stop_one() {
  local name="$1"
  if alive "$name"; then kill "$(cat "$RUN/$name.pid")" 2>/dev/null; sleep 0.5; alive "$name" && kill -9 "$(cat "$RUN/$name.pid")" 2>/dev/null; echo "✓ $name 已停止"; fi
  rm -f "$RUN/$name.pid"
  # 兜底：清掉手工在终端里起的同名进程
  pkill -f "$HERE/$name.py" 2>/dev/null; pkill -f " $name.py" 2>/dev/null; true
}
cmd="${1:-start}"; shift || true
case "$cmd" in
  start)
    ensure_deps; dock=1; args=()
    while [ $# -gt 0 ]; do case "$1" in --no-dock) dock=0;; *) args+=("$1");; esac; shift; done
    start_one live live.py ${args[@]+"${args[@]}"}
    [ "$dock" = 1 ] && start_one dock dock.py --always
    echo "页面 http://127.0.0.1:8765  ·  停止: $0 stop";;
  stop)    stop_one dock; stop_one live;;
  restart) "$0" stop; sleep 1; "$0" start "$@";;
  status)
    for n in live dock; do alive "$n" && echo "● $n 运行中 (pid $(cat "$RUN/$n.pid"))" || echo "○ $n 未运行"; done
    curl -s -m 2 http://127.0.0.1:8765/state.json | "$PY" -c "import json,sys; s=json.load(sys.stdin); print('  联系人:', s.get('contact'), '| 风格:', s.get('style'), '| 状态:', s.get('status'))" 2>/dev/null || true;;
  log)     tail -n 30 -f "$LOG/live.log" "$LOG/dock.log";;
  *)       echo "用法: $0 start [--no-dock] [--contact X] [--style K] | stop | restart | status | log"; exit 1;;
esac
