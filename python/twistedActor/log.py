

import datetime
import logging
import logging.handlers
import syslog
import time
logging.Formatter.converter = time.gmtime
import os
import sys
import pyparsing as pp
from twisted.internet import reactor

ROLLTIME = 24*60*60 # a day in seconds

__all__ = ["log", "LogLineParser", "startFileLogging", "startSystemLogging", "stopLogging",
    "getLoggerFacilityName"]

def getLoggerFacilityName(facility):
    """!Get a facility name for the unix logger executable

    @param[in] facility  syslog facility constant; must be one of
        LOG_USER, LOG_SYSLOG and LOG_LOCAL* (the others are not supported)

    @throw KeyError if facility is not supported
    """
    return SyslogLogger.FacilityNameDict[facility].lower()

def startFileLogging(basePath, rotate=None):
    """!Start logging to a file using python logging module

    @param[in] basePath  Full path to file where logging should start.
    @param[in] rotate: if not None, must be datetime.time instance
    specifying what time of day to rollover log.
    """
    global log
    if log:
        raise RuntimeError("%s logger already active" % (log))
        # log.warn("startFileLogging called, but %s logger already active." % (log))
    else:
        if rotate is not None:
            logger = RotatingFileLogger(basePath, rotate)
        else:
            logger = FileLogger(basePath)
        log.replaceLogger(logger)
        return logger.filePath

def startSystemLogging(facility):
    """!Start logging to syslog using python's syslog module

    @note Configure syslog or rsyslog for the specified facility in order to:
    - specify where the messages are logged (e.g. a file or a remote logger)
    - format the messages (e.g. prepend the date)

    @param[in] facility  a syslog.LOG_ facility constant; only a subset are permitted:
        LOG_USER, LOG_SYSLOG and LOG_LOCAL*
    """
    global log
    if log:
        raise RuntimeError("startSystemLogging called, but %s logger already active." % (log))
    log.replaceLogger(SyslogLogger(facility))

def stopLogging():
    """!Stop the current log process
    """
    global log
    log.stopLogging()


class BaseLogger(object):
    """!Base class for loggers

    Subclasses must:
    - define class constants DEBUG, INFO, WARNING, ERROR, CRITICAL
    - override the "log" and "stopLogging" methods
    - define "__init__" to construct the logger and starts logging
    """
    def log(self, logMsg, logLevel):
        """!Log a message at the specified log level

        @param[in] logMsg  message to log (a str)
        @param[in] logLevel  level at which to log, one of:
            self.DEBUG, INFO, WARNING, ERROR, CRITICAL

        Subclasses must provide an implementation of this method
        and define class variables DEBUG, INFO, WARNING, ERROR and CRITICAL
        """
        raise NotImplementedError()

    def stopLogging(self):
        """!Stop logging with this logger
        """
        raise NotImplementedError()

    def __repr__(self):
        return "%s" % (type(self).__name__)


class DefaultLogger(BaseLogger):
    """!Logger that logs to stderr

    Debug and info messages are ignored (to avoid clutter)
    """
    DEBUG = "Debug"
    INFO = "Info"
    WARNING = "Warning"
    ERROR = "Error"
    CRITICAL = "Critical"
    def log(self, logMsg, logLevel):
        if logLevel in (self.DEBUG, self.INFO):
            return
        sys.stderr.write("%s [%s] %s\n"%(self, logLevel, logMsg))

    def stopLogging(self):
        pass # nothing to stop!


class FileLogger(BaseLogger):
    """!Logger that logs to a file

    This logger uses the logging module
    """
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

    def __init__(self, basePath):
        """!Construct a FileLogger for a specific log file.

        @param[in] basePath  path to log file; the full file name will have the date and ".log" appended
            hence "example/foo" will write to "example/foo_<yyyy>_<mm>_<dd>:<hh><mm><ss>.log"
        @return filePath, the basePath with the appended basePath.
        """
        dirPath, baseName = os.path.split(basePath)
        dirPath = os.path.abspath(dirPath)
        if not os.path.exists(dirPath):
            raise RuntimeError("Directory %r does not exist" % (dirPath,))
            os.makedirs(dirPath)
        # append current time to baseName
        filePath = self.getLogFilePath(basePath)

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        fh = self.getFileHandler(filePath)

        # configure stdout to write messages with level warning
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.WARNING)

        logFormatter = logging.Formatter(fmt='%(asctime)s.%(msecs)03d %(levelname)s:  %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh.setFormatter(logFormatter)
        consoleFormatter = logging.Formatter("%(levelname)s: %(message)s")
        console.setFormatter(consoleFormatter) # can use a different formatter to not receive time stamp

        logger.addHandler(fh)
        logger.addHandler(console)
        # captureStdErr(logger)

        self.logger = logger
        self.console = console
        self.fh = fh
        self.filePath = filePath

    def getFileHandler(self, filePath):
        fh = logging.FileHandler(filePath)
        fh.setLevel(logging.DEBUG)
        return fh

    def getLogFilePath(self, basePath):
        return "%s_%s.log" % (basePath, datetime.datetime.now().strftime("%y-%m-%dT%H:%M:%S"))


    def log(self, logMsg, logLevel):
        self.logger.log(logLevel, logMsg)

    def stopLogging(self):
        """!Stop logging and close the log file
        """
        self.logger.removeHandler(self.fh)
        self.logger.removeHandler(self.console)
        self.logger = None
        self.fh = None
        self.console = None

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, self.filePath)

class RotatingFileLogger(FileLogger):
    """
    bit of a hack, set the timed rollover to 25 hours
    but we should be forcing a rollover every 24
    the only case in which a log will not rollover
    is if the actor is killed before the rollover time
    and restarted after, which is probably a small chance
    """

    def __init__(self, basePath, rolloverTime):
        # roloverTime should be a datetime.time object,
        # indicates what time of day to rollover
        FileLogger.__init__(self, basePath)
        timeNow = datetime.datetime.now()
        nextRollover = datetime.datetime(
            timeNow.year, timeNow.month, timeNow.day,
            rolloverTime.hour, rolloverTime.minute, rolloverTime.second
            )
        rollSecs = (nextRollover - timeNow).total_seconds()
        if  rollSecs < 0:
            # we started up after todays rollover
            # add 24 hours in seconds before next rollover
            rollSecs += ROLLTIME

        reactor.callLater(rollSecs, self.roll)



    def getFileHandler(self, filePath):
        fh = logging.handlers.TimedRotatingFileHandler(filePath, when="H", interval=25, utc=True)
        fh.setLevel(logging.DEBUG)
        return fh

    def getLogFilePath(self, basePath):
        return "%s.log" %basePath

    def roll(self):
        self.fh.doRollover()
        reactor.callLater(ROLLTIME, self.roll)




class SyslogLogger(BaseLogger):
    """!Logger that logs to syslog

    This module uses the syslog module, for performance
    """
    DEBUG = syslog.LOG_DEBUG
    INFO = syslog.LOG_INFO
    WARNING = syslog.LOG_WARNING
    ERROR = syslog.LOG_ERR
    CRITICAL = syslog.LOG_CRIT

    # dict of facility value: name as used by logger unix executable
    FacilityNameDict = {
        syslog.LOG_USER:   "user",
        syslog.LOG_SYSLOG: "syslog",
        syslog.LOG_LOCAL0: "local0",
        syslog.LOG_LOCAL1: "local1",
        syslog.LOG_LOCAL2: "local2",
        syslog.LOG_LOCAL3: "local3",
        syslog.LOG_LOCAL4: "local4",
        syslog.LOG_LOCAL5: "local5",
        syslog.LOG_LOCAL6: "local6",
        syslog.LOG_LOCAL7: "local7",
    }

    def __init__(self, facility):
        """!Construct a SyslogLogger

        @param[in] facility  a syslog.LOG_ facility constant; only a subset are permitted:
            LOG_USER, LOG_SYSLOG and LOG_LOCAL*
        """
        if facility not in self.FacilityNameDict:
            raise RuntimeError("Unsupported facility %s")

        syslog.openlog(facility=facility)

    def log(self, logMsg, logLevel):
        syslog.syslog(logLevel, logMsg)

    def stopLogging(self):
        """!Stop logging
        """
        syslog.closelog()


class LogManager(object):
    """!Object that holds the current logger.

    This is needed so that the logger used by the log object can be changed at will.
    """
    def __init__(self):
        self.logger = DefaultLogger()

    def log(self, logMsg, logLevel):
        self.logger.log(logMsg, logLevel)

    def replaceLogger(self, logger):
        """!Stop the current logger and switch to a new logger

        @param[in] logger  an instance of BaseLogger
        """
        self.logger.stopLogging()
        self.logger = logger

    def stopLogging(self):
        """!Stop the current logger and switch back to the default logger
        """
        self.logger.stopLogging()
        self.logger = DefaultLogger()

    def debug(self, logMsg):
        """!Write a debug-level message

        @param[in] logMsg  message string
        """
        self.logger.debug(logMsg)

    def info(self, logMsg):
        """!Write a debug-level message

        @param[in] logMsg  message string
        """
        self.logger.log(logMsg, self.logger.INFO)

    def warn(self, logMsg):
        """!Write a debug-level message

        @param[in] logMsg  message string
        """
        self.logger.log(logMsg, self.logger.WARNING)

    def error(self, logMsg):
        """!Write a debug-level message

        @param[in] logMsg  message string
        """
        self.logger.log(logMsg, self.logger.ERROR)

    def critical(self, logMsg):
        self.logger.log(logMsg, self.logger.CRITICAL)

    def __repr__(self):
        return "%s" % self.logger

    def __bool__(self):
        return not isinstance(self.logger, DefaultLogger)


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
        period = pp.Literal(".").suppress()
        severity = pp.oneOf("DEBUG INFO WARNING ERROR CRITICAL").suppress()
        msg = pp.restOfLine.setResultsName("msg").setParseAction(lambda t: t[0].strip())
        # alltogether
        self.grammar = year + dash + month + dash + day + hour + colon + minute + colon + second + period + ms + severity + colon + msg

    def parseLine(self, line):
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

    def parseLogFile(self, logfile):
        # return a list of tuples containing: [(datetime, logMsg)]
        outList = []
        with open(logfile, "r") as f:
            for ind, loggedLine in enumerate(f):
                loggedLine = loggedLine.strip()
                outList.append(self.parseLine(loggedLine))
        return outList

# global log
log = LogManager()
