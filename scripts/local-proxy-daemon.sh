#!/usr/bin/env bash

PROXY_SCRIPT="$PROJECT_DIR/scripts/local-proxy.py"
PROXY_PORT=8000

start_proxy() {
    if lsof -i :$PROXY_PORT >/dev/null 2>&1; then
        echo "✓ 本地代理已在运行 (端口 $PROXY_PORT)"
        return 0
    fi

    echo "启动本地代理..."
    nohup python3 "$PROXY_SCRIPT" $PROXY_PORT > /tmp/local-proxy.log 2>&1 &
    sleep 2

    if lsof -i :$PROXY_PORT >/dev/null 2>&1; then
        echo "✓ 本地代理已启动 (端口 $PROXY_PORT)"
        return 0
    else
        echo "✗ 本地代理启动失败"
        return 1
    fi
}

stop_proxy() {
    local pid=$(lsof -t -i :$PROXY_PORT 2>/dev/null)
    if [ -n "$pid" ]; then
        kill $pid 2>/dev/null
        echo "✓ 本地代理已停止"
    fi
}

case "${1:-start}" in
    start)
        start_proxy
        ;;
    stop)
        stop_proxy
        ;;
    restart)
        stop_proxy
        start_proxy
        ;;
    status)
        if lsof -i :$PROXY_PORT >/dev/null 2>&1; then
            echo "✓ 本地代理正在运行 (端口 $PROXY_PORT)"
        else
            echo "✗ 本地代理未运行"
        fi
        ;;
esac