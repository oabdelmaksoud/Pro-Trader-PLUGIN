#!/bin/bash
if [ -f /tmp/coopercorp_caffeinate.pid ]; then
    kill $(cat /tmp/coopercorp_caffeinate.pid) 2>/dev/null
    rm /tmp/coopercorp_caffeinate.pid
    echo "Keep-awake stopped"
fi
