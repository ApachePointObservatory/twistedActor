"""A convenient framework for testing actors, devices etc which rely on sending asynchronous commands
and responses over network sockets
"""
__all__ = ["getOpenPort", "CommunicationChain", "Commander"]
import RO.Comm.Generic
RO.Comm.Generic.setFramework("twisted")
#from twisted.trial.unittest import TestCase
from twisted.internet.defer import Deferred, gatherResults, maybeDeferred
#from twistedActor import Actor, TCPDevice
from RO.Comm.TwistedSocket import setCallbacks, _SocketProtocolFactory
from RO.Comm.TCPConnection import TCPConnection
from opscore.actor import ActorDispatcher, CmdVar
import socket
from collections import OrderedDict
from twisted.internet import reactor

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

class DevConnWrapper(object):
    def __init__(self, dev):
        """Wrap a device, expose connection and disconnection methods
        @param[in] dev: a twistedActor Device
        """
        self.dev = dev

    def startUp(self):
        print 'starting device conn'
        connDev = self.dev.connect()
        return connDev.deferred

    def shutDown(self):
        print 'stoping device conn'
        connDev = self.dev.disconnect()
        return connDev.deferred

class CommanderConnWrapper(object):
    def __init__(self, commander):
        """Wrap a commanders TCP connection
        @param[in] commander: a commander object
        """
        self.commander = commander

    def startUp(self):
        print 'starting commander conn'
        return self.commander.dispatcher.connection.connect()

    def shutDown(self):
        print 'stopping commander conn'
        return self.commander.dispatcher.connection.disconnect()    

class ActorServerWrapper(object):
    def __init__(self, actor):
        """Wrap an actor, expose startUp and shutDown
        @param[in] actor: an actor instance
        """
        self.actor = actor

    def startUp(self):
        print 'starting actor server'
        return self.actor.server.getReadyDeferred()

    def shutDown(self):
        print 'stoping actor server'
        return self.actor.server.close()
  

class CmdCallback(object):
    def __init__(self, deferred):
        """Call a deferred when a command is finished
        @param[in] deferred: a Deferred object to be fired once
            the command finishes
        """
        self.deferred = deferred
    
    def __call__(self, cmd):
        """If the executing command is finished fire the deferred
        @param[in] cmd, an opscore CmdVar passed via callback
        """
        if cmd.isDone:
            deferred, self.deferred = self.deferred, None
            deferred.callback("done")

class Commander(object):
    def __init__(self, port, modelName):
        """Construct a commander.  Sends commands via opscore protocols to a port
        @param[in] port: port to connect and send commands to
        @param[in] modelName: name of a model which must reside in the actorkeys package


        @note could possibly use manageCommands.CommandQueue but I believe that
        is overkill, with the added complexity of the queue setup and definitions
        """
        self.modelName = modelName
        conn = TCPConnection(
            host = 'localhost',
            port = port,
            readLines = True,
            name = "Commander",
        )

        self.dispatcher = ActorDispatcher(
            name = self.modelName,
            connection = conn,
#            logFunc = showReply,
        )
        self.cmdResults = [] ## command results collected here
        self.cmdsToRun = [] ## list, each element is [cmdStr, callFunc]. replace with queue?
        self.currCmdInd = 0 ## which index on command stack are we currently at?
        self.currExeCmd = None
        self.cmdsFinishedDeferred = Deferred() ## returned from self.runCmds

    @property
    def endCmdInd(self):
        return len(self.cmdsToRun)

    def runNextCmd(self, foo=None):
        """ Turn a string into a command var and execute it.
        @param[in] foo: dummy parameter, for callback
        @return d or None, a deferred to fire once the command is done
        """
        try:
            cmdStr = self.cmdsToRun[self.currCmdInd][0]    
        except IndexError:
            # we must be done with all commands
            self.cmdsFinishedDeferred.callback("All Done!")
            return
        else:
            d = Deferred()
            d.addCallback(self.recordCmdResults) # when this command done, record results
            d.addCallback(self.runNextCmd) # after results recorded, automatically start the next one
            cmdVar = CmdVar(
                actor = self.modelName,
                cmdStr = cmdStr,
                callFunc = CmdCallback(d),
            ) 
            self.dispatcher.executeCmd(cmdVar)
            self.currExeCmd = cmdVar
            return d   

    def recordCmdResults(self, foo=None):
        """After command finishes, verify everything worked as expected
        @param[in] foo: dummy param for callback
        """
        cmdOK = not self.currExeCmd.didFail
        modelOK = self.cmdsToRun[self.currCmdInd][1](self.dispatcher.model)
        self.currExeCmd = None
        self.currCmdInd += 1
        self.cmdResults.append([cmdOK, modelOK])

    def defineCmdAndResponse(self, cmdStr, callFunc):
        """Define a command string to be dispatched and provide the expected
        end result upon command completion.

        @param[in] cmdStr: the command string
        @param[in] callFunc: callable, expectes a model instance 
            as a sole parameter must return a boolean 
            (True for pass, False for Fail)

         """
        self.cmdsToRun.append([cmdStr, callFunc])

    def runCmds(self):
        """Run the command stack, in an orderly fashion
        """
        self.runNextCmd()
        return self.cmdsFinishedDeferred

class CommunicationChain(object):
    def __init__(self):
        """Define a chain of servers and clients, to be started up and closed in the correct 
        order.
        """
        self.listeners = []
        self.connectors = []
        self.commander = None

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
            print 'done', begOrEnd
            # global deferredSequence
            # deferredSequence = None # paranoia
            # foo = None # paranoia
            fireWhenReady.callback("here we go")
        def doConnectors(foo):
            """@param[in] foo: passed via callback, ignored
            """
            print "connect", begOrEnd
            # foo = None # paranoia
            # calls startUp or shutDown on each connector, gathers and returns all the (likely) Deferred(s) together
            return maybeDeferred(gatherResults, [maybeDeferred(getattr(connector, begOrEnd)) for connector in self.connectors])
          
        def doListeners(foo):
            """@param[in] foo: passed via callback, ignored
            """
            print "listen", begOrEnd
            # foo = None # paranoia
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
            ActorServerWrapper(actor)
        )
        for dev in actor.dev.nameDict.values():
            self.connectors.append(
                DevConnWrapper(dev)
            )

    def addServerFactory(self, factory, port):
        self.listeners.append(TwistedFactoryServerWrapper(factory, port))

    def addCommander(self, commander):
        """Add a commander to the chain.
        @param[in] commander: an instance of a Commander object
        """
        self.connectors.append(
            CommanderConnWrapper(commander)
        )
        self.commander = commander
   

################### old code pre-russells changes###############################
################################################################################

# class ServerConn(object):
#     """Note, this function may be completely unnecessary because servers start
#     themselves upon construction...
#     """
#     def __init__(self, server):
#         """ Creates a callable for jump-starting a server listening
#             @param[in] server: a RO/Twisted Server
#         """
#         self.server = server
#     def __call__(self):
#         """Begin the server listening, and set appropriate callbacks, 
#         this was stolen from actual code in the constructor of RO.TwistedSocket.Server
#         """
#         self.server._endpointDeferred = self.server._endpoint.listen(_SocketProtocolFactory(self.server._newConnection))
#         setCallbacks(self.server._endpointDeferred, self.server._listeningCallback, self.server._connectionLost)  

# class NewDeferredWrapper(object):
#     def __init__(self, socketObj, connMethod, disConnMethod, timeLim=2):
#         """Wrapper for a socket-type object (connection or server) that specifically handles 
#         (asynchronous) startUp and shutDown procedures.

#         @param[in] socketObj: A Twisted-RO TCPServer, or TCPConnection
#         @param[in] connMethod: a callable, will start connecting or listening, might return a deferred
#         @param[in] disConnMethod: a callable, will kill connection or stop listening, might return a deferred
#         @param[in] timLim: a time limit for connections/disconnections
#         This object contains important methods: startUp and shutDown.  These will start or stop 
#         connections/servers and, will return Deferred objects unless they are already
#         in the desired state. In this case they will return a fired Deferred object
#         """
#         self.socketObj = socketObj
#         self.connMethod = connMethod
#         self.disConnMethod = disConnMethod

#     def startUp(self):
#         return getattr(self.socketObj, self.connMethod)()

#     def shutDown(self):
#         return getattr(self.socketObj, self.disConnMethod)()

# class SocketDeferredWrapper(object):
#     def __init__(self, socketObj, connMethod, disConnMethod, connState, disConnState):
#         """Wrapper for a socket-type object (connection or server) that specifically handles 
#         (asynchronous) startUp and shutDown procedures.

#         @param[in] socketObj: A Twisted-RO TCPServer, or TCPConnection
#         @param[in] connMethod: a callable, will start connecting or listening
#         @param[in] disConnMethod: a callable, will kill connection or stop listening
#         @param[in] connState: state (via socketObj.state) that signals sucessfull connection or listening
#         @param[in] disConnState: state (via socketObj.state) that signals complete shut down of connection or listening

#         This object contains important methods: startUp and shutDown.  These will start or stop 
#         connections/servers and, will return Deferred objects unless they are already
#         in the desired state. In this case they will return a fired Deferred object
#         """
#         self.socketObj = socketObj
#         self.connDeferred = Deferred()
#         self.disConnDeferred = Deferred()
#         try:
#             # connections have addStateCallback
#             self.socketObj.addStateCallback(stateCallback = self.stateCallback)
#         except:
#             #servers have setStateCallback
#            self.socketObj.setStateCallback(callFunc=self.stateCallback)
#         if False in [callable(connMethod), callable(disConnMethod)]:
#             raise RuntimeError("SocketDeferredWrapper requires callable connection/disconnection inputs")
#         self.connMethod = connMethod
#         self.disConnMethod = disConnMethod
#         self.connState = connState
#         self.disConnState = disConnState
#         self.disConnDeferred = Deferred()

#     @property
#     def state(self):
#         """@return state of socket
#         """
#         return self.socketObj.state

#     def startUp(self):
#         """Startup prodecure for this socket. Returns a Deferred.  

#         @return a Deferred, or a fired Deferred

#         If the socket is already ready, the Deferred returned from this method comes pre-fired ("called back").
#         If the socket is not ready, the deferred is fired once the socket.state == connState
#         ***So code handling this methods should use maybeDeferred***
#         """
#         print self.name, ' starting up socket'
#         if self.state == self.connState:
#             self.connDeferred.callback("")
#         else:
#             # make connection
#             self.connMethod()
#         return self.connDeferred

#     def shutDown(self):
#         """Shut down prodecure for this socket. Returns a Deferred.  
#         @return a Deferred, or a fired Deferred

#         If the socket is already shut down, the Deferred returned from this method comes 'calledback'.
#         If the socket is not closed, the deferred is fired once the socket.state == disConnState
#         **So code handling this methods should use maybeDeferred**
#         """
#         print self.name, ' shutting down socket'
#         if self.state == self.disConnState:
#             self.disConnDeferred.callback("")
#         else:
#             self.disConnMethod()
#         return self.disConnDeferred

#     def stateCallback(self, foo=None):
#         """ This callback added to the stateCallback of the socket.
#             @param[in] foo passed via callback, ignored here
#         """
#         if self.state == self.connState:
#             self.connDeferred.callback("")
#         elif self.state == self.disConnState:
#             self.disConnDeferred.callback("")

# class ROServerWrapper(SocketDeferredWrapper):
#     def __init__(self, server):
#         """Wrap up a server socket for ease of handling by a CommunicationChain.
#         @param[in] server: a RO server instance
#         """
#         self.name = 'roServer'
#         SocketDeferredWrapper.__init__(self,
#             socketObj = server,
#             connMethod = ServerConn(server),
#             disConnMethod = server.close,
#             connState = server.Listening,
#             disConnState = server.Closed,
#         )

# class ConnectionWrapper(SocketDeferredWrapper):
#     def __init__(self, conn):
#         """Wrap up a (TCP) connection socket for ease of handling by a CommunicationChain
#         @param[in] conn: a RO TCPConnection object
#         """
#         self.name = 'connection'
#         SocketDeferredWrapper.__init__(self,
#             socketObj = conn,
#             connMethod = conn.connect,
#             disConnMethod = conn.disconnect,
#             connState = conn.Connected,
#             disConnState = conn.Disconnected,
#         )

# class CommanderWrapper(SocketDeferredWrapper):
#     def __init__(self, dispatcher):
#         """Wrap up an opscore dispatcher object
#         @param[in] commander: a obscore CmdKeyDispatcher instance
#         """ 
#         self.name = 'commander'
#         SocketDeferredWrapper.__init__(self,
#             socketObj = dispatcher.connection,
#             connMethod = dispatcher.connection.connect,
#             disConnMethod = dispatcher.connection.disconnect, #dispatcher includes other cleanup
#             connState = dispatcher.connection.Connected,
#             disConnState = dispatcher.connection.Disconnected,
#         )

# class NewDevDeferredWrapper(NewDeferredWrapper):
#     def __init__(self, device):
#         """Wrap a device, expose connection and disconnection deferreds
#         @param[in] device: a twistedActor device instance
#         """
#         NewDeferredWrapper.__init__(self, device, 'connect', 'disconnect')

#         def startUp(self):
#             connectDevice = getattr(self.socketObj, self.connMethod)()
#             return connectDevice.deferred

#         def shutDown(self):
#             connectDevice = getattr(self.socketObj, self.disConnMethod)()
#             return connectDevice.deferred

# class TwistedFactoryServerWrapper(object):
#     def __init__(self, factory, port):
#         """Expose setUp and tearDown methods for a twisted Factory server
#         @param[in] factory: an instance of the twisted factory
#         @param [in] port: a port to start the factory listening on 
#         """
#         self.factory = factory
#         self.port = port
#         self.portObj = None

#     def startUp(self):
#         """Start the server listening
#         """
#         print 'starting up factory server'
#         ## note: twisted documentation shows this is immediate (no deferred returned)
#         self.portObj = reactor.listenTCP(port=self.port, factory=self.factory)

#     def shutDown(self):
#         print 'shutting down factor server'
#         return self.portObj.stopListening()