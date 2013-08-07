"""For creating twisted log files for use with actors and devices

tweaked from :
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/logfile.py
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/log.py#L392
"""
import twisted.python.log as log
from twisted.python.logfile import LogFile
import os

LocalObservers = [] # a list of all currently active local logs (eg a single actor)

def writeToLog(msgStr, systemName, logPath):
    """ @param[in] msgStr: string to be logged
        @param[in] systemName: string, system that this message is coming from
        @param[in] logPath: path to directory where logs will be written
        
        note: startLogging must be called before writeToLog
    """
    global LocalObservers

    if systemName not in [obs.systemName for obs in LocalObservers]:
        # no logs have opened, start this one up
        LocalObservers.append(startLocalLogging(systemName, logPath))
    # if log.defaultObserver is not None, a log hasn't been opened
    log.msg(msgStr, system = systemName)

def startGlobalLogging(dir):
    """ @param[in] dir: directory where the master log file will be placed
    
    Will listen to every log event including stdio and stderr and log them.
    """
    fName = 'global.log'
    logFile = LogFile(fName, dir)
    flo = log.FileLogObserver(logFile)
    log.startLoggingWithObserver(flo.emit, setStdout=True)
    return flo    

def startLocalLogging(systemName, dir):
    """
        @param[in] systemName: name of system (usually the name of an Actor or Device). 
            Log messages triggered from inside these objects will be directed
            to a unique log file named <systemName>.log
            
        @param[in] dir: directory where the log file will be placed
        
        will only place log events with systemName in a log named '<systemName>.log'
    """
    fName = systemName + '.log'
    logFile = LogFile(fName, dir)
    flo = SystemLogObserver(logFile, systemName)
    log.startLoggingWithObserver(flo.emit, setStdout=False)
    return flo
    
class SystemLogObserver(log.FileLogObserver):
    """A pickier version of FileLogObserver.  It will only log messages coming
    from a certain system (eg, a single actor or device).  stdin and stderr are 
    not recorded.
    """
    def __init__(self, logFile, systemName):
        """ @param[in] logFile: a twisted LogFile-like object, which can be rotated, etc.
            @param[in] systemName: name of system (usually the name of an Actor or Device). 
                Log messages triggered from inside these objects will be directed
                to a unique log file named <systemName>.log
        """
        log.FileLogObserver.__init__(self, logFile)
        self.systemName = systemName
    
    def emit(self, eventDict):
        """This is where the magic happens.  Before logging (triggered by any
        log.msg event) may happen, the logging even must have been triggered
        by the system that this observer cares about.
        """ 
        if eventDict['system'] == self.systemName:
            log.FileLogObserver.emit(self, eventDict)


        