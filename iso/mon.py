#!/usr/bin/env python3
# mon.py 'screendump /path.ppm' | 'sendkey ctrl-alt-f2' ...   (fast: 60 ms between commands)
import socket,sys,time
s=socket.socket(socket.AF_UNIX); s.connect('/tmp/qmon.sock')
for c in sys.argv[1:]: s.send((c+'\n').encode()); time.sleep(0.06)
time.sleep(1)
