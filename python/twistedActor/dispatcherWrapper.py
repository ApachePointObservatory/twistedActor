import RO.Comm.Generic
RO.Comm.Generic.setFramework("twisted")
from RO.Comm.TCPConnection import TCPConnection
from opscore.actor import ActorDispatcher

from .baseWrapper import BaseWrapper

__all__ = ["DispatcherWrapper"]

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
    ):
        """Construct a DispatcherWrapper that manages everything

        @param[in] actorWrapper: actor wrapper (twistedActor.ActorWrapper); must be starting up or ready
        @param[in] dictName: name of actor keyword dictionary
        @param[in] readCallback: function to call when the actor dispatcher has data to read
        @param[in] stateCallback: function to call when connection state of of any socket changes;
            receives one argument: this actor wrapper
        """
        BaseWrapper.__init__(self, stateCallback=stateCallback, callNow=False)
        self.actorWrapper = actorWrapper
        self._dictName = dictName
        self._readCallback = readCallback
        self.dispatcher = None # the ActorDispatcher, once it's built
        self.actorWrapper.addCallback(self._actorWrapperStateChanged)
        self._actorWrapperStateChanged()
    
    def _makeDispatcher(self, connection):
        #print "_makeDispatcher()"
        self.dispatcher = ActorDispatcher(
            connection = connection,
            name = self._dictName, # name of keyword dictionary
        )
    
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
        return self.actorWrapper.isReady and self.dispatcher and self.dispatcher.connection.isConnected
    
    @property
    def isDone(self):
        """Return True if the actor and fake hardware controller are fully disconnected
        """
        return self.actorWrapper.isDone and self.dispatcher and self.dispatcher.connection.isDisconnected
    
    @property
    def didFail(self):
        """Return True if isDone and there was a failure
        """
        return self.isDone and (self.actorWrapper.didFail or self.dispatcher.connection.didFail)
    
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
