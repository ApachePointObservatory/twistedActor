"""For creating twisted log files for use with actors and devices

tweaked from :
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/logfile.py
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.2.0/twisted/python/log.py#L392
"""
import shutil
import datetime
from twisted.python import log
from twisted.python.logfile import LogFile
from twisted.internet.task import LoopingCall
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from RO.Comm.TwistedTimer import Timer
import sys
import time

StartedLogging = False
SuppressSTDIO = False

_NOON = 12*60*60

class NoonRotatingFileHandler(TimedRotatingFileHandler):
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
    # look in logDir. If twistedActor.log is present, check when it was last modified
    #
    fName = 'twistedActor.log'
    filename=os.path.join(logPath, fName)
    shouldRollover = False
    if os.path.exists(filename):
        # determine if the existing file should be rotated or not
        # parse the first line for the date of the first entry
        t = time.localtime()
        with open(filename, 'r') as f:
            year, month, day = [int(x) for x in f.readline().strip().split(" ", 1)[0].split("-")]
        if not (t.tm_year==year and t.tm_mon==month and t.tm_mday==day and t.tm_hour < 12):
            shouldRollover = True

    fh = NoonRotatingFileHandler(filename)
    if shouldRollover:
        fh.doRollover()
    return fh 

def captureStdErr():
    #sys.stdout = log.StdioOnnaStick(0, getattr(sys.stdout, "encoding", None))
    sys.stderr = log.StdioOnnaStick(1, getattr(sys.stderr, "encoding", None))

def writeToLog(msgStr, logLevel=logging.INFO):
    """ @param[in] msgStr: string to be logged
        @param[in] systemName: string, system that this message is coming from
        @param[in] logPath: path to directory where logs will be written
        
        note: startLogging must be called before writeToLog
    """
    global StartedLogging
    if not StartedLogging:
        if SuppressSTDIO:
            return
        print "Log Msg: '%s', use startLogging() to begin logging to file" % msgStr
        #raise RuntimeError("Cannot Log Msg: %s. Must call startLogging() first")
    else:
        log.msg(msgStr, logLevel=logLevel)#, system = systemName)   


################## Twisted and Logging ##############################
def startLogging(logPath):
    """
        @param[in] systemName: name of system (usually the name of an Actor or Device). 
            Log messages triggered from inside these objects will be directed
            to a unique log file named <systemName>.log
            
        @param[in] logPath: directory where the log file will be placed
        
        will only place log events with systemName in a log named '<systemName>.log'
    """
    global StartedLogging
    if StartedLogging:
        # logging already started do nothing
        return
    if not os.path.exists(logPath):
        os.makedirs(logPath)
    # fName = 'twistedActor.log'
    # filename=os.path.join(logPath, fName)
    #logging.basicConfig(filename=os.path.join(logPath, fName), format='%(asctime)s %(message)s', level=logging.DEBUG)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    fh = returnFileHandler(logPath)
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    fh.setFormatter(formatter)

    #ch = logging.StreamHandler()
    #ch.setLevel(logging.ERROR)

    logger.addHandler(fh)
    #logger.addHandler(ch)
    #flo = SystemLogObserver(logFile, systemName)
    flo = log.PythonLoggingObserver()
    
    flo.start()
    captureStdErr()
    StartedLogging = True
    #log.startLoggingWithObserver(flo.emit, setStdout=True)
    #return flo
##############################################################################################  
############################ Just Twisted ############################

def startLogging_(systemName, logPath):
    """
        @param[in] systemName: name of system (usually the name of an Actor or Device). 
            Log messages triggered from inside these objects will be directed
            to a unique log file named <systemName>.log
            
        @param[in] logPath: directory where the log file will be placed
        
        will only place log events with systemName in a log named '<systemName>.log'
    """
    global StartedLogging
    if StartedLogging:
        # logging already started do nothing
        return
    # fName = datetime.datetime.now().__str__().replace(' ', 'T').split('.')[0] + '.log'
    # fname = "log"
    #logPath += systemName + '/'
    if not os.path.exists(logPath):
        os.makedirs(logPath)
    #logFile = LogFile(fName, logPath)
    fName = 'log'
    logFile = LogFile(fName, logPath, rotateLength=3000)
    # rotateTimer = Timer()
    # def rotateLog():
    #     global n
    #     print "logpath ", logPath
    #     shutil.copyfile(logPath + "log", logPath + "cache/log%i"%n)
    #     logFile.rotate()
    #     n+=1
    #lc = LoopingCall(logFile.rotate)
    #     rotateTimer.start(Interval, rotateLog)
    #rotateTimer.start(Interval, rotateLog)
    log.startLogging(logFile, setStdout=0)
    captureStdErr()
    def printLoop():
        print "TEST"
        sys.stdout.write("TEST2\n")
    def raiseError():
        raise RuntimeError("KILL")
    def errWrite():
        sys.stderr.write('Kill\n')
        print >> sys.stderr, "Kill2"
    x=LoopingCall(printLoop)
    y=LoopingCall(raiseError)
    z=LoopingCall(errWrite)
    x.start(1, now=False)
    y.start(2, now=False)
    z.start(2, now=False)   
    #lc.start(5)


    StartedLogging = True



# def setupLogging(self):
#     logDir = "python/"
#     filename=os.path.join(logDir, self.filename)
#     logger = logging.getLogger()
#     logger.setLevel(logging.DEBUG)
#     fh = TimedRotatingFileHandler(filename, when='s', interval=5)
#     fh.setLevel(logging.DEBUG)
#     logger.addHandler(fh)

# def logMsg(msg):
#     logging.info(msg)

# class SystemLogObserver(log.PythonLoggingObserver):
#     """A pickier version of FileLogObserver.  It will only log messages coming
#     from a certain system (eg, a single actor or device).  stdin and stderr are 
#     not recorded.
#     """
#     def __init__(self, systemName):
#         """ @param[in] logFile: a twisted LogFile-like object, which can be rotated, etc.
#             @param[in] systemName: name of system (usually the name of an Actor or Device). 
#                 Log messages triggered from inside these objects will be directed
#                 to a unique log file named <systemName>.log
#         """
#         log.PythonLoggingObserver.__init__(self)
#         self.systemName = systemName    

# class SystemLogObserver(log.FileLogObserver):
#     """A pickier version of FileLogObserver.  It will only log messages coming
#     from a certain system (eg, a single actor or device).  stdin and stderr are 
#     not recorded.
#     """
#     def __init__(self, logFile, systemName):
#         """ @param[in] logFile: a twisted LogFile-like object, which can be rotated, etc.
#             @param[in] systemName: name of system (usually the name of an Actor or Device). 
#                 Log messages triggered from inside these objects will be directed
#                 to a unique log file named <systemName>.log
#         """
#         log.FileLogObserver.__init__(self, logFile)
#         self.systemName = systemName

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
            
            


        