#!/usr/bin/env python2
from __future__ import division, absolute_import
"""test logging functionality, stick test logs in _trial_temp

to test:
rollover
reopening
stderr
runtimeError
"""
import collections
import datetime
import glob
import os
import sys
import time

from twisted.trial.unittest import TestCase
from twistedActor import writeToLog, stopLogging, startLogging, parseLogFile
import twistedActor
from twisted.internet import reactor
from twisted.internet.defer import Deferred

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
        os.chmod(self.testLogPath, 0777)

        # manually set a rollover time that shouldn't interfere with these
        # test
        manRollover = secsNow() - 60*60 # set the rollover time to an hour ago.
        if manRollover < 0: # however unlikely...that were testing around midnight
            manRollover += 24*60*60 # add a day.
        twistedActor.log._NOON = manRollover
        startLogging(self.testLogPath)

    def emptyDir(self, dir):
        itemsToDelete = glob.glob(os.path.join(self.testLogPath, "*"))
        for deleteMe in itemsToDelete:
            os.remove(deleteMe)

    def getSecsNow(self):
        t = time.localtime()
        return (t.tm_hour*60 + t.tm_min)*60 + t.tm_sec

    def getAllLogs(self):
        return glob.glob(os.path.join(self.testLogPath, "twistedActor.*"))

    def getCurrentLog(self):
        logs = sorted(self.getAllLogs())
        return logs[-1]

    def getPreviousLog(self):
        logs = sorted(self.getAllLogs())
        return logs[-2]

    def tearDown(self):
        self.emptyDir(self.testLogPath)
        rmCmd = "rm -r %s"%self.testLogPath
        os.system(rmCmd)
        stopLogging()

    def getLogInfo(self, filename):
        return parseLogFile(filename)

    def testDum(Self):
        logMsg = "I was just logged"
        writeToLog(logMsg)

    def testSimplestCase(self):
        logMsg = "I was just logged"
        writeToLog(logMsg)
        loggedInfo = self.getLogInfo(self.getCurrentLog())
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
        startLogging(self.testLogPath)
        writeToLog(logMsgs[2])
        loggedInfo = self.getLogInfo(self.getCurrentLog())
        self.assertTrue(len(loggedInfo)==2)
        self.assertTrue(loggedInfo[0][1]==logMsgs[0])
        self.assertTrue(loggedInfo[1][1]==logMsgs[2])

    def testRollover(self):
        stopLogging() # clear the automatic setup
        # manually set the log to rollover in 1 seconds
        # use time module (thats what the logging module uses)

        startLogging(self.testLogPath, rolloverTime = self.getSecsNow() + 1) # now let r rip
        d = Deferred()
        preRoll = "Before Rollover"
        postRoll = "After Rollover"
        self.preRoll, self.postRoll = preRoll, postRoll
        def writeLater():
            writeToLog(postRoll)
            d.callback("done")
        d.addCallback(self.checkLogs)
        writeToLog(preRoll)
        reactor.callLater(2, writeLater) # write again after rotation time
        return d

    def checkLogs(self, *args):
        logFiles = self.getAllLogs()
        self.assertTrue(len(logFiles)==2)
        # check latest log
        loggedInfo = self.getLogInfo(self.getCurrentLog())
        self.assertTrue(len(loggedInfo)==1) # one line was written
        # print "Debug: ", loggedInfo[0][1]==self.postRoll, self.postRoll
        self.assertTrue(loggedInfo[0][1]==self.postRoll)
        # check the rotated log, first get it's suffix (which is yesterdays date)
        loggedInfo = self.getLogInfo(self.getPreviousLog())
        # only one line should have been written
        self.assertTrue(len(loggedInfo)==1)
        self.assertTrue(loggedInfo[0][1]==self.preRoll)

    def testStdErr(self):
        """Verify that anything sent to std error is sent to log
        """
        logMsg = "I was just logged"
        print >> sys.stderr, logMsg # should be redirected to log
        loggedInfo = self.getLogInfo(self.getCurrentLog())
        self.assertTrue(len(loggedInfo)==1) # only one line in log
        self.assertTrue(loggedInfo[0][1]==logMsg)

if __name__ == '__main__':
    from unittest import main
    main()