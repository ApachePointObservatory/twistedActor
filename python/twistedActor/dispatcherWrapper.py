from __future__ import division, absolute_import

from twisted.internet.defer import Deferred
import RO.Comm.Generic
RO.Comm.Generic.setFramework("twisted")
from RO.Comm.TCPConnection import TCPConnection
from RO.Comm.TwistedTimer import Timer
from opscore.actor import ActorDispatcher, CmdVar

from .baseWrapper import BaseWrapper

__all__ = ["DispatcherWrapper", "deferredFromCmdVar"]

class DispatcherWrapper(BaseWrapper):
    """A wrapper for an opscore.ActorDispatcher talking to an wrapped actor

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
        readCallback = None,
        stateCallback = None,
        debug = False,
    ):
        """Construct a DispatcherWrapper that manages everything

        @param[in] actorWrapper: actor wrapper (twistedActor.ActorWrapper); must be starting up or ready
        @param[in] dictName: name of actor keyword dictionary
        @param[in] readCallback: function to call when the actor dispatcher has data to read
        @param[in] stateCallback: function to call when connection state of of any socket changes;
            receives one argument: this actor wrapper
        @param[in] debug: print debug messages to stdout?
        """
        BaseWrapper.__init__(self, stateCallback=stateCallback, callNow=False, debug=debug)
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
        """Return the actor (in this case, the mirror controller)
        """
        return self.actorWrapper.actor

    @property
    def userPort(self):
        """Return the actor port, if known, else None
        """
        return self.actorWrapper.userPort

    @property
    def isReady(self):
        """Return True if the actor has connected to the fake hardware controller
        """
        return self.actorWrapper.isReady and self.dispatcher is not None and self.dispatcher.connection.isConnected

    @property
    def isDone(self):
        """Return True if the actor and fake hardware controller are fully disconnected
        """
        return self.actorWrapper.isDone and self.dispatcher is not None and self.dispatcher.connection.isDisconnected

    @property
    def isFailing(self):
        """Return True if there is a failure
        """
        return self.actorWrapper.didFail or (self.dispatcher is not None and self.dispatcher.connection.didFail)

    def queueCmd(self, cmdStr, callFunc=None):
        """add command to queue, dispatch when ready
        @param[in] cmdStr: a command string
        @param[in] callFunc: receives one arguement the CmdVar, called when command completes
        @return (deferred, cmdVar) deferred fires when the command is completed

        Turn a command string into an opscore cmdVar, return a deferred that fires
        when the command is completed. Once completed assert that the shouldFail == didFail.
        """
        cmdVar = CmdVar (
                actor = self._dictName,
                cmdStr = cmdStr,
                callFunc = callFunc
            )
        return self.cmdQueue.addCmd(cmdVar), cmdVar

    def _actorWrapperStateChanged(self, dumArg=None):
        """Called when the device wrapper changes state
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
        """Close dispatcher and actor
        """
        if self.dispatcher:
            self.dispatcher.disconnect()
        self.actorWrapper.close()

class DispatcherCmdQueue(object):
    def __init__(self, dispatcher):
        """ A simple command queue that dispatches commands in the order received

        @param[in] dispatcher: an opscore dispatcher
        """
        self.dispatcher = dispatcher
        self.cmdQueue = []

    def addCmd(self, cmdVar):
        """Add a cmdVar to the queue

        @param[in] cmdVar: an opscore cmdVar object
        @return a deferred associated with this command
        """
        # append an isRunning flag to the cmdVar
        cmdVar.isRunning = False
        def runQueue(dummy=None):
            """Run the queue, execute next command if previous has finished
            @param[in] dummy: incase of callback
            """
            for cmd in self.cmdQueue:
                if cmd.isDone:
                    # onto the next one
                    continue
                elif cmd.isRunning:
                    # cmd is not done and is running
                    # do nothing
                    return
                else:
                    # cmd is not done not running, start it
                    # and exit loop
                    cmd.isRunning = True
                    Timer(0, self.dispatcher.executeCmd, cmd)
                    return

        cmdVar.addCallback(runQueue)
        self.cmdQueue.append(cmdVar)
        runQueue()
        return deferredFromCmdVar(cmdVar)

def deferredFromCmdVar(cmdVar):
    """Return a deferred from a cmdVar.
    The deferred is fired when the cmdVar state is Done

    @param[in] cmdVar: an opscore cmdVar object
    """
    d = Deferred()
    def addMe(cmdVar):
        """add this callback to the cmdVar
        @param[in] the cmdVar instance, passed via callback
        """
        if cmdVar.isDone:
            d.callback(cmdVar) # send this command var with the callback
    cmdVar.addCallback(addMe)
    return d