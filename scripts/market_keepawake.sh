#!/bin/bash
# Prevents Mac sleep during market hours (9:25 AM - 4:15 PM ET Mon-Fri)
# Run via cron at 9:20 AM, kill caffeinate at 4:20 PM
caffeinate -d -u -t 25200 &  # 7 hours = 9:20 AM to 4:20 PM
echo $! > /tmp/coopercorp_caffeinate.pid
echo "Keep-awake started (PID $!)"
