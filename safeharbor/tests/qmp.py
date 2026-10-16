#!/usr/bin/env python3
# qmp.py shot FILE.ppm | key KEY [KEY...]
import json, socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect('/workspace/sh-test/qmp.sock'); f = s.makefile('rw')
def cmd(c, **a):
    f.write(json.dumps({'execute': c, 'arguments': a} if a else {'execute': c}) + '\n'); f.flush()
    while True:
        r = json.loads(f.readline())
        if 'return' in r or 'error' in r: return r
f.readline(); cmd('qmp_capabilities')
if sys.argv[1] == 'reset': print(cmd('system_reset'))
elif sys.argv[1] == 'shot': print(cmd('screendump', filename=sys.argv[2]))
else:
    for k in sys.argv[2:]:
        cmd('send-key', keys=[{'type': 'qcode', 'data': k}]); time.sleep(0.3)
