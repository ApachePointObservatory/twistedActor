#!/usr/bin/env python
"""test logging functionality, stick test logs in _trial_temp

to test:
rollover
reopening
stderr
runtimeError
"""
from twisted.trial.unittest import TestCase
from twistedActor import writeToLog, stopLogging, startLogging, parseLogFile
import twistedActor
import glob
import os
import time
import collections
from twisted.internet import reactor
from twisted.internet.defer import Deferred
import datetime
import sys

path2logs = os.path.join(os.path.abspath(os.path.dirname(__file__)), "logtest")

def secsNow():
    # return the time now (0-24 hours) in seconds 
    lcTime = time.localtime()
    return (lcTime.tm_hour*60 + lcTime.tm_min)*60 + lcTime.tm_sec

class TimedCallableQueue(object):
    def __init__(self, callableList, callEvery, deferred):
        """Once constructed, this object will call each callable in order in a non blocking fashion
        @param[in] callableList: list type object full of callable objects
        @param[in] callEvery: pop and call each item on the list at this interval in seconds
        @param[in] deferred: to be called when the queue has been emptied
        """
        self.d = deferred
        self.queue = collections.deque(callableList)
        self.callEvery = callEvery

    def callNext(self):
        try:
            nextToCall = self.queue.popleft()
        except IndexError:
            # nothing left must be done
            self.d.callback("done!")
        else:
            nextToCall()
            reactor.callLater(self.callEvery, self.callNext)

    def start(self):
        reactor.callLater(self.callEvery, self.callNext)
        return self.d


class LogTest(TestCase):

    def setUp(self):
        testLogPath = path2logs
        n = 0
        while os.path.exists(testLogPath):
            n += 1
            # append numbers to directory
            # this way if any unittests are running simultaneously
            # under scons, each test has it's own test directory
            head, tail = os.path.split(testLogPath)
            newTail = tail + "%i" % n
            testLogPath = os.path.join(head, newTail)
            if n > 50:
                # runaway loop?
                raise RuntimeError("Runnaway Loop")
        self.testLogPath = testLogPath
        os.makedirs(self.testLogPath)

        #self.deleteLogs()
        # manually set a rollover time that shouldn't interfere with these
        # test
        manRollover = secsNow() - 60*60 # set the rollover time to an hour ago.
        if manRollover < 0: # however unlikely...that were testing around midnight
            manRollover += 24*60*60 # add a day.
        twistedActor.log._NOON = manRollover
        #twistedActor.log.setSTDIO()
        # twistedActor.log._NOON = 5
        # print twistedActor.log._NOON
        startLogging(self.testLogPath, serverMode=False)        

    def deleteLogs(self):
        oldLogs = self.getAllLogs()
        for oldLog in oldLogs:
            os.remove(oldLog)

    def getSecsNow(self):
        t = time.localtime()
        return (t.tm_hour*60 + t.tm_min)*60 + t.tm_sec

    def getAllLogs(self):
        return glob.glob(os.path.join(self.testLogPath, "twistedActor.*"))

    def getLog(self, filename):
        return os.path.join(self.testLogPath, filename)

    def tearDown(self):
        self.deleteLogs()
        os.rmdir(self.testLogPath)
        stopLogging()

    def getLogInfo(self, filename = "twistedActor.log"):
        return parseLogFile(self.getLog(filename))

    def testSimplestCase(self):
        logMsg = "I was just logged"
        writeToLog(logMsg)
        loggedInfo = self.getLogInfo()
        self.assertTrue(len(loggedInfo)==1) # only one line in log
        self.assertTrue(loggedInfo[0][1]==logMsg)

    def testReopenLog(self):
        """write first message, stoplogging, write anoter message, startLogging, write another message.
        Only the first and last messages should appear in the log.
        """
        logMsgs = ["msg: %i"%n for n in range(3)]
        writeToLog(logMsgs[0])
        stopLogging()
        writeToLog(logMsgs[1])
        startLogging(self.testLogPath, serverMode=False)
        writeToLog(logMsgs[2])
        loggedInfo = self.getLogInfo()
        self.assertTrue(len(loggedInfo)==2)
        self.assertTrue(loggedInfo[0][1]==logMsgs[0])
        self.assertTrue(loggedInfo[1][1]==logMsgs[2])

    def testRollover(self):
        stopLogging() # clear the automatic setup
        # manually set the log to rollover in 1 seconds
        # use time module (thats what the logging module uses)

        # twistedActor.log.__NOON = tSecs + 1
        # print "diff", twistedActor.log._NOON - tSecs
        startLogging(self.testLogPath, serverMode = False, rolloverTime = self.getSecsNow() + 1) # now let r rip
        d = Deferred()
        preRoll = "Before Rollover"
        postRoll = "After Rollover"
        self.preRoll, self.postRoll = preRoll, postRoll
        def writeLater():
            writeToLog(postRoll)
            d.callback("done")
        d.addCallback(self.checkLogs)
        writeToLog(preRoll)
        reactor.callLater(1.25, writeLater) # write again after rotation time
        return d

    def testManualRollover(self):
        d = Deferred()
        preRoll = "Before Rollover"
        postRoll = "After Rollover"    
        writeToLog(preRoll)
        self.preRoll, self.postRoll = preRoll, postRoll
        stopLogging()
        def waitasec():
            startLogging(self.testLogPath, serverMode = False, rolloverTime=self.getSecsNow() - 1) 
            # set rollover time to a second ago
            # the previous log should rollover
            writeToLog(postRoll)
            d.callback("go")
        reactor.callLater(2, waitasec)
        d.addCallback(self.checkLogs)
        return d
        
    def checkLogs(self, *args):
        logFiles = self.getAllLogs()
        self.assertTrue(len(logFiles)==2)
        # check latest log
        loggedInfo = self.getLogInfo()
        self.assertTrue(len(loggedInfo)==1) # one line was written
        print "Debug: ", loggedInfo[0][1]==self.postRoll, self.postRoll
        self.assertTrue(loggedInfo[0][1]==self.postRoll)
        # check the rotated log, first get it's suffix (which is yesterdays date)
        datetimeYesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        dateSuffix = ".%02d-%02d-%02d"%(datetimeYesterday.year, datetimeYesterday.month, datetimeYesterday.day)
        filename = "twistedActor.log" + dateSuffix
        loggedInfo = self.getLogInfo(filename)
        # only one line should have been written
        self.assertTrue(len(loggedInfo)==1)
        self.assertTrue(loggedInfo[0][1]==self.preRoll)

    def testUnrecognizedLog(self):
        with open(os.path.join(self.testLogPath, "twistedActor.log"), "w") as f:
            f.write("No date prepended, This is total garbage, and shouldnt be recognized as a log.\n")
        stopLogging()
        startLogging(self.testLogPath, serverMode=False)
        writeToLog("This isn't garbage!")
        # with logging restarted the present log file should have this suffix appended to it
        suffix = "UNRECOGNIZED_BY_LOGGER"
        presentLogs = self.getAllLogs()
        #print 'Present logs', presentLogs
        self.assertTrue(os.path.join(self.testLogPath, "twistedActor.log") in presentLogs)
        self.assertTrue(os.path.join(self.testLogPath,"twistedActor.log"+suffix) in presentLogs)

    def testServerMode(self):
        """Put logger in serverMode, print statements should show up
        """
        stopLogging()
        startLogging(self.testLogPath, serverMode=True)
        logMsg = "I was just logged"
        print logMsg # should be redirected to log
        loggedInfo = self.getLogInfo()
        self.assertTrue(len(loggedInfo)==1) # only one line in log
        self.assertTrue(loggedInfo[0][1]==logMsg)     

    def testNotServerMode(self):
        """print statements should not show up
        """
        logMsg = "I was just logged"
        print logMsg # should be redirected to log
        loggedInfo = self.getLogInfo()
        self.assertTrue(len(loggedInfo)==0) # nothing in log

    def testStdErr(self):
        """Verify that anything sent to std error is sent to log
        """ 
        logMsg = "I was just logged"
        print >> sys.stderr, logMsg # should be redirected to log
        loggedInfo = self.getLogInfo()
        self.assertTrue(len(loggedInfo)==1) # only one line in log
        self.assertTrue(loggedInfo[0][1]==logMsg)  

if __name__ == '__main__':
    from unittest import main
    main()