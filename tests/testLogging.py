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
import glob
import os
import sys
import time

from twisted.trial.unittest import TestCase
from twistedActor import log, stopLogging, startFileLogging, LogLineParser
import twistedActor
from twisted.internet import reactor
from twisted.internet.defer import Deferred

path2logs = os.path.join(os.path.abspath(os.path.dirname(__file__)), "logtest")
logNum = 0

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
        global logNum
        self.testLogPath = path2logs

        self.logFile = startFileLogging(self.testLogPath + "%i" % logNum)
        logNum += 1
        os.chmod(self.logFile, 0777)

    def emptyDir(self, dir):
        itemsToDelete = glob.glob(self.testLogPath + "*")
        for deleteMe in itemsToDelete:
            os.remove(deleteMe)

    def getSecsNow(self):
        t = time.localtime()
        return (t.tm_hour*60 + t.tm_min)*60 + t.tm_sec

    def getAllLogs(self):
        return glob.glob(self.testLogPath + "*")
        # return glob.glob(os.path.join(self.testLogPath, "logtest*"))

    def getCurrentLog(self):
        logs = sorted(self.getAllLogs())
        return logs[-1]

    def getPreviousLog(self):
        logs = sorted(self.getAllLogs())
        return logs[-2]

    def tearDown(self):
        stopLogging()
        self.emptyDir(self.testLogPath)
        rmCmd = "rm -r %s"%self.testLogPath
        os.system(rmCmd)


    def getLogInfo(self, filename):
        return LogLineParser().parseLogFile(filename)

    def testDum(Self):
        logMsg = "I was just logged"
        log.info(logMsg)

    def testSimplestCase(self):
        logMsg = "I was just logged"
        log.info(logMsg)
        loggedInfo = self.getLogInfo(self.logFile)
        self.assertTrue(len(loggedInfo)==1) # only one line in log
        self.assertTrue(loggedInfo[0][1]==logMsg)

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

if __name__ == '__main__':
    from unittest import main
    main()