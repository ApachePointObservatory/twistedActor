#!/usr/bin/env python
"""Install the twistedActor package. Requires setuptools.

To use:
python setup.py install

Alternatively you can copy python/twistedActor to site-packages
"""
from setuptools import setup, find_packages
import sys
import os

PkgName = "twistedActor"

#if not hasattr(sys, 'version_info') or sys.version_info[0:2] < (2,5):
#    raise SystemExit("%s requires Python 2.5 or later." % (PkgName,))

PkgRoot = "python"
PkgDir = os.path.join(PkgRoot, PkgName)
sys.path.insert(0, PkgDir)
# from twistedActor import __version__
# print("%s version %s" % (PkgName, __version__))

setup(
    name = "sdss-" + PkgName,
    version = "2.0.1",
    description = "Actor package based on Twisted Framework",
    author = "Russell Owen",
    package_dir = {PkgName: PkgDir},
    packages = find_packages(PkgRoot),
    include_package_data = True,
    scripts = [],
)
