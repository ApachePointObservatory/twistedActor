#!/usr/bin/env python
"""Install the TclActor package. Requires setuptools.

To use:
python setup.py install

Alternatively you can copy python/TclActor to site-packages
"""
from setuptools import setup, find_packages
import sys
import os

PkgName = "TclActor"

#if not hasattr(sys, 'version_info') or sys.version_info[0:2] < (2,5):
#    raise SystemExit("%s requires Python 2.5 or later." % (PkgName,))

PkgRoot = "python"
PkgDir = os.path.join(PkgRoot, PkgName)
sys.path.insert(0, PkgDir)
import Version
print "%s version %s" % (PkgName, Version.__version__)

setup(
    name = PkgName,
    version = Version.__version__,
    description = "Actor package based on the Tcl event loop",
    author = "Russell Owen",
    package_dir = {PkgName: PkgDir},
    packages = find_packages(PkgRoot),
    include_package_data = True,
    scripts = [],
)
