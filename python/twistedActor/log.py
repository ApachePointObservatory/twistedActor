"""For creating twisted log files for use with actors and devices

Logfiles are stored in the directory specified as an argument to startLogging()
Logfiles are automatically named twistedActor.log
Logfiles rollover at noon, and at rollover time the date of the *previous* day is appended to the logfile name.
    A new twistedActor.log is opened and logging continues.
At the time logging is started, a check to the log directory is done. If there is an existing *active* 
    logfile (one with no date appended), logging resumes to that file if the local time is before
    the rollover time for the current log. Else the log is manually rolled over (with the correct date
    appended), and a new twistedActor.log is opened for logging.

refs :
https://twistedmatrix.com/documents/12.2.0/core/howto/logging.html
http://hg.python.org/cpython/file/2.7/Lib/logging/handlers.py
"""
from twisted.python import log as twistedLog
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import time
import datetime
import pyparsing as pp

LogObserver = None
StartedLogging = False
ShowSTDIO = False

_NOON = 12*60*60 # in secs
secPerHour = 60*60
noonHour = float(_NOON)/float(secPerHour)
#_NOON = (11*60 + 21)*60

class EmptyFileError(Exception):
    pass

class LogLineParser(object):
    def __init__(self):
        year = pp.Word(pp.nums, exact=4).setResultsName("year").setParseAction(lambda t: int(t[0]))
        month = pp.Word(pp.nums, exact=2).setResultsName("month").setParseAction(lambda t: int(t[0]))
        day = pp.Word(pp.nums, exact=2).setResultsName("day").setParseAction(lambda t: int(t[0]))
        hour = pp.Word(pp.nums, exact=2).setResultsName("hour").setParseAction(lambda t: int(t[0]))
        minute = pp.Word(pp.nums, exact=2).setResultsName("minute").setParseAction(lambda t: int(t[0]))
        second = pp.Word(pp.nums, exact=2).setResultsName("second").setParseAction(lambda t: int(t[0]))
        ms = pp.Word(pp.nums, exact=3).setResultsName("ms").setParseAction(lambda t: int(t[0]))
        dash = pp.Literal("-").suppress()
        colon = pp.Literal(":").suppress()
        comma = pp.Literal(",").suppress()
        msg = pp.restOfLine.setResultsName("msg").setParseAction(lambda t: t[0].strip())
        # alltogether
        self.grammar = year + dash + month + dash + day + hour + colon + minute + colon + second + comma + ms + msg

    def __call__(self, line):
        ppOut = self.grammar.parseString(line, parseAll=True)
        datetimeStamp = datetime.datetime(
            ppOut.year,
            ppOut.month,
            ppOut.day,
            ppOut.hour,
            ppOut.minute,
            ppOut.second,
            ppOut.ms * 1000 # milliseconds to microseconds
            )
        return datetimeStamp, ppOut.msg        

parseLogLine = LogLineParser()

class NoonRotatingFileHandler(TimedRotatingFileHandler):
    """Modified TimedRotatingFileHandler to rollover at noon.  Note that this is very similar to the 
    midnight rollover implementation of the base class.
    """
    def __init__(self, filename, rolloverTime = _NOON):
        self.rolloverTime = rolloverTime
        TimedRotatingFileHandler.__init__(self, filename, when='midnight', interval=1, backupCount=0, encoding=None, delay=False, utc=False)
        

    def computeRollover(self, currentTime):
            """
            Work out the rollover time based on the specified time.

            Note: this virtually identical to the parent class method (replacing self.rolloverTime vs _MIDNIGHT)
                irrelevant code from parent class method (for other types of rollover) were removed.
            """
            if self.utc:
                t = time.gmtime(currentTime)
            else:
                t = time.localtime(currentTime)
            currentHour = t[3]
            currentMinute = t[4]
            currentSecond = t[5]
            # r is the number of seconds left between now and noon
            r = self.rolloverTime - ((currentHour * 60 + currentMinute) * 60 +
                    currentSecond)
            if r < 0:
                r += 24*60*60
            result = currentTime + r
            return result

def manualRollover(filename, datetime=None, suffix=None):
    """ Rename filename to filename+date

        @param[in] filename: file to be renamed (full path)
        @param[in] datetime: a datetime object from which to extract 
            the correct date to be appended
        @param[in] suffix: a string to be appended to the file name

    note: either datetime or suffix must be supplied, but not both
    """
    if datetime and suffix:
        raise RuntimeError("Cannont specify both datetime and suffix")
    if datetime:
        suffix = ".%i-%i-%i" % (datetime.year, datetime.month, datetime.day)
    newfilename = filename + suffix
    n = 1
    while os.path.exists(newfilename): # incase there is already a log file of this name (paranoid?)
        newfilename += ".%i" % n
        n += 1
        if n > 500: # something very wrong
            raise RuntimeError('bug here, infinite loop while searching for available log files names?')
    os.rename(filename, newfilename)

def parseLogFile(logfile):
    # return a list of tuples containing: [(datetime, logMsg)]
    outList = []
    with open(logfile, "r") as f:
        for ind, loggedLine in enumerate(f):
            loggedLine = loggedLine.strip()
            print 'logged line!', loggedLine
            outList.append(parseLogLine(loggedLine))
    return outList

def returnFileHandler(logPath, rolloverTime = _NOON):
    """Get a file handler for logging purposes

    @param[in] logPath: the path to the logging directory

    This function will look in the logPath directory.  If no current log file is present, it will make one.
    If the current log file is old (eg from yesterday), it will rotate it.
    If the current file is todays log file, it will continue to write to that one.
    """
    fName = 'twistedActor.log'
    filename=os.path.join(logPath, fName)
    if os.path.exists(filename):
        # look at the first line of the current file,
        # decide if we will log to it
        with open(filename, "r") as f:
            firstLine = f.readline()
        try:
            begLogTime, foo = parseLogLine(firstLine)
        except Exception as e:
            print 'log parse problem', e
            # logfile in an unexpected format, force a rollover
            manualRollover(filename, suffix="UNRECOGNIZED_BY_LOGGER")
        else:
            # should logging continue to the present log?
            deltaTime = datetime.datetime.now() - begLogTime
            secondsTillRollover = _NOON - ((begLogTime.hour*60 + begLogTime.minute)*60 + begLogTime.second)
            if secondsTillRollover < 0:
                # add 24 hours
                secondsTillRollover += 24*60*60
            if deltaTime.total_seconds() < secondsTillRollover:
                # continue using current log, no rollover
                pass
            elif begLogTime.hour < noonHour:
                # current log should be rolled over with the previous day's
                # date appended (because first entry was before noon)
                manualRollover(filename, begLogTime - datetime.timedelta(days=1))
            else:
                # current log should be rolled over, date suffix should match the 
                # first entry of the logfile
                manualRollover(filename, begLogTime)
    fh = NoonRotatingFileHandler(filename, rolloverTime = rolloverTime)
    return fh 

class LogStateObj(object):
    def __init__(self):
        self.logger = None # python logging logger
        self.logObserver = None # twisted log observer
        self.startedLogging = False
        self.showStdio = False
        self.fh = None
LogState = LogStateObj()

def startLogging(logPath, showSTDIO=False, rolloverTime = _NOON):
    """ 
        Start logging to a file twistedActor.log.  This file is rotated at noon. After
        rotation a date suffix is added to the file.

        @param[in] logPath: directory where the log file will be placed
        @param[in] showSTDIO: bool. also print log messages to screen.
    """
    if LogState.startedLogging:
        # logging already started do nothing
        return
    if not os.path.exists(logPath):
        os.makedirs(logPath)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fh = returnFileHandler(logPath, rolloverTime)
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logObserver = twistedLog.PythonLoggingObserver()
    logObserver.start()
    captureStdErr()
    # update LogState
    LogState.logObserver = logObserver
    LogState.logger = logger
    LogState.fh = fh
    LogState.startedLogging = True

def stopLogging():
    LogState.logObserver.stop()
    LogState.startedLogging = False
    LogState.logObserver = None
    LogState.logger.removeHandler(LogState.fh)
    LogState.logger = None
    LogState.fh = None

def setSTDIO(stdio=True):
    # begin sending log messages to stdout
    LogState.showStdio = stdio

def captureStdErr():
    """For sending stderr writes to the log
       This is the way twisted does it.
    """
    #sys.stdout = log.StdioOnnaStick(0, getattr(sys.stdout, "encoding", None))
    sys.stderr = twistedLog.StdioOnnaStick(1, getattr(sys.stderr, "encoding", None))

def writeToLog(msgStr, logLevel=logging.INFO):
    """ Write to current log.

        @param[in] msgStr: string to be logged
        @param[in] logLevel: a log level available from pythons logging framework

    If StartedLogging is not set, log messages are printed to screen, except if SuppressSTDIO==True in which case nothing is seen.
    Call startLogging to set StartedLogging==True
    
    """
    if not LogState.startedLogging:
        if LogState.showStdio:
            print "Log Msg: '%s', use startLogging() to begin logging to file" % msgStr
    else:
        twistedLog.msg(msgStr, logLevel=logLevel)#, system = systemName)
        if LogState.showStdio:
            print "Msg Logged: '%s'" % msgStr   

