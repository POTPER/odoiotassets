#!/bin/bash
export LIBGL_ALWAYS_SOFTWARE=1
gnome-terminal -e "bash -c 'cd /home/ubuntu/linux-arm64/publish; chmod 755 AIotApp; ./AIotApp;'"
