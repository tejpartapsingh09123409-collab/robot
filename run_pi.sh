#!/bin/bash

set -e

PI=tej@192.168.2.45

ssh "$PI" '

ROBOT_DIR=/home/tej/robot

echo "Entering kernel src"
cd "$ROBOT_DIR/src_kernel/driver"
echo "Compiling kernel src"
make

echo "Entering userspace src"
cd "$ROBOT_DIR/src_userspace/"
echo "Compiling userspace src"
make

'
