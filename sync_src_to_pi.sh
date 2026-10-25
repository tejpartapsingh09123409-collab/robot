#!/bin/bash

set -e

PI="tej@192.168.2.45"
REMOTE_DIR="/home/tej/robot"

echo "Deleting old src driectories on PI"
ssh "$PI" "rm -rf '$REMOTE_DIR/src_kernel' '$REMOTE_DIR/src_userspace'"

echo "Copying kernel and userspace code to PI..."
scp -r src_kernel src_userspace "$PI:$REMOTE_DIR/"

echo "Transfer complete!"
