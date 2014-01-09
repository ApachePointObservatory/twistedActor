#!/usr/bin/env python
import sys

from twisted.internet.defer import Deferred
import RO.AddCallback

__all__ = ["BaseWrapper"]

class BaseWrapper(RO.AddCallback.BaseMixin):
    """A wrapper for a client talking to a server
    
    This wrapper is responsible for starting and stopping everything:
    - It accepts an actor wrapper
    - It builds an actor dispatcher when the actor wrapper is ready
    - It stops both on close()
    
    Public attributes include:
    - actorWrapper: the actor wrapper (twistedActor.ActorWrapper)
    - dispatcher: the actor dispatcher (twistedActor.ActorDispatcher); None until ready
    - readyDeferred: called when the dispatcher is ready
      (for tracking closure use the Deferred returned by the close method, or stateCallback).
      
    Subclasses must override:
    _basicClose
    isDone
    isReady,
    didFail
    and must call _stateChanged as appropriate; see, e.g. DeviceWrapper
    """
    def __init__(self,
        stateCallback=None,
        callNow=False,
    ):
        """Construct a DispatcherWrapper that manages everything

        @param[in] stateCallback: function to call when connection state of of any socket changes;
            receives one argument: this actor wrapper
        @param[in] callNow: call stateCallback now? (Defaults to false because typically
            subclasses have some additional setup to do before calling callback functions).
        """
        RO.AddCallback.BaseMixin.__init__(self, defCallNow=True)
        self.readyDeferred = Deferred()
        self._closeDeferred = None
        self.addCallback(stateCallback, callNow=callNow)

    @property
    def isReady(self):
        """Return True if the actor has connected to the fake hardware controller
        """
        raise NotImplementedError()
    
    @property
    def isDone(self):
        """Return True if the actor and fake hardware controller are fully disconnected
        """
        raise NotImplementedError()
    
    @property
    def didFail(self):
        """Return True if isDone and there was a failure
        """
        raise NotImplementedError()
    
    def _basicClose(self):
        """Close clients and servers
        """
        raise NotImplementedError()
#         if self.dispatcher:
#             self.dispatcher.disconnect()
#         self.actorWrapper.close()
    
    def _stateChanged(self, *args):
        """Called when state changes
        """
        # print "%r; _stateChanged()" % (self,)
        if self._closeDeferred: # closing or closed
            if self.isDone:
                if not self.readyDeferred.called:
                    self.readyDeferred.cancel()
                if not self._closeDeferred.called:
                    # print "%s calling closeDeferred" % (self,)
                    self._closeDeferred.callback(None)
                else:
                    sys.stderr.write("Device wrapper state changed after wrapper closed\n")
        else: # opening or open
            if not self.readyDeferred.called:
                if self.isReady:
                    # print "%s calling readyDeferred" % (self,)
                    self.readyDeferred.callback(None)
                elif self.didFail:
                    # print "%s calling readyDeferred.errback" % (self,)
                    self.readyDeferred.errback("Failed") # probably should not be a string?


        self._doCallbacks()
        if self.isDone:
            self._removeAllCallbacks()
    
    def close(self):
        """Close everything
        
        @return a deferred
        """
        # print "%s.close()" % (self,)
        if self._closeDeferred:
            raise RuntimeError("Already closing or closed")

        self._closeDeferred = Deferred()
        if not self.readyDeferred.called:
            self.readyDeferred.cancel()
        self._basicClose()
        return self._closeDeferred        
    
    def __str__(self):
        return "%s" % (type(self).__name__,)
    
    def __repr__(self):
        return "%s; isReady=%s, isDone=%s, didFail=%s" % \
            (type(self).__name__, self.isReady, self.isDone, self.didFail)
