#!/usr/bin/env python2
from __future__ import division, absolute_import

import os

from twisted.trial.unittest import TestCase
from twistedActor import log, stopLogging, startFileLogging, LogLineParser

TestLogPath = os.path.join(os.path.abspath(os.path.dirname(__file__)), ".tests", "testLogging")

class LogTest(TestCase):
    logNum = 0 # number the log files so each test has its own log file

    def setUp(self):
        global logNum
        self.logFilePath = startFileLogging("%s_%i_" % (TestLogPath, LogTest.logNum))
        LogTest.logNum += 1
        os.chmod(self.logFilePath, 0777)

    def tearDown(self):
        stopLogging()
        os.remove(self.logFilePath)

    def getLogInfo(self, filename):
        return LogLineParser().parseLogFile(filename)

    def testSimplestCase(self):
        logMsg = "I was just logged"
        log.info(logMsg)
        loggedInfo = self.getLogInfo(self.logFilePath)
        self.assertEqual(len(loggedInfo), 1) # only one line in log
        self.assertEqual(loggedInfo[0][1], logMsg)

if __name__ == '__main__':
    from unittest import main
    main()