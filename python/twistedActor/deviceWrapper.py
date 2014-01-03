#!/usr/bin/env python
from .baseWrapper import BaseWrapper

__all__ = ["DeviceWrapper"]

class DeviceWrapper(BaseWrapper):
    """A wrapper for a twistedActor.Device talking to a (likely fake) controller
    
    This wrapper is responsible for starting and stopping a controller and device
    - It builds the device when the controller is listening
    - It stops both on close()
    
    Public attributes include:
    - controller: the controller the device talks to
    - device: the wrapped device (None until ready)
    - readyDeferred: called when the controller and device are both ready
      (for tracking closure use the Deferred returned by the close method, or stateCallback).
    
    Subclasses must override _makeDevice to construct the device as self.device
        (no need to set a state callback; that is done automatically).
    """
    def __init__(self,
        controller,
        stateCallback = None,
    ):
        """Construct a DeviceWrapper

        @param[in] controller: the controller the device talks to (a RO.Comm.TwistedSocket.TCPServer);
            it need not be listening yet, but must be trying to start listening
        @param[in] stateCallback: function to call when connection state of controller or device changes;
            receives one argument: this device wrapper
        
        Subclasses must override _makeDevice
        """
        BaseWrapper.__init__(self, stateCallback=stateCallback, callNow=False)
        self._isReady = False
        self.device = None # the wrapped device, once it's built
        self.controller = controller
        self.controller.addStateCallback(self._controllerStateChanged)
        self._controllerStateChanged()
    
    def _makeDevice(self):
        """Override this method to construct the device
        """
        raise NotImplementedError()
    
    @property
    def port(self):
        """Return port of controller, if known, else None
        """
        return self.controller.port
    
    @property
    def isReady(self):
        """Return True if the fake hardare controller and device are running
        """
        self._isReady = self._isReady or (self.controller.isReady and self.device.conn.isConnected)
        return self._isReady
    
    @property
    def isDone(self):
        """Return True if the device and controller are fully disconnected
        """
        return self.controller.isDone and self.device.conn.isDisconnected
    
    @property
    def didFail(self):
        """Return True if isDone and there was a failure
        """
        return self.isDone and (self.controller.didFail or self.device.conn.didFail)
    
    def _basicClose(self):
        """Close everything
        
        @return a deferred
        """
        self._isReady = False
        if self.device:
            self.device.disconnect()
        self.controller.close()
    
    def _controllerStateChanged(self, dumArg=None):
        """Called when the controller changes state
        """
        if self.controller.isReady and not self.device:
            self._makeDevice()
            self.device.conn.addStateCallback(self._stateChanged)
            self.device.connect()
        self._stateChanged()
