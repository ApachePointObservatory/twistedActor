#!/usr/bin/env python
from .baseWrapper import BaseWrapper
from .baseActor import BaseActor

__all__ = ["DeviceWrapper"]

class DeviceWrapper(BaseWrapper):
    """A wrapper for a twistedActor.Device talking to a (likely fake) controller or controller wrapper
    
    This wrapper is responsible for starting and stopping a controller and device
    - It builds the device when the controller is listening
    - It stops both on close()
    
    Public attributes include:
    - controller: the controller the device talks to; an instance of BaseActor or RO.Comm.TwistedSocket.TCPServer;
        None if a controller wrapper was supplied and is not ready
    - controllerWrapper: a wrapper around the controller the device talks a;
        None if no controller wrapper specified
    - device: the wrapped device (None until ready)
    - readyDeferred: called when the controller and device are both ready
      (for tracking closure use the Deferred returned by the close method, or stateCallback).
    - server: controller server socket; None if controller is None
    
    Subclasses must override _makeDevice to construct the device as self.device
        (no need to set a state callback; that is done automatically).
    """
    def __init__(self,
        name = "",
        controller = None,
        controllerWrapper = None,
        stateCallback = None,
        debug = False,
    ):
        """Construct a DeviceWrapper

        You must specify either controller or controllerWrapper but not both

        @param[in] name: name of device
        @param[in] controller: the controller the device talks to (a RO.Comm.TwistedSocket.TCPServer);
            it need not be listening yet, but must be trying to start listening.
        @param[in] controllerWrapper: a wrapper around the controller the device talks to (an ActorWrapper).
        @param[in] stateCallback: function to call when connection state of controller or device changes;
            receives one argument: this device wrapper
        @param[in] debug: print debug messages to stdout?

        @raise RuntimeError if you do not specify exactly one of controller or controllerWrapper
        
        Subclasses must override _makeDevice
        """
        self.name = name
        BaseWrapper.__init__(self, stateCallback=stateCallback, callNow=False, debug=debug)
        if (controller is None) == (controllerWrapper is None):
            raise RuntimeError("You must specify exactly one of controller or controllerWrapper")
        self._isReady = False
        self.device = None # the wrapped device, once it's built
        self.connCmd = None # the connect device cmd
        self.disConnCmd = None # the disconnect device command
        self.controller = None
        self.server = None
        self.controllerWrapper = controllerWrapper
        if controllerWrapper is not None:
            self.controllerWrapper.addCallback(self._controllerWrapperStateChanged, callNow=True)
        else:
            self._setController(controller)
    
    def _makeDevice(self):
        """Override this method to construct the device
        """
        raise NotImplementedError()
    
    @property
    def port(self):
        """Return port of controller, if known, else None
        """
        return self.server.port
    
    @property
    def isReady(self):
        """Return True if the controller and device are running
        """
        self._isReady = self._isReady or \
            (self.server is not None and self.server.isReady \
             and self.device is not None and self.device.conn.isConnected \
             and self.connCmd is not None and self.connCmd.isDone)
        return self._isReady
    
    @property
    def isDone(self):
        """Return True if the device and controller are fully disconnected
        """
        if self.server is None:
            return self.controllerWrapper.didFail # wrapper failed, so controller will not be built
        else:
            return self.server.isDone \
                and self.device is not None and self.device.conn.isDisconnected \
                and self.disConnCmd is not None and self.disConnCmd.isDone
    
    @property
    def isFailing(self):
        """Return True if there is a failure
        """
        if self.server is None:
            return self.controllerWrapper.didFail
        else:
            return self.server.didFail or (self.device is not None and self.device.conn.didFail)
    
    def _basicClose(self):
        """Close everything
        """
        self._isReady = False
        if self.device is not None:
            self.disConnCmd = self.device.disconnect().userCmd
            self.disConnCmd.addCallback(self._stateChanged)
        if self.controllerWrapper is not None:
            self.controllerWrapper.close()
        if self.server is not None:
            self.server.close()

    def _setController(self, controller):
        """Set self.controller and self.server and server state callbacks

        @param[in] controller: an instance of BaseActor or RO.Comm.TwistedSocket.TCPSocket
        """
        self.controller = controller
        if isinstance(controller, BaseActor):
            self.server = controller.server
        else:
            self.server = controller
        self.server.addStateCallback(self.serverStateChanged)
        self.serverStateChanged()
    
    def serverStateChanged(self, dumArg=None):
        """Called when the controller's server socket changes state
        """
        # print "%s.serverStateChanged; server=%s; state=%s" % (self, self.server, self.server.state)
        if self.server.isReady and not self.device:
            # print "%s._makeDevice()" % (self,)
            self._makeDevice()
            self.device.conn.addStateCallback(self._stateChanged)
            self.connCmd = self.device.connect().userCmd
            self.connCmd.addCallback(self._stateChanged)
        self._stateChanged()

    def _controllerWrapperStateChanged(self, dumArg=None):
        """Called when the controller wrapper state changed
        """
        # print "_controllerWrapperStateChanged; controllerWrapper=%s" % (self.controllerWrapper,)
        if self.controllerWrapper.isReady and not self.controller:
            self._setController(self.controllerWrapper.actor)

    def __str__(self):
        return "%s(%s)" % (type(self).__name__, self.name)

