"""For creating twisted log files for use with actors and devices

tweaked from :
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/logfile.py
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/log.py#L392
"""
import twisted.python.log as log
from twisted.python.logfile import LogFile

def writeToLog(msgStr, systemName):
    """ @param[in] msgStr: string to be logged
        @param[in] systemName: string, system that this message is coming from
        
        note: startLogging must be called before writeToLog
    """
    print 'log.defaultObserver msg?', log.defaultObserver
    log.msg(msgStr, system = systemName)



def startLogging(systemName, dir):
    """
        @param[in] systemName: name of system (usually the name of an Actor or Device). 
            Log messages triggered from inside these objects will be directed
            to a unique log file named <systemName>.log
            
        @param[in] dir: directory where the log file will be placed
    """
    fName = systemName + '.log'
    logFile = LogFile(fName, dir)
    flo = ActorLogObserver(logFile, systemName)
    print 'log.defaultObserver? before', log.defaultObserver
    log.startLoggingWithObserver(flo.emit, setStdout=False)
    print 'log.defaultObserver? after', log.defaultObserver
    return flo
    
class ActorLogObserver(log.FileLogObserver):
    """A pickier version of FileLogObserver.  It will only log messages coming
    from a certain system (eg, a single actor or device).  stdin and stderr are 
    not recorded, those will be pushed to a separate log.
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


        