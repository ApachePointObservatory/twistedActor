"""A convenient framework for testing actors, devices etc which rely on sending asynchronous commands
and responses over network sockets
"""
__all__ = ["getOpenPort", "CommunicationChain"]

#from twisted.trial.unittest import TestCase
from twisted.internet.defer import Deferred, gatherResults, maybeDeferred
from twistedActor import Actor, TCPDevice
from RO.Comm.TwistedSocket import setCallbacks, _SocketProtocolFactory
import socket

def getOpenPort():
    """Return an open port number.  It seems to work fine.
    There is a miniscule race condition that I believe is negligible.
    @return an open port number
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("",0))
    s.listen(1)
    port = s.getsockname()[1]
    s.close()
    return port

class SocketDeferredWrapper(object):
    def __init__(self, socketObj, connMethod, disConnMethod, connState, disConnState):
        """Wrapper for a socket-type object (connection or server) that specifically handles 
        (asynchronous) startUp and shutDown procedures.

        @param[in] socketObj: A Twisted-RO TCPServer, or TCPConnection
        @param[in] connMethod: a callable, will start connecting or listening
        @param[in] disConnMethod: a callable, will kill connection or stop listening
        @param[in] connState: state (via socketObj.state) that signals sucessfull connection or listening
        @param[in] disConnState: state (via socketObj.state) that signals complete shut down of connection or listening

        This object contains important methods: startUp and shutDown.  These will start or stop 
        connections/servers and, will return Deferred objects unless they are already
        in the desired state. In this case they will return a fired Deferred object
        """
        self.socketObj = socketObj
        try:
            # servers have setStateCallback
            self.socketObj.setStateCallback(callFunc=self.stateCallback)
        except AttributeError:
            # connections have addStateCallback
            self.socketObj.addStateCallback(stateCallback = self.stateCallback)
        if False in [callable(connMethod), callable(disConnMethod)]:
            raise RuntimeError("SocketDeferredWrapper requires callable connection/disconnection inputs")
        self.connMethod = connMethod
        self.disConnMethod = disConnMethod
        self.connState = connState
        self.disConnState = disConnState

        self.connDeferred = Deferred()
        self.disConnDeferred = Deferred()

    @property
    def state(self):
        """@return state of socket
        """
        return self.socketObj.state

    def startUp(self):
        """Startup prodecure for this socket. Returns a Deferred.  

        @return a Deferred, or a fired Deferred

        If the socket is already ready, the Deferred returned from this method comes pre-fired ("called back").
        If the socket is not ready, the deferred is fired once the socket.state == connState
        ***So code handling this methods should use maybeDeferred***
        """
        if self.state == self.connState:
            print 'already connected!!!!!!!!!'
            self.connDeferred.callback("")
        else:
            # make connection
            self.connMethod()
        return self.connDeferred

    def shutDown(self):
        """Shut down prodecure for this socket. Returns a Deferred.  
        @return a Deferred, or a fired Deferred

        If the socket is already shut down, the Deferred returned from this method comes 'calledback'.
        If the socket is not closed, the deferred is fired once the socket.state == disConnState
        **So code handling this methods should use maybeDeferred**
        """
        if self.state == self.disConnState:
            self.disConnDeferred.callback("")
        else:
            self.disConnMethod()
        return self.disConnDeferred

    def stateCallback(self, foo=None):
        """ This callback added to the stateCallback of the socket.
            @param[in] foo passed via callback, ignored here
        """
        if self.state == self.connState:
            self.connDeferred.callback("")
        elif self.state == self.disConnState:
            self.disConnDeferred.callback("")

class ServerConn(object):
    """Note, this function may be completely unnecessary because servers start
    themselves upon construction...
    """
    def __init__(self, server):
        """ Creates a callable for jump-starting a server listening
            @param[in] server: a RO/Twisted Server
        """
        self.server = server
    def __call__(self):
        """Begin the server listening, and set appropriate callbacks, 
        this was stolen from actual code in the constructor of RO.TwistedSocket.Server
        """
        self.server._endpointDeferred = self.server._endpoint.listen(_SocketProtocolFactory(self.server._newConnection))
        setCallbacks(self.server._endpointDeferred, self.server._listeningCallback, self.server._connectionLost)    


class Commander(object):
    def __init__(self, port):
        isReady = False # dispatcher is connected
        pass

    def startUp(self):
        pass

    def shutDown(self):
        pass

class CommunicationChain(object):
    def __init__(self):
        """Define a chain of servers and clients, to be started up and closed in the correct 
        order.
        """
        self.listeners = []
        self.connectors = []

    def walkChain(self, begOrEnd):
        """Startup or shut down the chain.
        @param[in] begOrEnd: string, either 'startUp', or 'shutDown' these are also 
            methods defined on listeners and connectors which themselves return deferreds
        @return a Deferred, which is calledback when the chain walk is complete

        Step 1: Listeners are started first and simultaneously.  After all listeners are ready,
        Step 2: all connectors are started up simultaneously. 
        --or--
        Step 1: Connectors are killed first and simultaneously.  After all connectors are dead,
        Step 2: all listeners are killed simultaneously.      

        Only after Step 2 is completely finished will the returned Deferred object fired.
        """

        if begOrEnd not in ["startUp", "shutDown"]:
            raise RuntimeError("walkChain input string must be either 'startUp' or 'shutDown'")
        startUp = begOrEnd == "startUp"
        ## this will fire only after listeners then connectors have been fully started or closed
        fireWhenReady = Deferred()
        deferredSequence = Deferred()
        def done(foo):
            """@param[in] foo: passed via callback, ignored
            """
            deferredSequence = None # paranoia
            foo = None # paranoia
            fireWhenReady.callback("here we go")
        def doConnectors(foo):
            """@param[in] foo: passed via callback, ignored
            """
            foo = None # paranoia
            # calls startUp or shutDown on each connector, gathers and returns all the (likely) Deferred(s) together
            return maybeDeferred(gatherResults, [maybeDeferred(getattr(connector, begOrEnd)) for connector in self.connectors])
        def doListeners(foo):
            """@param[in] foo: passed via callback, ignored
            """
            foo = None # paranoia
            # calls startUp or shutDown on each listener, gathers and returns all the (likely) Deferred(s) together
            return maybeDeferred(gatherResults, [maybeDeferred(getattr(listener, begOrEnd)) for listener in self.listeners])
        if startUp:
            # start listeners before connectors
            deferredSequence.addCallback(doListeners) 
            deferredSequence.addCallback(doConnectors)
        else:
            # we are shutting down, close connectors before listeners
            deferredSequence.addCallback(doConnectors) 
            deferredSequence.addCallback(doListeners)    
        deferredSequence.addCallback(done)
        deferredSequence.callback("Start")
        return fireWhenReady

    def startUp(self):
        """Start up the connection chain
        """
        return self.walkChain("startUp")

    def shutDown(self):
        """Close down cleanly all communication sockets, in a way that keeps 
        twisted trial tests happy.
        """
        return self.walkChain("shutDown")

    def addActor(self, actor):
        ## overwrite any hard-coded device ports???
        """Add an actor, and its respective socket entities to the listeners/connectors lists
        @param[in] actor: a TwistedActor
        """
        self.listeners.append(
            SocketDeferredWrapper(
                socketObj = actor.server,
                connMethod = ServerConn(actor.server),
                disConnMethod = actor.server.close,
                connState = actor.server.Listening,
                disConnState = actor.server.Closed,
            )
        )
        for dev in actor.dev.nameDict.values():
            self.connectors.append(
                SocketDeferredWrapper(
                    socketObj = dev.conn,
                    connMethod = dev.conn.connect,
                    disConnMethod = dev.conn.disconnect,
                    connState = dev.conn.Connected,
                    disConnState = dev.conn.Disconnected,
                )
            )

    def addFactory(self, factory):
        pass

    def addCommander(self):
        pass
