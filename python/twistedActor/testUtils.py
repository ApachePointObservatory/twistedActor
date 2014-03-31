from __future__ import division, absolute_import
"""Utilities to aid unit tests
"""
import os

from twistedActor import startLogging

__all__ = ["init"]

def setEnviron(filePath, doLog=True):
    """Set TCC environment variables appropriately for running unit tests

    @param[in] filePath: path of file being tested (e.g. __file__)
    @param[in] doLog: start a log file?
    """
    testDir, testFile = os.path.split(filePath)
    if doLog:
        logDir = os.path.join(testDir,  ".tests")
        os.environ["TWISTED_LOG_DIR"] = logDir
        logFileName = "%s.log" % (os.path.splitext(testFile)[0],)
        startLogging(logDir, logFileName, serverMode=False)

def init(filePath, doLog=True):
    """Prepare for a unit test to run that starts an actor

    @param[in] filePath: path of file being tested (e.g. __file__)
    @param[in] doLog: start a log file?
    """
    setEnviron(filePath=filePath, doLog=doLog)
