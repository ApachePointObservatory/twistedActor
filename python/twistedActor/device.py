"""Base classes for interface to devices controlled by the Tcl Actor

A Device is an interface/driver/model for one device controlled by an Actor.
It is responsible for sending commands to the device and keeping track of the state of the device.
The Device also enforces any special requirements for safe use of the underlying device, such as
making sure only one command is executed at a time.

For each device an Actor commands you will typically have to make a Device for it as subclass
of one of these classes. Much of the work of writing an Actor involves writing the appropriate
Device classes.
"""
__all__ = ["Device", "TCPDevice", "ActorDevice", "DeviceCollection"]

from collections import OrderedDict
import RO.Comm.Generic
RO.Comm.Generic.setFramework("twisted")
from RO.AddCallback import BaseMixin
from RO.Comm.TCPConnection import TCPConnection
import opscore.actor
from .command import DevCmd, DevCmdVar

class Device(BaseMixin):
    """Device interface.
    
    Data includes information necessary to connect to this device
    and a list of commands handled directly by this device.
    
    Tasks include:
    - Send commands to the device
    - Parse all replies and use that information to:
      - Output appropriate data to the users
      - Upate a device model, if one exists
      - Call callbacks associated with the command, if any
        
    Attributes include:
    connReq: a tuple of:
    - is connection wanted?
    - the user command that triggered this request, or None if none
    
    When this device is added to an Actor then it gains the actor's writeToUsers method.
    """
    def __init__(self,
        name,
        conn,
        cmdInfo = None,
        callFunc = None,
        cmdClass = DevCmd,
    ):
        """Construct a Device

        Inputs:
        - name      a short name to identify the device
        - conn      a connection to the device; see below for details
        - cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        - callFunc  function to call when state of device changes, or None if none;
                    additional functions may be added using addCallback
        - cmdClass  class for commands for this device

        conn is an object implementing these methods:
        - connect()
        - disconnect()
        - addStateCallback(callFunc, callNow=True)
        - getFullState(): Returns the current state as a tuple:
            - state: a numeric value; named constants are available
            - stateStr: a short string describing the state
            - reason: the reason for the state ("" if none)
        - isConnected(): return True if connected, False otherwise
        - isDone(): return True if fully connected or disconnected
        - addReadCallback(callFunc, callNow=True)
        - writeLine(str)
        - readLine()
        """
        BaseMixin.__init__(self)
        self.name = name
        self.cmdInfo = cmdInfo or()
        self.connReq = (False, None)
        self.conn = conn
        self.cmdClass = cmdClass
        if callFunc:
            self.addCallback(callFunc, callNow=False)
    
    def writeToUsers(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to all users.
        
        This is overridden by Actor when the device is added to the actor
        """
        raise NotImplementedError("Cannot report msgCode=%r; msgStr=%r" % (msgCode, msgStr))
    
    def handleReply(self, replyStr):
        """Handle a line of output from the device.

        Inputs:
        - replyStr  the reply, minus any terminating \n
        
        Called whenever the device outputs a new line of data.
        
        This is the heart of the device interface and what makes
        each device unique. As such, it must be specified by the subclass.
        
        Tasks include:
        - Parse the reply
        - Manage pending commands
        - Update the device model representing the state of the device
        - Output state data to users (if state has changed)
        - Call the command callback
        
        Warning: this must be defined by the subclass
        """
        raise NotImplementedError()

    def startCmd(self, cmdStr, callFunc=None, userCmd=None):
        """Start a new command.
        """
        devCmd = self.cmdClass(cmdStr, userCmd=userCmd, callFunc=callFunc)
        
        fullCmdStr = devCmd.fullCmdStr
        try:
            #print "Device.sendCmd writing %r" % (fullCmdStr,)
            self.conn.writeLine(fullCmdStr)
        except Exception, e:
            devCmd.setState(isDone=True, isOK=False, textMsg=str(e))
        
        return devCmd


class TCPDevice(Device):
    """TCP-connected device.
    """
    def __init__(self,
        name,
        host,
        port = 23,
        cmdInfo = None,
        callFunc = None,
        cmdClass = DevCmd,
    ):
        """Construct a TCPDevice
        
        Inputs:
        - name      a short name to identify the device
        - host      IP address
        - port      port
        - cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        - callFunc  function to call when state of device changes, or None if none;
                    additional functions may be added using addCallback.
                    Note that device state callbacks is NOT automatically called
                    when the connection state changes; register a callback with "conn" for that task.
        - cmdClass  class for commands for this device
        """
        Device.__init__(self,
            name = name,
            cmdInfo = cmdInfo,
            conn = TCPConnection(
                host = host,
                port = port,
                readCallback = self._readCallback,
                readLines = True,
            ),
            callFunc = callFunc,
            cmdClass = cmdClass,
        )
    
    def _readCallback(self, sock, replyStr):
        """Called whenever the device has returned a reply.
        Inputs:
        - sock  the socket (ignored)
        - line  the reply, missing the final \n     
        """
        #print "TCPDevice._readCallback(sock, replyStr=%r)" % (replyStr,)
        self.handleReply(replyStr)


class ActorDevice(TCPDevice):
    """A device that obeys the APO standard actor interface
    """
    def __init__(self,
        name,
        host,
        port = 23,
        modelName = None,
        cmdInfo = None,
        callFunc = None,
        cmdClass = DevCmdVar,
    ):
        """Construct an ActorDevice
        
        Inputs:
        - name      a short name to identify the device
        - host      IP address
        - port      port
        - modelName the name of the model in the actorkeys package; if none then use name
        - cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        - callFunc  function to call when state of device changes, or None if none;
                    additional functions may be added using addCallback.
                    Note that device state callbacks is NOT automatically called
                    when the connection state changes; register a callback with "conn" for that task.
        """
        TCPDevice.__init__(self,
            name = name,
            host = host,
            port = port,
            cmdInfo = cmdInfo,
            callFunc = callFunc,
        )
        if modelName is None:
            modelName = name
        self.dispatcher = opscore.actor.ActorDispatcher(
            name = modelName,
            connection = self.conn,
        )
    
    def startCmd(self,
        cmdStr,
        callFunc = None,
        userCmd = None,
        timeLimit = 0,
        timeLimKeyVar = None,
        timeLimKeyInd = 0,
        abortCmdStr = None,
        keyVars = None,
    ):
        """Start a new command.
        
        Inputs:
        - cmdStr: the command; no terminating \n wanted
        - callFunc: a callback function; it receives one argument: a CmdVar object
        - userCmd: user command that will track this command; None if none
        - timeLim: maximum time before command expires, in sec; 0 for no limit
        - timeLimKeyVar: a KeyVar specifying a delta-time by which the command must finish
            this KeyVar must be registered with the message dispatcher.
        - timeLimKeyInd: the index of the time limit value in timeLimKeyVar; defaults to 0;
            ignored if timeLimKeyVar is None.
        - abortCmdStr: a command string that will abort the command.
            Sent to the actor if abort is called and if the command is executing.
        - keyVars: a sequence of 0 or more keyword variables to monitor for this command.
            Any data for those variables that arrives IN RESPONSE TO THIS COMMAND is saved
            and can be retrieved using cmdVar.getKeyVarData or cmdVar.getLastKeyVarData.
        """
        cmdVar = opscore.actor.CmdVar(
            cmdStr = cmdStr,
            timeLim = timeLimit,
            timeLimKeyVar = timeLimKeyVar,
            timeLimKeyInd = timeLimKeyInd,
            abortCmdStr = abortCmdStr,
            keyVars = keyVars,
        )
        devCmdVar = DevCmdVar(
            cmdVar = cmdVar,
            userCmd = userCmd,
            callFunc = callFunc
        )
        self.dispatcher.executeCmd(cmdVar)
        return devCmdVar

class DeviceCollection(object):
    """A collection of devices that provides easy access
    
    Access is as follows:
    - .<name> for the device named <name>, e.g. .foo for the device "foo"
    - .nameDict contains a collections.OrderedDict of devices in alphabetical order by device name
    """
    def __init__(self, devList):
        """Construct a DeviceCollection
        
        Inputs:
        - devList: a collection of devices (instances of device.Device).
            Required attributes are:
            - name: name of device
            - connection: connection used by device
        
        Raise RuntimeError if any device name starts with _
        Raise RuntimeError if any two devices have the same name
        Raise RuntimeError if any device name matches a DeviceCollection attribute (e.g. nameDict or getFromConnection)
        """
        self.nameDict = OrderedDict()
        self._connDict = dict()
        tempNameDict = dict()
        for dev in devList:
            if dev.name.startswith("_"):
                raise RuntimeError("Illegal device name %r; must not start with _" % (dev.name,))
            if hasattr(self, dev.name):
                raise RuntimeError("Device name: %r matches existing device name or DeviceCollection attribute" % (dev.name,))
            connId = id(dev.conn)
            if connId in self._connDict:
                existingDev = self._connDict[connId]
                raise RuntimeError("A device already exists that uses this connection; new device=%r; old device=%r" % \
                    (dev.name, existingDev.name))
            self._connDict[connId] = dev
            setattr(self, dev.name, dev)
            tempNameDict[dev.name] = dev
        for name in sorted(tempNameDict.keys()):
            self.nameDict[name] = tempNameDict[name]
    
    def getFromConnection(self, conn):
        """Return the device that has this connection
        
        Raise KeyError if not found
        """
        return self._connDict[id(conn)]
