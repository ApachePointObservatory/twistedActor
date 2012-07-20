"""Base classes for interface to devices controlled by the Tcl Actor
"""
__all__ = ["Device", "TCPDevice"]

import RO.Comm.Generic
RO.Comm.Generic.setFramework("twisted")
from RO.AddCallback import BaseMixin
from RO.Comm.TCPConnection import TCPConnection
from .command import DevCmd

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

    Inputs:
    - name      a short name to identify the device
    - conn      a connection to the device; more information below
    - cmdInfo   a list of (user command verb, device command verb, help string)
                for commands that are be sent directly through to this device.
                Specify None for the device command verb if it is the same as the user command verb
                (high recommended as it is much easier for the user to figure out what is going on)
    - callFunc  function to call when state of device changes;
                note that it is NOT called when the connection state changes;
                register a callback with "conn" for that task.
    - actor actor that contains this device; this gives access to writeToUsers
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
    and this is traditional:
    - readLine()
    """
    def __init__(self,
        name,
        conn,
        cmdInfo = None,
        callFunc = None,
        actor = None,
        cmdClass = DevCmd,
    ):
        BaseMixin.__init__(self)
        self.name = name
        self.cmdInfo = cmdInfo or()
        self.connReq = (False, None)
        self.conn = conn
        self.pendCmdDict = {} # key=locCmdID, value=cmd
        self.actor = actor
        self.cmdClass = cmdClass
        if callFunc:
            self.addCallback(callFunc, callNow=False)        
    
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

    def newCmd(self, cmdStr, callFunc=None, userCmd=None):
        """Start a new command.
        """
        cmd = self.cmdClass(cmdStr, userCmd=userCmd, callFunc=callFunc)
        
        self.pendCmdDict[cmd.locCmdID] = cmd
        fullCmdStr = cmd.getCmdWithID()
        try:
            #print "Device.sendCmd writing %r" % (fullCmdStr,)
            self.conn.writeLine(fullCmdStr)
        except Exception, e:
            cmd.setState(isDone=True, isOK=False, textMsg=str(e))


class TCPDevice(Device):
    """TCP-connected device.
    
    Inputs:
    - name      a short name to identify the device
    - addr      IP address
    - port      port
    - cmdInfo   a list of (user command verb, device command verb, help string)
                for commands that are be sent directly through to this device.
                Specify None for the device command verb if it is the same as the user command verb
                (high recommended as it is much easier for the user to figure out what is going on)
    - callFunc  function to call when state of device changes;
                note that it is NOT called when the connection state changes;
                register a callback with "conn" for that task.
    - actor actor that contains this device; this gives access to writeToUsers
    - cmdClass  class for commands for this device
    """
    def __init__(self,
        name,
        addr,
        port = 23,
        cmdInfo = None,
        callFunc = None,
        actor = None,
        cmdClass = DevCmd,
    ):
        Device.__init__(self,
            name = name,
            cmdInfo = cmdInfo,
            conn = TCPConnection(
                host = addr,
                port = port,
                readCallback = self._readCallback,
                readLines = True,
            ),
            callFunc = callFunc,
            actor = actor,
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
