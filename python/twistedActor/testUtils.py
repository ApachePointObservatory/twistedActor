
"""!Utilities to aid unit tests
"""
import os

from . import startFileLogging, stopLogging

def startLogging(filePath):
    """!Set TCC environment variables appropriately for running unit tests

    @param[in] filePath  path of file being tested (e.g. __file__); must be in subdir tests of your package
        (NOT deeper in the hierarchy) in order to determine where the log file should go.
    """
    if filePath is None:
        return
    testDir, testFile = os.path.split(filePath)
    logDir = os.path.join(testDir,  ".tests")
    # if log dir doesn't exist create it
    if not os.path.exists(logDir):
        os.makedirs(logDir)
    logFileName = "%s" % (os.path.splitext(testFile)[0],)
    startFileLogging(os.path.join(logDir, logFileName))

def init(filePath=None):
    """!Prepare for a unit test to run that starts an actor

    @param[in] filePath  path of file being tested (e.g. __file__), or None:
        - If supplied must be in subdir tests of your package (NOT deeper in the hierarchy)
            in order to determine where the log file should go.
        - If None, no log file is created.
    """
    stopLogging() # stop incase logging is already on.
    startLogging(filePath)
