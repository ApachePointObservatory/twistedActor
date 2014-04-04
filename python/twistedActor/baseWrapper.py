from __future__ import division, absolute_import

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
        debug=False,
    ):
        """Construct a DispatcherWrapper that manages everything

        @param[in] stateCallback: function to call when connection state of of any socket changes;
            receives one argument: this actor wrapper
        @param[in] callNow: call stateCallback now? (Defaults to false because typically
            subclasses have some additional setup to do before calling callback functions).
        @param[in] debug: print debug messages to stdout?
        """
        RO.AddCallback.BaseMixin.__init__(self, defCallNow=True)
        self.debug = bool(debug)
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
        """Return True if isDone and there is a failure
        """
        return self.isDone and self.isFailing

    @property
    def isFailing(self):
        """Return True if there is a failure
        """
        raise NotImplementedError()

    def debugMsg(self, msgStr):
        if self.debug:
            print "%s: %s" % (self, msgStr)
    
    def _basicClose(self):
        """Close clients and servers
        """
        raise NotImplementedError()
    
    def _stateChanged(self, *args):
        """Called when state changes
        """
        self.debugMsg("_stateChanged(): isReady=%s, isDone=%s, didFail=%s, isFailing=%s" % \
            (self.isReady, self.isDone, self.didFail, self.isFailing))
        if self.isFailing and not self.isDone and not self._closeDeferred:
            self.close()
            return

        if self._closeDeferred: # closing or closed
            if self.isDone:
                if not self.readyDeferred.called:
                    self.debugMsg("canceling readyDeferred in _stateChanged; this should not happen")
                    self.readyDeferred.cancel()
                if not self._closeDeferred.called:
                    self.debugMsg("calling closeDeferred")
                    self._closeDeferred.callback(None)
                else:
                    sys.stderr.write("%s state changed after wrapper closed\n" % (self,))
        else: # opening or open
            if not self.readyDeferred.called:
                if self.isReady:
                    self.debugMsg("calling readyDeferred")
                    self.readyDeferred.callback(None)
                elif self.didFail:
                    self.debugMsg("failing readyDeferred")
                    self.readyDeferred.errback("Failed") # probably should not be a string?


        self._doCallbacks()
        if self.isDone:
            self._removeAllCallbacks()
    
    def close(self):
        """Close everything
        
        @return a deferred
        """
        self.debugMsg("close()")
        if self._closeDeferred:
            raise RuntimeError("Already closing or closed")

        self._closeDeferred = Deferred()
        if not self.readyDeferred.called:
            self.debugMsg("canceling readyDeferred")
            self.readyDeferred.cancel()
        self._basicClose()
        return self._closeDeferred        
    
    def __str__(self):
        return "%s" % (type(self).__name__,)
    
    def __repr__(self):
        return "%s; isReady=%s, isDone=%s, didFail=%s, isFailing=%s" % \
            (type(self).__name__, self.isReady, self.isDone, self.didFail, self.isFailing)
