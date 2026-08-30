import errno
import json
import os
import signal
import subprocess
import sys
import time


def write_atomic(path, value):
    temporary = f"{path}.tmp-{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)

mode = sys.argv[1]
events_path = sys.argv[2]
if mode == "crash-before-started":
    raise SystemExit(17)
if mode == "wait-before-started":
    write_atomic(sys.argv[3], str(os.getpid()))
    time.sleep(60)
try:
    os.setsid()
except OSError as exc:
    if exc.errno != errno.EPERM or os.getpgrp() != os.getpid():
        raise
write_atomic(
    events_path,
    json.dumps({"type": "started"}) + "\n",
)

if mode == "normal":
    raise SystemExit(0)
if mode in {"term-process-tree", "ignore-term-process-tree"}:
    child_code = """
import json,os,signal,subprocess,sys,time
ignore = sys.argv[1] == 'ignore'
if ignore:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild_code = (
    'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN)'
    if ignore
    else 'import time; time.sleep(60)'
)
grandchild = subprocess.Popen([
    sys.executable,
    '-c',
    grandchild_code,
])
temporary = f'{sys.argv[2]}.tmp-{os.getpid()}'
with open(temporary, 'w', encoding='utf-8') as handle:
    json.dump({'child': os.getpid(), 'grandchild': grandchild.pid}, handle)
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, sys.argv[2])
while True:
    time.sleep(1)
"""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            "ignore" if mode == "ignore-term-process-tree" else "respond",
            sys.argv[3],
        ],
    )
    if mode == "ignore-term-process-tree":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
raise SystemExit(2)
