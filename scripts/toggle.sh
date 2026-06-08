#!/bin/sh
# Send toggle signal to running vocotype daemon.
# Bind this to a Hyprland keybinding:
#   bind = $mainMod, F2, exec, /path/to/vocotype-cli/scripts/toggle.sh

PID_FILE="/tmp/vocotype.pid"

if [ ! -f "$PID_FILE" ]; then
    notify-send -u critical "VocoType" "VocoType 未运行 (PID 文件不存在)" 2>/dev/null || \
        echo "VocoType 未运行: PID 文件 $PID_FILE 不存在" >&2
    exit 1
fi

PID=$(cat "$PID_FILE" 2>/dev/null)
if [ -z "$PID" ]; then
    notify-send -u critical "VocoType" "VocoType PID 文件为空" 2>/dev/null || \
        echo "VocoType PID 文件为空" >&2
    exit 1
fi

if kill -0 "$PID" 2>/dev/null; then
    kill -USR1 "$PID"
else
    notify-send -u critical "VocoType" "VocoType 进程 (PID=$PID) 已不存在" 2>/dev/null || \
        echo "VocoType 进程 (PID=$PID) 已不存在" >&2
    rm -f "$PID_FILE"
    exit 1
fi
