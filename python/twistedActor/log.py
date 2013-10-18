"""For creating twisted log files for use with actors and devices

refs :
https://twistedmatrix.com/documents/12.2.0/core/howto/logging.html
http://hg.python.org/cpython/file/2.7/Lib/logging/handlers.py
"""
from twisted.python import log
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import time

StartedLogging = False
SuppressSTDIO = False

_NOON = 12*60*60
#_NOON = (11*60 + 21)*60

class NoonRotatingFileHandler(TimedRotatingFileHandler):
    """Modified TimedRotatingFileHandler to rollover at noon.  Note that this is very similar to the 
    midnight rollover implementation of the base class.
    """
    def __init__(self, filename):
        TimedRotatingFileHandler.__init__(self, filename, when='midnight', interval=1, backupCount=0, encoding=None, delay=False, utc=False)

    def computeRollover(self, currentTime):
            """
            Work out the rollover time based on the specified time.
            """
            if self.utc:
                t = time.gmtime(currentTime)
            else:
                t = time.localtime(currentTime)
            currentHour = t[3]
            currentMinute = t[4]
            currentSecond = t[5]
            # r is the number of seconds left between now and noon
            r = _NOON - ((currentHour * 60 + currentMinute) * 60 +
                    currentSecond)
            if r < 0:
                r += 24*60*60
            result = currentTime + r
            return result


def returnFileHandler(logPath):
    """Get a file handler for logging purposes

    @param[in] logPath: the path to the logging directory

    This function will look in the logPath directory.  If no current log file is present, it will make one.
    If the current log file is old (eg from yesterday), it will rotate it.
    If the current file is todays log file, it will continue to write to that one.
    """
    fName = 'twistedActor.log'
    filename=os.path.join(logPath, fName)
    if os.path.exists(filename):
        # determine if the existing file should be rotated or not
        # parse the first line for the date of the first entry
        t = time.localtime()
        with open(filename, 'r') as f:
            year, month, day = [int(x) for x in f.readline().strip().split(" ", 1)[0].split("-")]
        if not (t.tm_year==year and t.tm_mon==month and t.tm_mday==day and t.tm_hour < 12):
            # manually rename this file, adding a date suffix from the earliest entry in the log.
            dateSuffix = ".%i-%i-%i" % (year, month, day) # 
            newfilename = filename + dateSuffix
            n = 1
            while os.path.exists(newfilename): # incase there is already a log file of this name (paranoid?)
                newfilename += ".%i" % n
                n += 1
                if n > 500: # something very wrong
                    raise RuntimeError('bug here, infinite loop while searching for available log files names?')
            os.rename(filename, newfilename)

    fh = NoonRotatingFileHandler(filename)
    return fh 

def captureStdErr():
    """For sending stderr writes to the log
    """
    #sys.stdout = log.StdioOnnaStick(0, getattr(sys.stdout, "encoding", None))
    sys.stderr = log.StdioOnnaStick(1, getattr(sys.stderr, "encoding", None))

def writeToLog(msgStr, logLevel=logging.INFO):
    """ Write to current log.

        @param[in] msgStr: string to be logged
        @param[in] logLevel: a log level available from pythons logging framework

    If StartedLogging is not set, log messages are printed to screen, except if SuppressSTDIO==True in which case nothing is seen.
    Call startLogging to set StartedLogging==True
    
    """
    global StartedLogging
    if not StartedLogging:
        if SuppressSTDIO:
            return
        print "Log Msg: '%s', use startLogging() to begin logging to file" % msgStr
        #raise RuntimeError("Cannot Log Msg: %s. Must call startLogging() first")
    else:
        log.msg(msgStr, logLevel=logLevel)#, system = systemName)   



def startLogging(logPath):
    """ 
        Start logging to a file twistedActor.log.  This file is rotated at noon. After
        rotation a date suffix is added to the file.

        @param[in] logPath: directory where the log file will be placed
    """
    global StartedLogging
    if StartedLogging:
        # logging already started do nothing
        return
    if not os.path.exists(logPath):
        os.makedirs(logPath)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fh = returnFileHandler(logPath)
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    flo = log.PythonLoggingObserver()
    flo.start()
    captureStdErr()
    StartedLogging = True
