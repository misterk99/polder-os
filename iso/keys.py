#!/usr/bin/env python3
import subprocess,sys
m={' ':'spc','-':'minus','/':'slash','.':'dot','=':'equal','|':'shift-backslash','>':'shift-dot',':':'shift-semicolon','_':'shift-minus','"':'shift-apostrophe','*':'shift-8','\n':'ret',"'":'apostrophe',';':'semicolon','[':'bracket_left',']':'bracket_right','!':'shift-1','~':'shift-grave_accent','$':'shift-4',',':'comma','&':'shift-7'}
c=[]
for ch in sys.argv[1]:
    c.append('sendkey '+(m.get(ch) or ('shift-'+ch.lower() if ch.isupper() else ch)))
subprocess.run(['./mon.py']+c)
