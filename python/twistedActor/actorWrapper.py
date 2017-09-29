

from .baseWrapper import BaseWrapper

__all__ = ["ActorWrapper"]

class ActorWrapper(BaseWrapper):
    """!A wrapper for a twistedActor.Actor talking to one or more wrapped devices

    This wrapper is responsible for starting the actor and stopping the devices and actor:
    - It takes a list of wrapped devices that are starting up
    - It builds an Actor when the wrapped devices are ready
    - It stops both on close()

    Public attributes include:
    - deviceWrapperList: a list of wrapped devices
    - actor: the actor (None until ready)
    - readyDeferred: called when the actor and fake Galil are ready
      (for tracking closure use the Deferred returned by the close method, or stateCallback).

    Subclasses must override _makeActor
    """
    def __init__(self,
        deviceWrapperList,
        name = "",
        userPort = 0,
        stateCallback = None,
        debug = False,
    ):
        """!Construct a ActorWrapper that manages its devices and controllers

        @param[in] name  a name to use for messages
        @param[in] deviceWrapperList  a list of device wrappers (twistedActor.DeviceWrapper);
            each must be starting up or ready
        @param[in] userPort  port for mirror controller connections; 0 to auto-select
        @param[in] stateCallback  function to call when state of actor server socket or any device wrapper changes
            receives one argument: this actor wrapper
        @param[in] debug  print debug messages to stdout?
        """
        BaseWrapper.__init__(self,
            name = name,
            stateCallback = stateCallback,
            callNow = False,
            debug = debug,
        )
        self.deviceWrapperList = deviceWrapperList
        self._userPort = userPort
        self.actor = None # the actor, once it is built; None until then
        self._actorFailed = False
        for dw in self.deviceWrapperList:
            dw.addCallback(self._deviceWrapperStateChanged, callNow=False)
        self._deviceWrapperStateChanged()

    def _makeActor(self):
        """!Make self.actor; subclasses must override
        """
        raise NotImplementedError()

    @property
    def userPort(self):
        """!Return the actor port, if known, else None
        """
        if self.actor:
            return self.actor.server.port
        return None

    @property
    def isReady(self):
        """!Return True if the actor has connected to the fake hardware controller
        """
        return all(dw.isReady for dw in self.deviceWrapperList) and self.actor is not None and self.actor.server.isReady

    @property
    def isDone(self):
        """!Return True if the actor and fake hardware controller are fully disconnected
        """
        return all(dw.isDone for dw in self.deviceWrapperList) and \
            (self._actorFailed or (self.actor is not None and self.actor.server.isDone))

    @property
    def isFailing(self):
        """!Return True if anything failed
        """
        return any(dw.didFail for dw in self.deviceWrapperList) or self._actorFailed \
            or self.actor is not None and self.actor.server.didFail

    def _basicClose(self):
        """!Close clients and servers
        """
        if not self.deviceWrapperList:
            # no devices, just shut down the actor
            return self.actor.close()
        else:
            for dw in self.deviceWrapperList:
                dw.close()

    def printState(self):
        """!Print state of components; useful for debugging
        """
        stateList = ["%s.device.state=%s" % (dw, dw.device.state if dw.device else "?") for dw in self.deviceWrapperList]
        stateList.append(
            "self.actor.server.state=%s" % (self.actor.server.state if self.actor else "?")
        )
        print("%s state: %s" % (self, ", ".join(stateList)))

    def _deviceWrapperStateChanged(self, dumArg=None):
        """!Called when the device wrapper changes state
        """
        self.debugMsg("_deviceWrapperStateChanged()")
        if not self.actor:
            # opening
            if all(dw.isReady for dw in self.deviceWrapperList):
                try:
                    self.debugMsg("calling _makeActor()")
                    self._makeActor()
                except Exception as e:
                    self._actorFailed = True
                    self.debugMsg("_makeActor() failed; failing readyDeferred: %s" % (e,))
                    self.readyDeferred.errback(e)
                    self._stateChanged()
                    return
                self.actor.server.addStateCallback(self._stateChanged)
        elif self._closeDeferred:
            # closing
            if all(dw.isDone for dw in self.deviceWrapperList):
                self.actor.close()

        self._stateChanged()
