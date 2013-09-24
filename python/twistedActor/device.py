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
import os.path

import RO.Comm.Generic
RO.Comm.Generic.setFramework("twisted")
from RO.AddCallback import safeCall, BaseMixin
from RO.Comm.TCPConnection import TCPConnection
from RO.StringUtil import quoteStr, strFromException
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

        @param[in] name      a short name to identify the device
        @param[in] conn      a connection to the device; see below for details
        @param[in] cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        @param[in] callFunc  function to call when state of device changes, or None if none;
                    additional functions may be added using addCallback
        @param[in] cmdClass  class for commands for this device

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

    def basicInit(self, userCmd=None, callFunc=None):
        """Basic initialization

        @param[in] callFunc: callback function: function to call when command succeeds or fails, or None;
            if specified it receives one argument: a device command
        @param[in] userCmd: user command that tracks this command, if any

        subclasses must override; typically this merely calls startCmd with a suitable command string
        """
        raise NotImplementedError()

    def getStatus(self, userCmd=None, callFunc=None):
        """Get status

        @param[in] callFunc: callback function: function to call when command succeeds or fails, or None;
            if specified it receives one argument: a device command
        @param[in] userCmd: user command that tracks this command, if any

        subclasses must override; typically this merely calls startCmd with a suitable command string
        """
        raise NotImplementedError()

    def init(self, filePath=None, userCmd=None, callFunc=None):
        """Initialize the device

        Call basicInit
        Send a list of commands, if provided
        Call getStatus

        If any command in cmdList fails then call callFunc based on the failed command, but also call getStatus
        to try to update status.

        @param[in] filePath: path to a file containing commands to send after basicInit succeeds.
            Warn but continue if file not found.
        @param[in] callFunc: callback function: function to call when command succeeds or fails, or None;
            if specified it receives one argument: a device command
        @param[in] userCmd: user command that tracks this command, if any
        """
        def finishUp(devCmd, textMsg=None):
            """Finish the command by calling the callback function with the final devCmd
            """
            if textMsg:
                self.writeToUsers("w", "Text=%s" % (quoteStr(textMsg),), cmd=userCmd)
            if callFunc:
                safeCall(callFunc, devCmd)
            if userCmd:
                userCmd.setState(state=devCmd.state, textMsg=devCmd.textMsg, hubMsg=devCmd.hubMsg)

        def initCallback(devCmd):
            if devCmd.didFail:
                finishUp(devCmd=devCmd)

            cmdList = []
            if filePath:
                try:
                    with file(filePath, "rU") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            if line[0] == "#":
                                continue
                            cmdList.append(line)
                except Exception, e:
                    msgStr = "Error reading %s init file %s: %s" % (self.name, filePath, strFromException(e))
                    self.writeToUsers("w", "Text=%s" % (quoteStr(msgStr),))

            if cmdList:
                def fileCallback(devCmd):
                    if devCmd.didFail:
                        finishUp(devCmd=devCmd, textMsg="Skipping remaining file commands")
                        self.getStatus() # don't wait for this to complete
                    else:
                        self.getStatus(callFunc=finishUp)
                self.startCmdList(cmdList, callFunc=fileCallback)
            else:
                self.getStatus(callFunc=finishUp)

        self.basicInit(callFunc=initCallback)
            
    def writeToUsers(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to all users.
        
        This is overridden by Actor when the device is added to the actor
        """
        raise NotImplementedError("Cannot report msgCode=%r; msgStr=%r" % (msgCode, msgStr))
    
    def handleReply(self, replyStr):
        """Handle a line of output from the device. Called whenever the device outputs a new line of data.

        @param[in] replyStr  the reply, minus any terminating \n
        
        This is the heart of the device interface and an important part of what makes
        each device unique. As such, it must be specified by the subclass.
        
        Tasks include:
        - Parse the reply
        - Manage pending commands
        - Update the device model representing the state of the device
        - Output state data to users (if state has changed)
        - Call the command callback
        
        @warning: must be defined by the subclass
        """
        raise NotImplementedError()

    def startCmd(self, cmdStr, callFunc=None, userCmd=None):
        """Start a new command.

        @param[in] cmdStr: command string
        @param[in] callFunc: callback function: function to call when command succeeds or fails, or None;
            if specified it receives one argument: a device command
        @param[in] userCmd: user command that tracks this command, if any

        @return devCmd: the device command that was started (and may already have failed)
        """
        devCmd = self.cmdClass(cmdStr, userCmd=userCmd, callFunc=callFunc, dev=self)
        if not self.conn.isConnected:
            devCmd.setState(devCmd.Failed, textMsg="%s %s failed: not connected" % (self.name, cmdStr))
        else:
            fullCmdStr = devCmd.fullCmdStr
            try:
                self.conn.writeLine(fullCmdStr)
            except Exception, e:
                devCmd.setState(devCmd.Failed, textMsg="%s %s failed: %s" % (self.name, cmdStr, strFromException(e)))
        
        return devCmd

    def startCmdList(self, cmdList, callFunc=None, userCmd=None):
        """Start a sequence of commands; if a command fails then subsequent commands are ignored

        @param[in] cmdList: a sequence of command strings
        @param[in] callFunc: callback function: function to call when the final command is done
            or when a command fails (in which case subsequent commands are ignored), or None;
            if specified it receives one argument: the final device command that was executed
            (if a command fails, it will be the one that failed)
        @param[in] userCmd: user command that tracks this list of commands, if any

        @return devCmd: the first device command that was started (and may already have failed)
        """
        locCmdList = cmdList[:]

        def cmdListDone(devCmd):
            """Finish the sequence of commands by calling callFunc and setting state of userCmd

            @param[in] devCmd: the last device command executed (final device command of the list if all commands succeeded,
                else the first device command that failed)
            @raise RuntimeError if not devCmd.isDone
            """
            if not devCmd.isDone:
                raise RuntimeError("cmdListDone should only be called when devCmd is done")

            if callFunc:
                safeCall(callFunc(devCmd))

            if userCmd:
                if devCmd.didFail:
                    userCmd.setState(userCmd.Failed, textMsg=devCmd.textMsg, hubMsg=devCmd.hubMsg)
                else:
                    userCmd.setState(userCmd.Done)

        def cmdCallback(devCmd):
            """Device command callback for running a list of commands

            If the command failed, stop and fail the userCmd (if any)
            If the command succeeded then execute the next command
            If there are no more command to execute, then conclude the userCmd (if any)

            @param[in] devCmd: device command, or None to start the first command
            """
            if not devCmd.isDone:
                return
            if devCmd and devCmd.didFail:
                cmdListDone(devCmd)
            else:
                if locCmdList:
                    cmdStr = locCmdList.pop(0)
                    return self.startCmd(cmdStr, callFunc=cmdCallback)
                else:
                    cmdListDone(devCmd)

        return cmdCallback(None)


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
        
        @param[in] name      a short name to identify the device
        @param[in] host      IP address
        @param[in] port      port
        @param[in] cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        @param[in] callFunc  function to call when state of device changes, or None if none;
                    additional functions may be added using addCallback.
                    Note that device state callbacks is NOT automatically called
                    when the connection state changes; register a callback with "conn" for that task.
        @param[in] cmdClass  class for commands for this device
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

        @param[in] sock  the socket (ignored)
        @param[in] line  the reply, missing the final \n     
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
        
        @param[in] name      a short name to identify the device
        @param[in] host      IP address
        @param[in] port      port
        @param[in] modelName the name of the model in the actorkeys package; if none then use name
        @param[in] cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        @param[in] callFunc  function to call when state of device changes, or None if none;
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
            cmdClass = cmdClass,
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
        
        @param[in] cmdStr: the command; no terminating \n wanted
        @param[in] callFunc: a callback function; it receives one argument: a CmdVar object
        @param[in] userCmd: user command that tracks this command, if any
        @param[in] timeLim: maximum time before command expires, in sec; 0 for no limit
        @param[in] timeLimKeyVar: a KeyVar specifying a delta-time by which the command must finish
            this KeyVar must be registered with the message dispatcher.
        @param[in] timeLimKeyInd: the index of the time limit value in timeLimKeyVar; defaults to 0;
            ignored if timeLimKeyVar is None.
        @param[in] abortCmdStr: a command string that will abort the command.
            Sent to the actor if abort is called and if the command is executing.
        @param[in] keyVars: a sequence of 0 or more keyword variables to monitor for this command.
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
        devCmdVar = self.cmdClass(
            cmdVar = cmdVar,
            userCmd = userCmd,
            callFunc = callFunc,
            dev = self,
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
        
        @param[in] devList: a collection of devices (instances of device.Device).
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
