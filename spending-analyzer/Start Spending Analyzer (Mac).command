#!/bin/bash
cd "$(dirname "$0")"
for p in python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c "import sys, tkinter; sys.exit(sys.version_info < (3,10))" 2>/dev/null; then
    exec "$p" app/main.py
  fi
done
echo "Python 3.10+ (with Tkinter) is required. Install it from https://www.python.org/downloads/ and try again."
read -n 1 -s -r -p "Press any key to close."
