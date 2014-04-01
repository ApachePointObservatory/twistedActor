from __future__ import division, absolute_import
"""Utilities to aid unit tests
"""
import os

from . import log

def startLogging(filePath):
    """Set TCC environment variables appropriately for running unit tests

    @param[in] filePath: path of file being tested (e.g. __file__); must be in subdir tests of your package
        (NOT deeper in the hierarchy) in order to determine where the log file should go.
    """
    if filePath is None:
        return
    testDir, testFile = os.path.split(filePath)
    logDir = os.path.join(testDir,  ".tests")
    os.environ["TWISTED_LOG_DIR"] = logDir
    logFileName = "%s.log" % (os.path.splitext(testFile)[0],)
    logFilePath = os.path.join(logDir, logFileName)
    if os.path.isfile(logFilePath):
        try:
            os.remove(logFilePath)
        except Exception, e:
            print "Tried to delete exist log file %r but failed: %s" % (logFilePath, e)
    log.startLogging(logDir, logFileName, serverMode=False)

def init(filePath=None):
    """Prepare for a unit test to run that starts an actor

    @param[in] filePath: path of file being tested (e.g. __file__), or None:
        - If supplied must be in subdir tests of your package (NOT deeper in the hierarchy)
            in order to determine where the log file should go.
        - If None, no log file is created.
    """
    startLogging(filePath)
