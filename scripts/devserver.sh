#!/usr/bin/env bash
# Start/stop the development server with a pid file (safe to call from scripts).
#   scripts/devserver.sh start [port]   |   scripts/devserver.sh stop   |   scripts/devserver.sh restart [port]
cd "$(dirname "$0")/.."
PID=data/uvicorn.pid; LOG=data/uvicorn.log; PORT=${2:-8891}
stop() { [ -f $PID ] && kill "$(cat $PID)" 2>/dev/null && rm -f $PID && echo "stopped"; }
start() { nohup .venv/bin/uvicorn simera.api.main:app --port "$PORT" > $LOG 2>&1 & echo $! > $PID; for i in $(seq 1 15); do sleep 1; curl -s -o /dev/null "http://127.0.0.1:$PORT/docs" && { echo "running on http://127.0.0.1:$PORT/ (pid $(cat $PID))"; return; }; done; echo "failed to start; see $LOG"; }
case "${1:-restart}" in start) start;; stop) stop;; restart) stop; sleep 1; start;; *) echo "usage: $0 start|stop|restart [port]";; esac
