

import collections
import sys
import traceback

from twisted.internet.defer import Deferred
from twisted.python import failure
from opscore.RO.Comm import Generic
Generic.setFramework("twisted")
from opscore.RO.Comm.TCPConnection import TCPConnection
from opscore.RO.Comm.TwistedTimer import Timer
from opscore.actor import ActorDispatcher, CmdVar, DoneCodes, FailedCodes

from .baseWrapper import BaseWrapper

__all__ = ["DispatcherWrapper", "CmdWrapper"]

class DispatcherWrapper(BaseWrapper):
    """!A wrapper for an opscore.ActorDispatcher talking to an wrapped actor

    This wrapper is responsible for starting and stopping everything:
    - It builds an actor dispatcher when the actor wrapper is ready
    - It stops the actor wrapper and actor dispatcher on close()

    Public attributes include:
    - actorWrapper: the actor wrapper (twistedActor.ActorWrapper)
    - dispatcher: the actor dispatcher (twistedActor.ActorDispatcher); None until ready
    - readyDeferred: called when the dispatcher is ready
      (for tracking closure use the Deferred returned by the close method, or stateCallback).
    """
    def __init__(self,
        actorWrapper,
        dictName,
        name = "",
        readCallback = None,
        stateCallback = None,
        debug = False,
    ):
        """!Construct a DispatcherWrapper that manages everything

        @param[in] actorWrapper  actor wrapper (twistedActor.ActorWrapper); must be starting up or ready
        @param[in] dictName  name of actor keyword dictionary
        @param[in] name  a name to use for messages
        @param[in] readCallback  function to call when the actor dispatcher has data to read
        @param[in] stateCallback  function to call when connection state of of any socket changes;
            receives one argument: this actor wrapper
        @param[in] debug  print debug messages to stdout?
        """
        BaseWrapper.__init__(self,
            name = name,
            stateCallback = stateCallback,
            callNow = False,
            debug = debug,
        )
        self.actorWrapper = actorWrapper
        self._dictName = dictName
        self._readCallback = readCallback
        self.dispatcher = None # the ActorDispatcher, once it's built
        self.actorWrapper.addCallback(self._actorWrapperStateChanged)
        self._actorWrapperStateChanged()

    def _makeDispatcher(self, connection):
        self.debugMsg("_makeDispatcher()")
        self.dispatcher = ActorDispatcher(
            connection = connection,
            name = self._dictName, # name of keyword dictionary
        )
        # initialize a command queue
        self.cmdQueue = DispatcherCmdQueue(self.dispatcher)

    @property
    def actor(self):
        """!Return the actor (in this case, the mirror controller)
        """
        return self.actorWrapper.actor

    @property
    def userPort(self):
        """!Return the actor port, if known, else None
        """
        return self.actorWrapper.userPort

    @property
    def isReady(self):
        """!Return True if the actor has connected to the fake hardware controller
        """
        return self.actorWrapper.isReady and self.dispatcher is not None and self.dispatcher.connection.isConnected

    @property
    def isDone(self):
        """!Return True if the actor and fake hardware controller are fully disconnected
        """
        return self.actorWrapper.isDone and self.dispatcher is not None and self.dispatcher.connection.isDisconnected

    @property
    def isFailing(self):
        """!Return True if there is a failure
        """
        return self.actorWrapper.didFail or (self.dispatcher is not None and self.dispatcher.connection.didFail)

    def queueCmd(self, cmdStr, timeLim=0, timeLimKeyVar=None, timeLimKeyInd=0, keyVars=None, callFunc=None, callCodes=":"):
        """!add command to queue, dispatch when ready

        @warning error handling is determined by callCodes; for details, see the documentation
            for the returned deferred below

        @param[in] cmdStr  a command string
        @param[in] timeLim  maximum time before command expires, in sec; 0 for no limit
        @param[in] timeLimKeyVar  a KeyVar specifying a delta-time by which the command must finish
        @param[in] timeLimKeyInd  the index of the time limit value in timeLimKeyVar; defaults to 0;
            ignored if timeLimKeyVar is None.
        @param[in] keyVars  a sequence of 0 or more keyword variables to monitor for this command.
            Any data for those variables that arrives IN RESPONSE TO THIS COMMAND is saved
            and can be retrieved using cmdVar.getKeyVarData or cmdVar.getLastKeyVarData.
        @param[in] callFunc  receives one arguement the CmdVar
        @param[in] callCodes  a string of message codes that will result in calling callFunc;
            common values include ":"=success, "F"=failure and ">"=queued
            see opscore.actor.keyvar for all call codes.

        Common use cases:
        - To call callFunc only when the command succeeds, use callCodes=":" (the default);
            if the command fails callFunc is not called.
        - To call callFunc every time the cmdVar calls back, while running successfully,
            specify callCodes=""DIW:>". Again, if the command fails callFunc is not called.
        - To test a command you expect to fail, specify callCodes=":F!"
            and have callFunc assert cmdVar.didFail

        @return two items:
        - deferred: a Twisted Deferred:
            - errorback is called if:
                - the cmdVar fails (unless callCodes includes "F")
                - callFunc raises an exception
            - otherwise callback is called when the command is done and callFunc did not raise an exception
        - cmdVar: the CmdVar for the command
        """
        cmdVar = CmdVar(
            actor = self._dictName,
            cmdStr = cmdStr,
            timeLim = timeLim,
            timeLimKeyVar = timeLimKeyVar,
            timeLimKeyInd = timeLimKeyInd,
            keyVars = keyVars,
        )
        cmdWrapper = CmdWrapper(cmdVar=cmdVar, callFunc=callFunc, callCodes=callCodes)
        self.cmdQueue.addCmd(cmdWrapper)
        return (cmdWrapper.deferred, cmdVar)

    def _actorWrapperStateChanged(self, dumArg=None):
        """!Called when the device wrapper changes state
        """
        if self.actorWrapper.isReady and not self.dispatcher:
            connection = TCPConnection(
                host = 'localhost',
                port = self.actorWrapper.userPort,
                readLines = True,
                name = "mirrorCtrlConn",
            )
            self._makeDispatcher(connection)
            connection.addStateCallback(self._stateChanged)
            if self._readCallback:
                connection.addReadCallback(self._readCallback)
            connection.connect()
        self._stateChanged()

    def _basicClose(self):
        """!Close dispatcher and actor
        """
        if self.dispatcher:
            self.dispatcher.disconnect()
        self.actorWrapper.close()


class CmdWrapper(object):
    def __init__(self, cmdVar, callFunc, callCodes):
        """!Start a command and call callFunc if it succeeds

        @param[in] cmdVar  command variable (instance of opscore.actor.CmdVar)
        @param[in] callFunc  callback function to call if the command succeeds, or None;
            if specified, callFunc receives one argument: cmdVar;
            if callFunc raises an exception then a traceback is printed and the command wrapper fails
        @param[in] callCodes  if True then only call callFunc if and when the command succeeds

        Maintain a deferred that fails if the command fails or callFunc raises an exception
        and completes successfully if both succeed.
        """
        self.deferred = Deferred()
        self.cmdVar = cmdVar
        self.callFunc = callFunc
        self.callCodes = set(callCodes)
        self._checkCmd = not bool(self.callCodes & set(FailedCodes)) # check command state if callFunc is not called on command failure
        callOrDoneCodes = "".join(set(callCodes) | set(DoneCodes))
        cmdVar.addCallback(self._cmdCallback, callCodes = callOrDoneCodes)
        self._stateFunc = None
        self.didFail = False

    def setStateFunc(self, stateFunc):
        if self._stateFunc is not None:
            raise RuntimeError("%s already has a state function" % (self,))
        if self.isDone:
            raise RuntimeError("%s already finished" % (self,))
        self._stateFunc = stateFunc

    def startCmd(self, dispatcher):
        """!Start running the command
        """
        if self.cmdVar.isDone:
            raise RuntimeError("Already done")
        print("Starting command %s" % (self.cmdVar,))
        dispatcher.executeCmd(self.cmdVar)

    @property
    def isDone(self):
        return self.deferred.called

    @property
    def _reportFailure(self):
        """!Return True if cmdVar and we check for failure (because failure codes not in callCodes)
        """
        return self.cmdVar.didFail and self._checkCmd

    def _cmdCallback(self, cmdVar=None):
        """!Command callback
        """
        # call the callback, if justified:
        # function exists, last message code matches and command does not have a reportable failure
        if (self.callFunc is not None) and (self.cmdVar.lastCode in self.callCodes) and not self._reportFailure:
            # either the command succeeded, or checking for success is disabled
            try:
                self.callFunc(self.cmdVar)
            except Exception as e:
                # callback failed; fail this command
                traceback.print_exc(file=sys.stderr) # is this always needed?
                Timer(0, self._finish, e)
                return

        if self.cmdVar.isDone:
            if self._reportFailure:
                try:
                    reason = self.cmdVar.lastReply.string
                except Exception:
                    reason = "why? (no lastReply)"
                msgStr = "Command %s failed: %s" % (self.cmdVar, reason)
                print(msgStr)
                Timer(0, self._finish, RuntimeError(msgStr))
            else:
                print("Command %s done" % (self.cmdVar,))
                Timer(0, self._finish)


    def _finish(self, exception=None):
        """!Command finished; call deferred and stateFunc and clear callFunc and stateFunc

        @param[in] exception  an exception or None; if specified, the command wrapper is failed
        """
        self.callFunc = None
        if exception:
            self.didFail = True
            self.deferred.errback(failure.Failure(exception))
        else:
            self.deferred.callback(self.cmdVar)
        if self._stateFunc:
            stateFunc, self._stateFunc = self._stateFunc, None
            stateFunc(self)

    def __repr__(self):
        return "%s(cmdVar=%r, callFunc=%r, callCodes=%s)" % \
            (type(self).__name__, self.cmdVar, self.callFunc, self.callCodes)


class DispatcherCmdQueue(object):
    def __init__(self, dispatcher):
        """!A simple command queue that dispatches commands in the order received

        @param[in] dispatcher  an opscore dispatcher
        """
        self.dispatcher = dispatcher
        self.currCmdWrapper = None
        self.cmdQueue = collections.deque() # a list of CmdWrapper instances in FIFO order

    def addCmd(self, cmdWrapper):
        """!Add a cmdVar to the queue and call a callFunc if it succeeds

        @param[in] cmdWrapper  command wrapper, an instance of CmdWrapper
        """
        self.cmdQueue.append(cmdWrapper)
        self.runQueue()

    @property
    def isBusy(self):
        """!Return True if the command queue is running a command
        """
        return self.currCmdWrapper is not None and not self.currCmdWrapper.isDone

    def _cmdWrapperDone(self, cmdWrapper):
        if not cmdWrapper.isDone:
            print("Warning: DispatcherCmdQueue._cmdWrapperDone called with not done wrapper")
            return

        if cmdWrapper.didFail:
            # stop the test
            for cmdWrapper in self.cmdQueue:
                cmdWrapper.deferred.callback("cancel because %s failed" % (self.currCmdWrapper,))
            return
        else:
            self.runQueue()

    def runQueue(self):
        if self.isBusy:
            return

        if self.cmdQueue:
            self.currCmdWrapper = self.cmdQueue.popleft()
            self.currCmdWrapper.setStateFunc(self._cmdWrapperDone)
#            self.currCmdWrapper.startCmd(self.dispatcher)
            Timer(0, self.currCmdWrapper.startCmd, self.dispatcher)
