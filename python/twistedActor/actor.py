
"""!Basic framework for a hub actor or ICC based on the Twisted event loop.
"""
import operator
import sys
import types
import traceback

from opscore.RO.StringUtil import quoteStr, strFromException

from .baseActor import BaseActor
from .linkCommands import LinkCommands
from .command import CommandError, UserCmd
from .device import DeviceCollection
from .log import log

__all__ = ["Actor"]

class Actor(BaseActor):
    """!Base class for a hub actor or instrument control computer with a unix-like command syntax

    Subclass this and add cmd_ methods to add commands, (or add commands by adding items to self.locCmdDict
    but be careful with command names -- see comment below)

    Commands are defined in three ways:
    - Local commands: all Actor methods whose name starts with "cmd_";
        the rest of the name is the command verb.
        These methods must return True if the command is executed in the background
        (otherwise they will be reported as "done" when the method ends)
    - Device commands: commands specified via argument cmdInfo when creating the device;
        these commands are sent directly to the device that claims to handle them
        (with a new unique command ID number if the device can execute multiple commands at once).
        The device must finish the command (unless dev.newCmd raises an exception).
    - Direct device access commands (for debugging and engineering): the command verb is the device name
        and the subsequent text is sent directly to the device.
        The device must finish the command (unless dev.newCmd raises an exception).

    Error conditions:
    - Raise RuntimeError if any command verb is defined more than once.
    """
    def __init__(self,
        userPort,
        devs = (),
        maxUsers = 0,
        doDebugMsgs = False,
        version = "?",
        name = "Actor",
        doConnect = True,
        doDevNameCmds = True,
        commandSet = None,
    ):
        """!Construct an Actor

        @param[in] userPort  port on which to listen for users
        @param[in] devs  a collection of Device objects that this ICC controls
        @param[in] maxUsers  the maximum allowed # of users; if 0 then there is no limit
        @param[in] doDebugMsgs  print debug messages?
        @param[in] version  actor version str
        @param[in] name  actor name, used for logging
        @param[in] doConnect  if True then connect devices on construction
        @param[in] doDevNameCmds  if True, support device name commands to send arbitrary commands to each device
        @param[in] commandSet a twistedActor.parse.CommandSet instance, defines the command set and provides means for parsing
        """
        self.commandSet = commandSet
        # local command dictionary containing cmd verb: method
        # all methods whose name starts with cmd_ are added
        # each such method must accept one argument: a UserCmd
        self.locCmdDict = dict()
        for attrName in dir(self):
            if attrName.startswith("cmd_"):
                cmdVerb = attrName[4:].lower()
                self.locCmdDict[cmdVerb] = getattr(self, attrName)
        cmdVerbSet = set(self.locCmdDict.keys())

        self.dev = DeviceCollection(devs) # the short name "dev" allows easy access, e.g. self.dev.dev1Name

        # add device-specific commands
        self.devCmdDict = dict() # dict of cmdVerb: (dev, devCmdVerb, cmdHelp)
        for dev in devs:
            dev.writeToUsers = self.writeToUsers
            dev.conn.addStateCallback(self.devConnStateCallback)
            for cmdVerb, devCmdVerb, cmdHelp in dev.cmdInfo:
                devCmdVerb = devCmdVerb or cmdVerb
                lowCmdVerb = (devCmdVerb or cmdVerb).lower()
                if lowCmdVerb in self.devCmdDict:
                    raise RuntimeError("Duplicate device-specific command %s for devices %s and %s" % \
                        (cmdVerb, dev, self.devCmdDict[lowCmdVerb][0]))
                self.devCmdDict[lowCmdVerb] = (dev, devCmdVerb, cmdHelp)

        # add device name breakthrough commands
        if doDevNameCmds:
            for dev in devs:
                lowDevName = dev.name.lower()
                if lowDevName in self.devCmdDict:
                    raise RuntimeError("Device name %s duplicates device-specific command for device %s" % \
                        (dev.name, self.devCmdDict[lowDevName][0]))
                self.devCmdDict[lowDevName] = (dev, "", "send an arbitrary command to device %s" % (dev.name,))

        devCmdSet = set(key.lower() for key in self.devCmdDict)
        cmdCollisionSet = set(cmdVerbSet & devCmdSet)
        if cmdCollisionSet:
            raise RuntimeError("Device commands %s duplicate local commands" %  sorted(list(cmdCollisionSet,)))
        cmdVerbSet.update(devCmdSet)

        BaseActor.__init__(self,
            userPort = userPort,
            maxUsers = maxUsers,
            doDebugMsgs = doDebugMsgs,
            version = version,
            name = name,
        )

        # connect all devices
        if doConnect:
            self.initialConn()

    def close(self):
        """!Close the connection and cancel any timers
        """
        log.info("%s.close()" % (self,))
        for dev in self.dev:
            if not dev.isDisconnecting:
                dev.disconnect()
        BaseActor.close(self)

    def initialConn(self):
        """!Perform initial connections.

        Normally this just calls cmd_connDev, but you can override this command
        if you need a special startup sequence, such as waiting until devices boot up.
        """
        self.cmd_connDev()

    def checkNoArgs(self, newCmd):
        """!Raise CommandError if newCmd has arguments
        """
        if newCmd and newCmd.cmdArgs:
            raise CommandError("%s takes no arguments" % (newCmd.cmdVerb,))

    def checkLocalCmd(self, newCmd):
        """!Check if the new local command can run given what else is going on

        @param[in] newCmd  new local user command (twistedActor.UserCmd);
            "local" means this command will trigger a cmd_<verb> method of this actor

        If the new command cannot run then raise CommandError
        If the new command can run but must be superseded, then supersed the old command here.
        If it can run but an existing command must be superseded then supersede the old command here.

        Subclasses will typically want to override this method, as the default implementation does nothing
        (thus accepting all new local commands).

        Note that each cmd_foo method can perform additional checks and cancellation;
        this method allows a preliminary check, potentially simplifying cmd_<verb> methods.
        """
        pass

    def devConnStateCallback(self, conn):
        """!Called when a device's connection state changes

        @param[in] conn  device connection whose state has changed
        """
        dev = self.dev.getFromConnection(conn)
        wantConn, cmd = dev.connReq
        self.showOneDevConnStatus(dev, cmd=cmd)
        state, reason = conn.fullState
        if cmd and conn.isDone:
            succeeded = (bool(wantConn) == conn.isConnected)
            cmdState = "done" if succeeded else "failed"
            if not cmd.isDone:
                cmd.setState(cmdState, textMsg=reason)
            dev.connReq = (wantConn, None)

    def parseAndDispatchCmd(self, cmd):
        """!Parse and dispatch a command

        @param[in] cmd  user command (twistedActor.UserCmd)

        Duplicate command names are resolved such that the first match in this list is used:
        - local commands (cmd_<foo> methods of this actor)
        - commands handled by devices
        - direct device access commands (device name)
        """
        if not cmd.cmdBody:
            # echo to show alive
            self.writeToOneUser(":", "", cmd=cmd)
            return

        # if a commandSet was supplied use it!
        if self.commandSet is not None:
            cmd.parsedCommand = self.commandSet.parse(cmd.cmdBody)

        cmd.cmdVerb = ""
        cmd.cmdArgs = ""
        if cmd.cmdBody:
            res = cmd.cmdBody.split(None, 1)
            if len(res) > 1:
                cmd.cmdVerb, cmd.cmdArgs = res
            else:
                cmd.cmdVerb = res[0]
            cmd.cmdVerb = cmd.cmdVerb.lower()

        # see if command is a local command
        cmdFunc = self.locCmdDict.get(cmd.cmdVerb)
        if cmdFunc is not None:
            # execute local command
            try:
                self.checkLocalCmd(cmd)
                retVal = cmdFunc(cmd)
            except CommandError as e:
                cmd.setState("failed", strFromException(e))
                return
            except Exception as e:
                sys.stderr.write("command %r failed\n" % (cmd.cmdStr,))
                sys.stderr.write("function %s raised %s\n" % (cmdFunc, strFromException(e)))
                traceback.print_exc(file=sys.stderr)
                quotedErr = quoteStr(strFromException(e))
                msgStr = "Exception=%s; Text=%s" % (e.__class__.__name__, quotedErr)
                self.writeToUsers("f", msgStr, cmd=cmd)
            else:
                if not retVal and not cmd.isDone:
                    cmd.setState("done")
            return

        # see if command is a device command
        dev = None
        devCmdStr = ""
        devCmdInfo = self.devCmdDict.get(cmd.cmdVerb)
        if devCmdInfo:
            # command verb is one handled by a device
            dev, devCmdVerb, cmdHelp = devCmdInfo
            devCmdStr = "%s %s" % (devCmdVerb, cmd.cmdArgs) if devCmdVerb else cmd.cmdArgs
        if dev and devCmdStr:
            try:
                dev.startCmd(devCmdStr, userCmd=cmd, timeLim=2)
            except CommandError as e:
                cmd.setState("failed", strFromException(e))
                return
            except Exception as e:
                sys.stderr.write("command %r failed\n" % (cmd.cmdStr,))
                sys.stderr.write("function %s raised %s\n" % (cmdFunc, strFromException(e)))
                traceback.print_exc(file=sys.stderr)
                quotedErr = quoteStr(strFromException(e))
                msgStr = "Exception=%s; Text=%s" % (e.__class__.__name__, quotedErr)
                self.writeToUsers("f", msgStr, cmd=cmd)
            return

        self.writeToOneUser("f", "UnknownCommand=%s" % (cmd.cmdVerb,), cmd=cmd)

    def showNewUserInfo(self, sock):
        """!Show information for new users; called automatically when a new user connects

        @param[in] sock  socket connection to new user
        """
        fakeCmd = BaseActor.showNewUserInfo(self, sock)
        self.showDevConnStatus(cmd=fakeCmd, onlyOneUser=True, onlyIfNotConn=True)

    def showDevConnStatus(self, cmd=None, onlyOneUser=False, onlyIfNotConn=False):
        """!Show connection status for all devices

        @param[in] cmd  user command (twistedActor.UserCmd)
        @param[in] onlyOneUser  if True only display the information to the commanding user
        @param[in] onlyIfNotConn  only show information for devices that are disconnected
        """
        for dev in self.dev.nameDict.values():
            self.showOneDevConnStatus(dev, onlyOneUser=onlyOneUser, onlyIfNotConn=onlyIfNotConn, cmd=cmd)

    def showOneDevConnStatus(self, dev, cmd=None, onlyOneUser=False, onlyIfNotConn=False):
        """!Show connection status for one device

        @param[in] dev  device whose state is to be shown
        @param[in] cmd  user command (twistedActor.UserCmd)
        @param[in] onlyOneUser  if True only display the information to the commanding user
        @param[in] onlyIfNotConn  only show information for devices that are disconnected
        """
        if onlyIfNotConn and dev.conn.isConnected:
            return

        state, reason = dev.conn.fullState
        quotedReason = quoteStr(reason)
        #msgCode = "i" if dev.conn.isConnected else "w"
        if dev.conn.isConnected:
            msgCode = "i"
        else:
            msgCode = "w"
        msgStr = "%sConnState = %r, %s" % (dev.name, state, quotedReason)
        if onlyOneUser:
            self.writeToOneUser(msgCode, msgStr, cmd=cmd)
        else:
            self.writeToUsers(msgCode, msgStr, cmd=cmd)

    def cmd_connDev(self, cmd=None):
        """[dev1 [dev2 [...]]]: connect one or more devices (all devices if none specified).
        Already-connected devices are ignored (except to output status).
        Command args: 0 or more device names, space-separated
        """
        if cmd and cmd.cmdArgs:
            devNameList = cmd.cmdArgs.split()
        else:
            devNameList = list(self.dev.nameDict.keys())

        runInBackground = False
        subCmdList = []
        for devName in devNameList:
            dev = self.dev.nameDict[devName]
            if dev.isConnected:
                self.showOneDevConnStatus(dev, cmd=cmd)
            else:
                connSubCmd = UserCmd()
                subCmdList.append(connSubCmd)
                runInBackground = True
                dev.connReq = (True, connSubCmd)
                try:
                    dev.connect()
                except Exception as e:
                    self.writeToUsers("w", "text=could not connect device %s: %s" % (devName, strFromException(e)), cmd=cmd)
        if subCmdList and cmd:
            LinkCommands(cmd, subCmdList)
        return runInBackground

    def cmd_disconnDev(self, cmd=None):
        """[dev1 [dev2 [...]]]: disconnect one or more devices (all if none specified).
        Already-disconnected devices are ignored (except to output status).
        Command args: 0 or more device names, space-separated
        """
        if cmd and cmd.cmdArgs:
            devNameList = cmd.cmdArgs.split()
        else:
            devNameList = list(self.dev.nameDict.keys())

        runInBackground = False
        subCmdList = []
        for devName in devNameList:
            dev = self.dev.nameDict[devName]
            if not dev.isConnected:
                self.showOneDevConnStatus(dev, cmd=cmd)
            else:
                disconnSubCmd = UserCmd()
                subCmdList.append(disconnSubCmd)
                runInBackground = True
                dev.connReq = (False, disconnSubCmd)
                try:
                    dev.disconnect()
                except Exception as e:
                    self.writeToUsers("w", "text=could disconnect device %s: %s" % (devName, strFromException(e)), cmd=cmd)
        if subCmdList and cmd:
            LinkCommands(cmd, subCmdList)
        return runInBackground

    def cmd_exit(self, cmd=None):
        """!disconnect yourself"""
        sock = self.userDict[cmd.userID]
        sock.close()

    def cmd_help(self, cmd=None):
        """!print this help"""
        helpList = []
        debugHelpList = []

        # commands handled by this actor
        for cmdVerb, cmdFunc in self.locCmdDict.items():
            helpStr = cmdFunc.__doc__.split("\n")[0]
            if helpStr.startswith("!"):
                # an initial "!" is used to enable Doxygen formatting of help
                helpStr = helpStr[1:]
            if ":" in helpStr:
                joinStr = " "
            else:
                joinStr = ": "
            if cmdVerb.startswith("debug"):
                debugHelpList.append(joinStr.join((cmdVerb, helpStr)))
            else:
                helpList.append(joinStr.join((cmdVerb, helpStr)))

        # commands handled by a device
        for cmdVerb, cmdInfo in self.devCmdDict.items():
            helpStr = cmdInfo[2]
            if ":" in helpStr:
                joinStr = " "
            else:
                joinStr = ": "
            helpList.append(joinStr.join((cmdVerb, helpStr)))

        helpList.sort()
        helpList += ["", "Debug commands:"]
        debugHelpList.sort()
        helpList += debugHelpList

        # direct device access commands (these go at the end)
        helpList += ["", "Direct device access commands:"]
        for devName in self.dev.nameDict:
            helpList.append("%s <text>: send <text> to device %s" % (devName, devName))

        for helpStr in helpList:
            self.writeToUsers("i", "text=%r" % (helpStr,), cmd=cmd)

    def cmd_ping(self, cmd):
        """!verify that actor is alive"""
        cmd.setState("done", textMsg="alive")

    def cmd_status(self, cmd):
        """!show status

        Actors may wish to override this method to output additional status.
        """
        self.showUserInfo(cmd=cmd)
        self.showDevConnStatus(cmd=cmd)

    def cmd_debugMsgs(self, cmd):
        """!on/off: turn debugging messages on or off"""
        arg = cmd.cmdArgs.lower()
        if arg == "on":
            self.doDebugMsgs = True
        elif arg == "off":
            self.doDebugMsgs = False
        else:
            raise RuntimeError("Unrecognized argument %r; must be 'on' or 'off'" % (cmd.cmdArgs,))
        self.writeToUsers("i", 'Text="Debugging messages %s"' % (arg,), cmd=cmd)

    def cmd_debugRefCounts(self, cmd):
        """!print the reference count for each object"""
        d = {}
        # collect all classes
        for m in list(sys.modules.values()):
            for sym in dir(m):
                o = getattr (m, sym)
                if type(o) in (type, type):
                    d[o] = sys.getrefcount (o)
        # sort by descending refcount (most interesting objects first)
        pairs = list(d.items())
        pairs.sort(key=operator.itemgetter(1), reverse=True)

        for c, n in pairs[:100]:
            self.writeToOneUser("i", "refCount=%5d, %s" % (n, c.__name__), cmd=cmd)
