"""For creating twisted log files for use with actors and devices

tweaked from :
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/logfile.py
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/log.py#L392
"""
import datetime
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
        LocalObservers.append(startLogging(systemName, logPath))
    # if log.defaultObserver is not None, a log hasn't been opened
    log.msg(msgStr, system = systemName)   

def startLogging(systemName, dir):
    """
        @param[in] systemName: name of system (usually the name of an Actor or Device). 
            Log messages triggered from inside these objects will be directed
            to a unique log file named <systemName>.log
            
        @param[in] dir: directory where the log file will be placed
        
        will only place log events with systemName in a log named '<systemName>.log'
    """
    fName = datetime.datetime.now().__str__().replace(' ', 'T').split('.')[0] + '.log'
    print fName
    dir += systemName + '/'
    if not os.path.exists(dir):
        os.makedirs(dir)
    logFile = LogFile(fName, dir)
    flo = SystemLogObserver(logFile, systemName)
    log.startLoggingWithObserver(flo.emit, setStdout=True)
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

# note: code below may be used to filter what to print to log based on self.systemName.    
#     def emit(self, eventDict):
#         """This is where the magic happens.  Before logging (triggered by any
#         log.msg event) may happen, the logging even must have been triggered
#         by the system that this observer cares about.
#         """ 
#         allSys = [x.systemName for x in LocalObservers]
#         if eventDict['system'] == self.systemName:
#             log.FileLogObserver.emit(self, eventDict)
#         elif eventDict['system'] not in allSys:
#             # this is an event automatically generated via twisted, log it
#             log.FileLogObserver.emit(self, eventDict)
#         else:
#             # this event is specific to another log, don't record it
#             pass
            
            


        