#!/bin/bash

set -e

PI_USER="tej"
PI_HOST="192.168.2.45"
PI_ROBOT_DIR="~/robot"
ROBOT_PORT=8000

echo "================================"
echo "       Starting Robot"
echo "================================"
echo

echo "[1/3] Waiting for Raspberry Pi..."

until ping -c 1 -W 1 "$PI_HOST" >/dev/null 2>&1
do
    echo "Pi not ready yet..."
    sleep 1
done

echo "Pi is online."

echo
echo "[2/3] Starting robot server on Pi..."

ssh "$PI_USER@$PI_HOST" "
    cd $PI_ROBOT_DIR || exit 1

    echo 'Starting pigpio daemon...'
    sudo pigpiod 2>/dev/null || true

    echo 'Stopping old robot server if one exists...'
    pkill -f '^python3 robot_slave\.py$' 2>/dev/null || true

    echo 'Starting robot_slave.py...'
    python3 robot_slave.py
" &

SSH_PID=$!

echo
echo "Waiting for robot server on port $ROBOT_PORT..."

while true
do
    if ! kill -0 "$SSH_PID" 2>/dev/null; then
        echo
        echo "ERROR: SSH/robot server process died before becoming ready."
        exit 1
    fi

    if nc -z "$PI_HOST" "$ROBOT_PORT" 2>/dev/null; then
        break
    fi

    sleep 0.2
done

echo "Robot server is ready."

echo
echo "[3/3] Starting host client..."
echo

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR/ai" || exit 1

python3 robot_host.py