
"""!Base classes for interface to devices controlled by the twisted actor

A Device is an interface/driver/model for one device controlled by an Actor.
It is responsible for sending commands to the device and keeping track of the state of the device.
The Device also enforces any special requirements for safe use of the underlying device, such as
making sure only one command is executed at a time.

For each device an Actor commands you will typically have to make a Device for it as subclass
of one of these classes. Much of the work of writing an Actor involves writing the appropriate
Device classes.
"""
from collections import OrderedDict

from opscore.RO.Comm import Generic
Generic.setFramework("twisted")
from opscore.RO.AddCallback import BaseMixin
from opscore.RO.Comm.TwistedTimer import Timer
from opscore.RO.Comm.TCPConnection import TCPConnection
from opscore.RO.StringUtil import quoteStr, strFromException
import opscore.actor

from .command import DevCmd, DevCmdVar, UserCmd, expandUserCmd
from .log import log

__all__ = ["Device", "TCPDevice", "ActorDevice", "DeviceCollection"]

class Device(BaseMixin):
    """!Device interface.

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
    DefaultTimeLim = 5 # default time limit, seconds; subclasses may override

    Connected = "Connected" # connected and init function finished
    Connecting = "Connecting"
    Disconnected = "Disconnected"
    Disconnecting = "Disconnecting"
    Failed = "Failed"
    _AllStates = frozenset((Connected, Connecting, Disconnected, Disconnecting, Failed))

    def __init__(self,
        name,
        conn,
        cmdInfo = None,
        callFunc = None,
        cmdClass = DevCmd,
    ):
        """!Construct a Device

        @param[in] name      a short name to identify the device
        @param[in] conn      a connection to the device; an RO.Conn.TCPDevice or similar; see below for details
        @param[in] cmdInfo   a list of (user command verb, device command verb, help string)
                    for user commands that are be sent directly to this device.
                    Specify None for the device command verb if it is the same as the user command verb
                    (strongly recommended as it is much easier for the user to figure out what is going on)
        @param[in] callFunc  function to call when state of device changes, or None if none;
                    additional functions may be added using addCallback
        @param[in] cmdClass  class for commands for this device

        conn is an RO.Conn.TCPDevice or object with these attributes (see RO.Comm.TCPConnection for descriptions):
        - connect()
        - disconnect()
        - isConnected
        - isDisconnected
        - isDone
        - didFail
        - state
        - addStateCallback(callFunc, callNow=True)
        - addReadCallback(callFunc, callNow=True)
        - writeLine(str)
        - readLine()
        """
        BaseMixin.__init__(self)
        self.name = name
        self.cmdInfo = cmdInfo or ()
        self.connReq = (False, None)
        self.conn = conn
        self.cmdClass = cmdClass
        self._state = self.Disconnected
        self._ignoreConnCallback = False # set during connection and disconnection
        self.conn.addStateCallback(self._connCallback)
        if callFunc:
            self.addCallback(callFunc, callNow=False)

    def connect(self, userCmd=None, timeLim=DefaultTimeLim):
        """!Connect the device and start init (on success)

        If already connected then simply set returned userCmd's state to userCmd.Done.

        @param[in] userCmd  user command (or None); if None a new one is generated
            to allow tracking the progress of this command
        @param[in] timeLim  maximum time before command expires, in sec; None for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one
        """
        log.info("%s.connect(userCmd=%s, timeLim=%s)" % (self, userCmd, timeLim))
        return ConnectDevice(dev=self, userCmd=userCmd, timeLim=timeLim).userCmd

    def disconnect(self, userCmd=None, timeLim=DefaultTimeLim):
        """!Start init and disconnect the device

        If already disconnected then simply set returned userCmd's state to userCmd.Done.

        @return userCmd: the specified userCmd or if that was None, then a new empty one
        """
        log.info("%s.disconnect(userCmd=%s, timeLim=%s)" % (self, userCmd, timeLim))
        return DisconnectDevice(dev=self, userCmd=userCmd, timeLim=timeLim).userCmd

    def cleanup(self):
        """!Release resources and halt pending processes

        Called when disconnecting (after disconnection begins)
        """
        pass

    def setState(self, state, reason=None):
        """!Set connection state
        """
        # print("%s.setState(state=%s, reason=%r)" % (self, state, reason))
        if state not in self._AllStates:
            raise RuntimeError("Unknown state=%r" % (state,))
        if self._state == state:
            return # ignore null state changes

        self._state = state
        if reason is not None:
            self.reason = reason
        self._doCallbacks()

    def writeToUsers(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """!Write a message to all users.

        This is overridden by Actor when the device is added to the actor
        """
        log.info("Device does not yet have access to writeToUsers: msgCode=%r; msgStr=%r" % (msgCode, msgStr))
        # print("msgCode=%r; msgStr=%r" % (msgCode, msgStr))

    def handleReply(self, replyStr):
        """!Handle a line of output from the device. Called whenever the device outputs a new line of data.

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

    def init(self, userCmd=None, timeLim=DefaultTimeLim, getStatus=True):
        """!Initialize the device and cancel all pending commands

        @param[in] userCmd  user command that tracks this command, if any
        @param[in] timeLim  maximum time before command expires, in sec; None for no limit
        @param[in] getStatus  if true then get status after init
        @return userCmd (a new one if the provided userCmd is None)

        @warning: must be defined by the subclass
        """
        raise NotImplementedError()

    @property
    def state(self):
        return self._state

    @property
    def didFail(self):
        """!Return True if device is connected (and init succeeded)
        """
        return self._state == self.Failed

    @property
    def isConnected(self):
        """!Return True if device is connected (and init succeeded)
        """
        return self._state == self.Connected

    @property
    def isDisconnected(self):
        """!Return True if device is disconnected or disconnection failed
        """
        return self._state in (self.Disconnected, self.Failed)

    @property
    def isDisconnecting(self):
        """!Return True if device is disconnecting or disconnected
        """
        return self._state in (self.Disconnected, self.Failed, self.Disconnecting)

    def startCmd(self, cmdStr, callFunc=None, userCmd=None, timeLim=DefaultTimeLim, showReplies=False):
        """!Start a new command.

        @param[in] cmdStr  command string
        @param[in] callFunc  callback function: function to call when command succeeds or fails, or None;
            if specified it receives one argument: a device command
        @param[in] userCmd  user command that tracks this command, if any
        @param[in] timeLim  maximum time before command expires, in sec; None for no limit
        @param[in] showReplies  show all replies as plain text?

        @return devCmd: the device command that was started (and may already have failed)

        @note: if callFunc and userCmd are both specified callFunc is called before userCmd is updated.

        @warning: subclasses must supplement or override this method to set the devCmd done when finished.
        Subclasses that use a command queue will usually replace this method.
        """
        log.info("%s.startCmd(cmdStr=%r, callFunc=%s, userCmd=%s, timeLim=%s)" % (self, cmdStr, callFunc, userCmd, timeLim))
        devCmd = self.cmdClass(
            cmdStr = cmdStr,
            userCmd = userCmd,
            callFunc = callFunc,
            timeLim = timeLim,
            dev = self,
            showReplies = showReplies,
        )
        if not self.conn.isConnected:
            devCmd.setState(devCmd.Failed, textMsg="%s %s failed: not connected" % (self.name, cmdStr))
        else:
            fullCmdStr = devCmd.fullCmdStr
            try:
                self.conn.writeLine(fullCmdStr)
            except Exception as e:
                devCmd.setState(devCmd.Failed, textMsg="%s %s failed: %s" % (self.name, cmdStr, strFromException(e)))

        return devCmd

    def _connCallback(self, conn=None):
        """!Call when the connection state changes

        Monitor that the socket has disconnected and set the internal state accordingly
        """
        # print("%s._connCallback(conn=%s); self.state=%s, self.conn.state=%s, self._ignoreConnCallback=%s" % (self, conn, self.state, self.conn.state, self._ignoreConnCallback))
        if self._ignoreConnCallback:
            return False
        if self.conn.isConnected:
            return
        if self.isDisconnected:
            if self.state != self.Disconnected:
                self.setState(self.Disconnected, "connection state = %s" % (self.conn.state,))
        else:
            if self.state != self.Disconnecting:
                self.setState(self.Disconnecting, "connection state = %s" % (self.conn.state,))

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, self.name)


class ConnectDevice(object):
    """!Connect a device and execute dev.init

    If the device is already connected then generate a new userCmd, if needed,
    and sets userCmd's state to userCmd.Done.

    Public attributes:
    - dev: the provided device
    - userCmd: the provided userCmd, or a new one if none provided
    """
    def __init__(self, dev, userCmd, timeLim):
        """!Start connecting a device

        @param[in] dev  device
        @param[in] userCmd  user command associated with the connection, or None
        @param[in] timeLim  time limit (sec) to make this connection
        """
        self.dev = dev
        self._timeLim = timeLim
        self.userCmd = expandUserCmd(userCmd)
        self._connTimer = Timer()
        self._addedConnCallback = False

        if self.dev.isConnected and self.dev.conn.isConnected:
            # already done; don't send init
            self.finish()
            return

        self.dev._ignoreConnCallback = True
        self.dev.setState(self.dev.Connecting)
        self.dev.conn.addStateCallback(self.connCallback)
        self._addedConnCallback = True
        if self.dev.conn.mayConnect:
            self.dev.conn.connect(timeLim=timeLim)
        else:
            if self._timeLim:
                # start timer for the connection that is occurring now
                self._connTimer.start(self._timeLim, self.finish, "timed out waiting for connection")

    def initCallback(self, userCmd):
        """!Callback for device initialization
        """
        # print("%s.initCallback(userCmd=%r); _callbacks=%s" % (self, userCmd, userCmd._callbacks))
        if not userCmd.isDone:
            return

        if userCmd.didFail:
            reason = userCmd.getMsg() or "init command failed for unknown reasons"
        else:
            reason = None
        Timer(0, self.finish, reason)

    def connCallback(self, conn):
        """!Callback for device connection state
        """
        if self.dev.conn.isConnected:
            self._connTimer.cancel()
            initUserCmd = UserCmd(cmdStr="connect %s" % (self.dev.name,), callFunc=self.initCallback)
            self.dev.init(userCmd=initUserCmd, timeLim=self._timeLim, getStatus=True)
        elif self.dev.conn.didFail:
            self._connTimer.cancel()
            self.finish("connection failed")

    def finish(self, reason=None):
        """!Call on success or failure to finish the command

        @param[in] reason: reason for failure (if non-empty then failure is assumed)
        """
        self._connTimer.cancel()
        self.dev._ignoreConnCallback = False
        if self._addedConnCallback:
            self.dev.conn.removeStateCallback(self.connCallback)
        if reason or not self.dev.conn.isConnected:
            reason = reason or "unknown reason"
            self.dev.setState(self.dev.Failed, reason)
            if not self.userCmd.isDone:
                self.userCmd.setState(self.userCmd.Failed, textMsg="%s failed to connect: %s" % (self.dev, reason))
            Timer(0, self.dev.conn.disconnect)
        else:
            self.dev.setState(self.dev.Connected)
            if not self.userCmd.isDone:
                self.userCmd.setState(self.userCmd.Done)

    def __repr__(self):
        return "%s(dev.name=%s)" % (type(self).__name__, self.dev.name)


class DisconnectDevice(object):
    """!Execute dev.init (if the device is fully connected) and disconnect a device

    If the device is already disconnected then generate a new userCmd, if needed,
    and sets userCmd's state to userCmd.Done.

    Public attributes:
    - dev: the provided device
    - userCmd: the provided userCmd, or a new one if none provided
    """
    def __init__(self, dev, userCmd, timeLim):
        """!Start disconnecting a device
        """
        self.dev = dev
        self.userCmd = expandUserCmd(userCmd)
        self._timeLim = timeLim
        self._connTimer = Timer()
        self._addedConnCallback = False

        if self.dev.conn.isDisconnected:
            if self.dev.state != self.dev.Disconnected:
                self.dev.setState(self.dev.Disconnected, "socket disconnected")
            if not self.userCmd.isDone:
                self.userCmd.setState(self.userCmd.Done)
            return

        self.dev._ignoreConnCallback = True
        if self.dev.state != self.dev.Disconnected:
            self.dev.setState(self.dev.Disconnecting)

        if self.dev.conn.isConnected:
            initUserCmd = UserCmd(cmdStr="Init via device.DisconnectDevice", callFunc=self.initCallback, timeLim=timeLim)
            self.dev.init(userCmd=initUserCmd, timeLim=timeLim, getStatus=False)
        else:
            # not fully connected, so cannot send init, but not fully disconnected yet, so finish disconnecting
            textMsg = "%s connection state=%s; cannot initialize before disconnecting" % (self.dev.name, self.dev.conn.state)
            self.dev.writeToUsers("w", "text=%s" % (quoteStr(textMsg),))
            self.startDisconnect()
            return

    def startDisconnect(self):
        """!Start disconnecting the connection
        """
        if self.dev.conn.isDone and not self.dev.conn.isConnected:
            # fully disconnected; no more to be done
            Timer(0, self.finish)
        else:
            if self._timeLim:
                # start timer for disconnection
                self._connTimer.start(self._timeLim, self.finish, "timed out waiting for disconnection")

            self.dev.conn.addStateCallback(self.connCallback)
            self._addedConnCallback = True
            self.dev.conn.disconnect()

    def initCallback(self, initUserCmd):
        """!Callback for device initialization
        """
        if not initUserCmd.isDone:
            return

        if initUserCmd.didFail:
            textMsg = "%s initialization failed: %s" % (self.dev.name, initUserCmd.textMsg,)
            self.dev.writeToUsers("w", "text=%s" % (quoteStr(textMsg),))
        self.startDisconnect()

    def connCallback(self, conn):
        """!Callback for device connection state
        """
        if self.dev.conn.isDone:
            Timer(0, self.finish)

    def finish(self, reason=None):
        """!Call on success or failure to finish the command

        @param[in] reason: reason for failure (if non-empty then failure is assumed)
        """
        self._connTimer.cancel()
        self.dev._ignoreConnCallback = False
        if self._addedConnCallback:
            self.dev.conn.removeStateCallback(self.connCallback)
        if reason or not self.dev.conn.isDone or not self.dev.conn.isDisconnected:
            reason = reason or "unknown reasons"
            self.dev.setState(self.dev.Failed, reason)
            if not self.userCmd.isDone:
                self.userCmd.setState(self.userCmd.Failed, textMsg="%s failed to disconnect: %s" % (self.dev, reason))
        else:
            if self.dev.state != self.dev.Disconnected:
                self.dev.setState(self.dev.Disconnected)
            if not self.userCmd.isDone:
                self.userCmd.setState(self.userCmd.Done)
        self.dev.cleanup()

    def __repr__(self):
        return "%s(dev.name=%s)" % (type(self).__name__, self.dev.name)


class TCPDevice(Device):
    """!TCP-connected device.
    """
    def __init__(self,
        name,
        host,
        port = 23,
        cmdInfo = None,
        callFunc = None,
        cmdClass = DevCmd,
        lineTerminator = "\r\n",
    ):
        """!Construct a TCPDevice

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
        @param[in] lineTerminator  specifies the end of line characters when sending data to the device
        """
        Device.__init__(self,
            name = name,
            cmdInfo = cmdInfo,
            conn = TCPConnection(
                host = host,
                port = port,
                readCallback = self._readCallback,
                readLines = True,
                lineTerminator = lineTerminator,
            ),
            callFunc = callFunc,
            cmdClass = cmdClass,
        )

    def _readCallback(self, sock, replyStr):
        """!Called whenever the device has returned a reply.

        @param[in] sock  the socket (ignored)
        @param[in] line  the reply, missing the final \n
        """
        # print("TCPDevice._readCallback(sock, replyStr=%r)" % (replyStr,))
        self.handleReply(replyStr)

    def __str__(self):
        return "%s(%s)" % (type(self).__name__, self.name)

    def __repr__(self):
        return "%s(%s, host=%s, port=%s)" % (type(self).__name__, self.name, self.conn.host, self.conn.port)


class ActorDevice(TCPDevice):
    """!A device that obeys the APO standard actor interface
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
        """!Construct an ActorDevice

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
        @param[in] cmdClass  class for new device commands
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

    @property
    def model(self):
        """!Get the keyword model for the device
        """
        return self.dispatcher.model

    def startCmd(self,
        cmdStr,
        callFunc = None,
        userCmd = None,
        timeLim = 0,
        timeLimKeyVar = None,
        timeLimKeyInd = 0,
        abortCmdStr = None,
        keyVars = None,
        showReplies = False,
    ):
        """!Queue or start a new command.

        @param[in] cmdStr  the command; no terminating \n wanted
        @param[in] callFunc  callback function: function to call when command succeeds or fails, or None;
            if specified it receives one argument: an opscore.actor.CmdVar object
        @param[in] userCmd  user command that tracks this command, if any
        @param[in] callFunc  a callback function; it receives one argument: a CmdVar object
        @param[in] userCmd  user command that tracks this command, if any
        @param[in] timeLim  maximum time before command expires, in sec; 0 for no limit
        @param[in] timeLimKeyVar  a KeyVar specifying a delta-time by which the command must finish
            this KeyVar must be registered with the message dispatcher.
        @param[in] timeLimKeyInd  the index of the time limit value in timeLimKeyVar; defaults to 0;
            ignored if timeLimKeyVar is None.
        @param[in] abortCmdStr  a command string that will abort the command.
            Sent to the actor if abort is called and if the command is executing.
        @param[in] keyVars  a sequence of 0 or more keyword variables to monitor for this command.
            Any data for those variables that arrives IN RESPONSE TO THIS COMMAND is saved
            and can be retrieved using cmdVar.getKeyVarData or cmdVar.getLastKeyVarData.
        @param[in] showReplies  show all replies as plain text?

        @return devCmd: the device command that was started (and may already have failed)

        @note: if callFunc and userCmd are both specified callFunc is called before userCmd is updated.
        """
        cmdVar = opscore.actor.CmdVar(
            cmdStr = cmdStr,
            timeLim = timeLim,
            timeLimKeyVar = timeLimKeyVar,
            timeLimKeyInd = timeLimKeyInd,
            abortCmdStr = abortCmdStr,
            keyVars = keyVars,
        )
        if showReplies:
            cmdVar.addCallback(
                self._showReply,
                callCodes = opscore.actor.AllCodes,
            )
        devCmdVar = self.cmdClass(
            cmdVar = cmdVar,
            userCmd = userCmd,
            callFunc = callFunc,
            dev = self,
            showReplies = showReplies,
        )
        log.info("%s writing %r" % (self, cmdVar.cmdStr))
        self.dispatcher.executeCmd(cmdVar)
        return devCmdVar

    def _showReply(self, cmdVar):
        replyStr = cmdVar.lastReply.string if cmdVar.lastReply else None
        if not replyStr:
            return
        msgCode = {
            ":": "I",
            "E": "W",
            "F": "W",
            "!": "W",
        }.get(cmdVar.lastCode, cmdVar.lastCode)
        self.writeToUsers(msgCode, "%sReply=%s" % (self.name, quoteStr(replyStr),))

    def __repr__(self):
        return "%s(name=%s, host=%s, port=%s, modelName=%s)" % \
            (type(self).__name__, self.name, self.conn.host, self.conn.port, self.dispatcher.name)


class DeviceCollection(object):
    """!A collection of devices that provides easy access to them

    Access is as follows:
    - .&lt;name&gt; for the device named &lt;name&gt;, e.g. .foo for the device "foo"
    - .nameDict contains a collections.OrderedDict of dev.name: dev, in alphabetical order
    """
    def __init__(self, devList):
        """!Construct a DeviceCollection

        @param[in] devList  a collection of devices (instances of device.Device).
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
        """!Return the device that has this connection

        @param[in] conn  connection (a RO.Comm.TCPConnection)

        Raise KeyError if not found
        """
        return self._connDict[id(conn)]

    def __iter__(self):
        """!Return an iterator over the devices
        """
        return iter(self.nameDict.values())
