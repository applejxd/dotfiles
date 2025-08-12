set auto-load local-gdbinit on
set print elements 0
add-auto-load-safe-path /

python
# Update GDB's Python paths with the `sys.path` values of the local
#  Python installation, whether that is brew'ed Python, a virtualenv,
#  or another system python.

# Convert GDB to interpret in Python

import os, subprocess, sys
from os.path import expanduser

sys.path.insert(0, expanduser('~/.config/gdb'))
from eigen_gdb import register_eigen_printers
register_eigen_printers(None)

import opencv_gdb

# Execute a Python using the user's shell and pull out the sys.path (for site-packages)
paths = subprocess.check_output('/usr/bin/python3 -c "import os,sys;print(os.linesep.join(sys.path).strip())"',shell=True).decode("utf-8").split()

# Extend GDB's Python's search path
sys.path.extend(paths)

end
