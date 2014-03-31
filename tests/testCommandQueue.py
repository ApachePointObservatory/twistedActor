#!/usr/bin/env python2
from __future__ import division, absolute_import

from twisted.trial import unittest
from twisted.internet.defer import Deferred

from RO.Comm.TwistedTimer import Timer

from twistedActor import CommandQueue, UserCmd, testUtils

testUtils.init(__file__)

def nullCallFunc(cmd):
    pass

cmdPriorityDict = {
    'killa': CommandQueue.Immediate,
    'killb': CommandQueue.Immediate,
    'hia': 3,
    'hib': 3,
    'meda': 2,
    'medb': 2,
    'lowa': 1,
    'lowb': 1,
}

class CmdQueueTest(unittest.TestCase):
    """Unit test for CommandQueue
    """
    def setUp(self):
        self.deferred = Deferred()
        self.doneOrder = []
        self.failOrder = []
        self.cmdQueue = CommandQueue(
            killFunc=self.killFunc,
            priorityDict = cmdPriorityDict
        )
        self.commandsLeft = False

    def tearDown(self):
        self.deferred = None
        self.doneOrder = []
        self.failOrder = []
        self.cmdQueue = None

    def addCmdsToQueue(self, cmdStrList, timeStep=0.02):
        # add commands to the queue every timeStep seconds
        cmdStrListCopy = cmdStrList[:]
        self.commandsLeft = True
        def addInOrder():
            if not cmdStrListCopy:
                # all commands have been added to the queue
                self.commandsLeft = False
                return
            else:
                cmdStr = cmdStrListCopy.pop(0)
                self.cmdQueue.addCmd(self.makeCmd(cmdStr), nullCallFunc)
                Timer(timeStep, addInOrder)
        addInOrder()

    def addToQueue(self, cmdStr):
        self.cmdQueue.addCmd(self.makeCmd(cmdStr), nullCallFunc)
        # Timer(0., self.cmdQueue.addCmd, self.makeCmd(cmdStr), nullCallFunc)

    def cmdCallback(self, cmd):
        # allow commands to run for 0.15 seconds before killing
       # print cmd.cmdVerb, cmd.state
       # print 'q: ', [x.cmd.cmdVerb for x in self.cmdQueue.cmdQueue]
        if cmd.isDone:
            if cmd.didFail:
                self.failOrder.append(cmd.cmdVerb)
            else:
                self.doneOrder.append(cmd.cmdVerb)
        elif cmd.isActive:
            Timer(0.15, self.setDone, cmd)
        if (not self.cmdQueue.cmdQueue) and (self.cmdQueue.currExeCmd.cmd.isDone) and not self.commandsLeft: # must be last command and its done
            # the queue is empty and last command is done, end the test
            self.deferred.callback('go')

    def killFunc(self, killMe):
        killMe.setState(killMe.Cancelled)

    def setDone(self, cmd):
        if not cmd.isDone:
            cmd.setState(cmd.Done)

    def makeCmd(self, cmd):
        newCmd = UserCmd(userID = 0, cmdStr = cmd)
        newCmd.cmdVerb = cmd
        newCmd.addCallback(self.cmdCallback)
        return newCmd

    def testNoRules(self):
        cmdsIn = ['hia', 'hib', 'meda', 'medb', 'lowa', 'lowb']
        def checkResults(cb):
            self.assertEqual(cmdsIn, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testPrioritySort(self):
        cmdsIn = ['hia', 'meda', 'lowa', 'lowb', 'medb', 'hib']
        cmdsOut = ['hia', 'hib', 'meda', 'medb', 'lowa', 'lowb']
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testLowPriorityFirstIn(self):
        cmdsIn = ['lowb', 'meda', 'lowa']
        def checkResults(cb):
            self.assertEqual(cmdsIn, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testImmediate(self):
        cmdsIn = ['hia', 'meda', 'lowa', 'lowb', 'medb', 'hib', 'killa']
        cmdsOut = ['killa']
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testDoubleImmediate(self):
        cmdsIn = ['hia', 'meda', 'lowa', 'lowb', 'medb', 'hib', 'killa', 'killb']
        cmdsOut = ['killb']
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testKillRule(self):
        cmdsIn = ['meda', 'medb']
        cmdsOut = ['medb']
        self.cmdQueue.addRule(
            action = CommandQueue.KillRunning,
            newCmds = ['medb'],
            queuedCmds = ['meda'],
        )
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testSupersede(self):
        cmdsIn = ['hia', 'hib', 'meda', 'medb', 'meda']
        cmdsOut = ['hia', 'hib', 'medb', 'meda']
        self.cmdQueue.addRule(
            action = CommandQueue.CancelQueued,
            newCmds = ['meda'],
            queuedCmds = ['meda'],
        )
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testQueueSame(self):
        cmdsIn = ['hia', 'hia']
        cmdsOut = ['hia', 'hia']
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testCancelNewRule(self):
        cmdsIn = ['meda', 'hib', 'meda', 'medb']
        cmdsOut = ['meda', 'hib', 'meda']
        self.cmdQueue.addRule(
            action = CommandQueue.CancelNew,
            newCmds = ['medb'],
            queuedCmds = ['meda'],
        )
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testCancelQueuedRule(self):
        cmdsIn = ['meda', 'hib', 'meda', 'medb']
        cmdsOut = ['meda', 'hib', 'medb']
        self.cmdQueue.addRule(
            action = CommandQueue.CancelQueued,
            newCmds = ['medb'],
            queuedCmds = ['meda'],
        )
        def checkResults(cb):
            self.assertEqual(cmdsOut, self.doneOrder)
        self.deferred.addCallback(checkResults)
        self.addCmdsToQueue(cmdsIn)
        # for cmd in cmdsIn:
        #     self.addToQueue(cmd)
        return self.deferred

    def testBadRule(self):
        try:
            self.cmdQueue.addRule(
                action = 'badRule',
                newCmds = ['medb'],
                queuedCmds = ['meda'],
            )
        except RuntimeError:
            self.assertTrue(True)
        else:
            self.assertTrue(False)

    def testRuleUnrecognizedCmd(self):
        try:
            self.cmdQueue.addRule(
                action = CommandQueue.CancelNew,
                newCmds = ['badCmd'],
                queuedCmds = ['meda'],
            )
        except RuntimeError:
            self.assertTrue(True)
        else:
            self.assertTrue(False)

    def testStartUnrecognizedCmd(self):
        try:
            self.addToQueue('badCmd')
        except RuntimeError:
            self.assertTrue(True)
        else:
            self.assertTrue(False)


if __name__ == '__main__':
    from unittest import main
    main()
