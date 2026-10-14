#!/bin/bash
# screenshots for the current my/ session: <prefix>-shelf-qs.png, -instellingen.png, -thunar.png
source ${S:-/workspace/rustshelf-test/my}/env; P=$1; S=/workspace/rustshelf-test/my
polder-quicksettings > $S/qs.log 2>&1 & sleep 2.5; grim $P-qs.png; pkill -f polder-quicksettings; sleep 0.8
python3 $S/config/settings/instellingen.py personalisatie > $S/inst.log 2>&1 & sleep 4; grim $P-instellingen.png; pkill -f instellingen.py; sleep 0.5
mkdir -p $HOME/Documenten $HOME/Afbeeldingen $HOME/Muziek; echo x > $HOME/Documenten/notities.txt
GTK_THEME=PolderOS-GTK-$(cat $HOME/.config/osb/gtkslot) thunar $HOME > $S/thunar.log 2>&1 & sleep 3.5; grim $P-thunar.png; pkill -x thunar; sleep 0.5
