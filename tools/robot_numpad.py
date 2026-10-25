#!/usr/bin/env python3
"""Local, focus-only numpad launcher for a Raspberry Pi robot development workflow."""
import os
import queue
import shlex
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, messagebox

PROJECT = Path.home() / 'Documents/learning/linux/robot'
PI = 'tej@192.168.2.45'
REMOTE = '~/robot'

# No sudo password storage, no network listener, no global keyboard hooks.
ACTIONS = {
    'KP_7': ('Sync source', ['rsync', '-av', '--exclude=*.o', '--exclude=*.ko', '--exclude=*.cmd', '--exclude=*.d', '--exclude=*.mod', '--exclude=Module.symvers', '--exclude=modules.order', '--exclude=*.dtbo', '--exclude=*.dtb', 'src_kernel/', f'{PI}:{REMOTE}/src_kernel/']),
    'KP_8': ('Sync userspace', ['rsync', '-av', '--exclude=*.o', '--exclude=*.d', '--exclude=led_controller', 'src_userspace/', f'{PI}:{REMOTE}/src_userspace/']),
    'KP_9': ('Build driver', ['ssh', PI, 'cd ~/robot/src_kernel/driver && make']),
    'KP_4': ('Build application', ['ssh', PI, 'cd ~/robot/src_userspace && make']),
    'KP_5': ('Driver status', ['ssh', PI, 'lsmod | grep -F d_led_spi || true; grep -w robot_led /proc/devices || true; ls -l /dev/robot_led 2>/dev/null || true']),
    'KP_6': ('Kernel logs', ['ssh', PI, 'sudo -n dmesg | tail -n 35']),
    'KP_1': ('Load driver', ['ssh', PI, 'cd ~/robot/src_kernel/driver && sudo -n insmod ./d_led_spi.ko']),
    'KP_2': ('Create device node', ['ssh', PI, 'major=$(awk \'$2=="robot_led" {print $1}\' /proc/devices); test -n "$major" || exit 1; if [ ! -e /dev/robot_led ]; then sudo -n mknod /dev/robot_led c "$major" 0; fi; ls -l /dev/robot_led']),
    'KP_3': ('Run LEDs', ['ssh', PI, 'cd ~/robot/src_userspace && ./led_controller']),
}

root = tk.Tk()
root.title('Robot Numpad • Local Controls')
root.geometry('760x580')
root.configure(bg='#17202c')
messages = queue.Queue()
running = None

heading = tk.Label(root, text='ROBOT NUMPAD', font=('DejaVu Sans', 18, 'bold'), bg='#17202c', fg='#e7f0fb')
heading.pack(pady=(15, 4))
tk.Label(root, text='Click this window, then use the numpad with Num Lock ON. One command at a time.', bg='#17202c', fg='#b6c6da').pack(pady=(0, 12))

frame = tk.Frame(root, bg='#17202c')
frame.pack()
button_grid = [
    [('KP_7', '7\nSYNC KERNEL'), ('KP_8', '8\nSYNC APP'), ('KP_9', '9\nBUILD DRIVER')],
    [('KP_4', '4\nBUILD APP'), ('KP_5', '5\nSTATUS'), ('KP_6', '6\nLOGS')],
    [('KP_1', '1\nLOAD DRIVER'), ('KP_2', '2\nMKNOD'), ('KP_3', '3\nRUN LEDs')],
]
buttons = {}


def append(text):
    output.configure(state='normal')
    output.insert('end', text)
    output.see('end')
    output.configure(state='disabled')


def execute(key):
    global running
    if running is not None and running.poll() is None:
        append('\nA task is already running. Stop it before starting another.\n')
        return
    name, argv = ACTIONS[key]
    if key == 'KP_1' and not messagebox.askyesno('Load kernel module', 'Load a kernel module on the Pi? A buggy module can crash the kernel.'):
        return
    if key == 'KP_2' and not messagebox.askyesno('Create character device', 'Create /dev/robot_led using the currently registered major number?'):
        return
    append(f'\n$ {shlex.join(argv)}\n')
    status.set(f'Running: {name}')
    def worker():
        global running
        try:
            running = subprocess.Popen(argv, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
            for line in running.stdout:
                messages.put(('text', line))
            code = running.wait()
            messages.put(('done', f'{name}: exit status {code}'))
        except Exception as exc:
            messages.put(('done', f'{name}: {exc}'))
    threading.Thread(target=worker, daemon=True).start()

for row_num, row in enumerate(button_grid):
    for col_num, (key, label) in enumerate(row):
        button = tk.Button(frame, text=label, width=17, height=3, bg='#2c435d', fg='white', activebackground='#426c97', font=('DejaVu Sans', 10, 'bold'), command=lambda k=key: execute(k))
        button.grid(row=row_num, column=col_num, padx=5, pady=5)
        buttons[key] = button

tools = tk.Frame(root, bg='#17202c')
tools.pack(fill='x', padx=22, pady=(12, 4))
status = tk.StringVar(value='Idle')
tk.Label(tools, textvariable=status, bg='#17202c', fg='#b6c6da').pack(side='left')


def stop():
    if running is not None and running.poll() is None:
        import signal
        os.killpg(running.pid, signal.SIGINT)
        append('\nSent interrupt to current command.\n')

tk.Button(tools, text='STOP (Esc)', command=stop, bg='#b24646', fg='white').pack(side='right')
output = scrolledtext.ScrolledText(root, height=12, bg='#0d1420', fg='#cce6d8', insertbackground='white', font=('DejaVu Sans Mono', 10), state='disabled')
output.pack(fill='both', expand=True, padx=22, pady=(5, 16))


def handle_key(event):
    if event.keysym == 'Escape':
        stop()
    elif event.keysym in ACTIONS:
        execute(event.keysym)
    # Some X11 configurations send KP_End etc. when NumLock is off.

root.bind_all('<KeyPress>', handle_key)

def pump():
    try:
        while True:
            kind, value = messages.get_nowait()
            if kind == 'text':
                append(value)
            else:
                append(f'\n{value}\n')
                status.set(value)
    except queue.Empty:
        pass
    root.after(80, pump)

root.after(80, pump)
root.mainloop()
