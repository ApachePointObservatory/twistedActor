from __future__ import division, absolute_import

import datetime
import logging
import syslog
import time
logging.Formatter.converter = time.gmtime
import os
import sys
import pyparsing as pp

__all__ = ["LogLineParser", "startFileLogging", "startSystemLogging", "stopLogging", "log"]

facilityDict = {
    "USER": syslog.LOG_USER,
    "SYSLOG": syslog.LOG_SYSLOG,
    "LOCAL0": syslog.LOG_LOCAL0,
    "LOCAL1": syslog.LOG_LOCAL1,
    "LOCAL2": syslog.LOG_LOCAL2,
    "LOCAL3": syslog.LOG_LOCAL3,
    "LOCAL4": syslog.LOG_LOCAL4,
    "LOCAL5": syslog.LOG_LOCAL5,
    "LOCAL6": syslog.LOG_LOCAL6,
    "LOCAL7": syslog.LOG_LOCAL7
}

def startFileLogging(filename):
    """ Start logging using python logging module to a file.
        @param[in] filename: Full path to file where logging should start.
        @return filename with datetimestamp appended, or None if logging has already started
    """
    global log
    if log:
        # logging already rolling send an error msg
        raise RuntimeError("startFileLogging called, but %s logger already active." % (log))
        # log.warn("startFileLogging called, but %s logger already active." % (log))
    else:
        logger = PyLogger(filename)
        log.setLogger(logger)
        return logger.filepath

def startSystemLogging(facility):
    """Start logging using python's syslog module.  Note you will need to configure
    syslog/rsyslog for the system.
    @param[in] facility where logs are sent, must be a key in facilityDict
    """
    global log
    if log:
        # logging already rolling send an error msg
        raise RuntimeError("startSystemLogging called, but %s logger already active." % (log))
        # log.warn("startSystemLogging called, but %s logger already active." % (log))
    elif facility not in facilityDict.keys():
        # send msg to std error
        sys.stderr.write("Cannot start system logging to facility %s. Must be one of %s"%(facility, facilityDict.keys()))
    else:
        log.setLogger(SysLogger(facility))

def stopLogging():
    """Stop the current log process
    """
    global log
    log.stopLogging()
    log.setLogger(NullLogger())

class BaseLogger(object):

    def _log(self, logMsg, logLevel):
        """Subclasses must provide this method
        """
        raise NotImplementedError()

    def debug(self, msg):
        self._log(msg, self.DEBUG)

    def info(self, msg):
        self._log(msg, self.INFO)

    def warn(self, msg):
        self._log(msg, self.WARNING)

    def error(self, msg):
        self._log(msg, self.ERROR)

    def critical(self, msg):
        self._log(msg, self.CRITICAL)

    def __repr__(self):
        return "%s" % (type(self).__name__)


class NullLogger(BaseLogger):

    def debug(self,msg):
        pass

    def info(self, msg):
        pass

    def warn(self, msg):
        sys.stderr.write("%s [Warn] %s"%(self, msg))

    def error(self, msg):
        sys.stderr.write("%s [Error] %s"%(self, msg))

    def critical(self, msg):
        sys.stderr.write("%s [Crit] %s"%(self, msg))

    def __nonzero__(self):
        """Boolean value of this logger is False
        """
        return False

    def stopLogging(self):
        pass # nothing to stop!

class PyLogger(BaseLogger):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, self.filepath)

    def __init__(self, filepath):
        """Begin logging to a specified log file.

        @param[in] filepath, path to file.  Currrent date/time will be appended to the filename
        @return filepath, the filepath with the appended filename.
        """
        # determine directories, creat em if they dont exist
        dirname, filename = os.path.split(filepath)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        # append current time to filename
        filename = filename + datetime.datetime.now().strftime("%y-%m-%dT%H:%M:%S")
        fullpath = os.path.join(dirname, filename)

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        fh = logging.FileHandler(fullpath)
        fh.setLevel(logging.DEBUG)

        console = logging.StreamHandler(sys.stdout) # writes to sys.stderr
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
        self.filepath = fullpath

    def stopLogging(self):
        """Shut down logging.
        """
        self.logger.removeHandler(self.fh)
        self.logger.removeHandler(self.console)
        self.logger = None
        self.fh = None
        self.console = None

    def _log(self, logMsg, logLevel):
        self.logger.log(logLevel, logMsg)

class SysLogger(BaseLogger):
    DEBUG = syslog.LOG_DEBUG
    INFO = syslog.LOG_INFO
    WARNING = syslog.LOG_WARNING
    ERROR = syslog.LOG_ERR
    CRITICAL = syslog.LOG_CRIT

    def __init__(self, facility):
        syslog.openlog(facility = facilityDict[facility])

    def stopLogging(self):
        syslog.closelog()

    def _log(self, logMsg, logLevel):
        syslog.syslog(logLevel, logMsg)

class LogManager(object):
    """Object that holds the current logger.
    """
    def __init__(self):
        self.logger = NullLogger()

    def __nonzero__(self):
        return bool(self.logger)

    def setLogger(self, logger):
        self.logger = logger

    def debug(self, msg):
        self.logger.debug(msg)

    def info(self, msg):
        self.logger.info(msg)

    def warn(self, msg):
        self.logger.warn(msg)

    def error(self, msg):
        self.logger.error(msg)

    def critical(self, msg):
        self.logger.critical(msg)

    def stopLogging(self):
        self.logger.stopLogging()

    def __repr__(self):
        return "%s" % self.logger

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
log = LogManager() # global logger, 2 flavors available PyLogger and SystemLogger, if logging hasn't started, use NullLogger.
