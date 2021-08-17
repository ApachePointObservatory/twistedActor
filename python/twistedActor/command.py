
"""Command objects for the twisted actor
"""
import re
import sys

from opscore.RO import AddCallback
from opscore.RO import Alg
from opscore.RO.StringUtil import quoteStr
from opscore.RO.Comm.TwistedTimer import Timer

from .log import log

__all__ = ["CommandError", "BaseCmd", "DevCmd", "DevCmdVar", "UserCmd", "expandUserCmd"]

class CommandError(Exception):
    """Raise for a "normal" command failure

    Raise this error while processing a command when you want the explanation
    to be nothing more than the text of the exception, rather than a traceback.
    """
    pass


class BaseCmd(AddCallback.BaseMixin):
    """Base class for commands of all types (user and device).
    """
    # state constants
    Done = "done"
    Cancelled = "cancelled" # including superseded
    Failed = "failed"
    Ready = "ready"
    Running = "running"
    Cancelling = "cancelling"
    Failing = "failing"
    ActiveStates = frozenset((Running, Cancelling, Failing))
    FailedStates = frozenset((Cancelled, Failed))
    FailingStates = frozenset((Cancelling, Failing))
    DoneStates = frozenset((Done,)) | FailedStates
    AllStates = frozenset((Ready,)) | ActiveStates | DoneStates
    _MsgCodeDict = dict(
        ready = "i",
        running = "i",
        cancelling = "w",
        failing = "w",
        cancelled = "f",
        failed = "f",
        debug = "d",
        done = ":",
    )
    _InvMsgCodeDict = dict((val, key) for key, val in _MsgCodeDict.items())
    def __init__(self,
        cmdStr,
        userID = 0,
        cmdID = 0,
        callFunc = None,
        timeLim = None,
    ):
        """Construct a BaseCmd

        @param[in] cmdStr  command string
        @param[in] userID  user ID number
        @param[in] cmdID  command ID number
        @param[in] callFunc  function to call when command changes state;
            receives one argument: this command
        @param[in] timeLim  time limit for command (sec); if None or 0 then no time limit
        """
        self._cmdStr = cmdStr
        self.userID = int(userID)
        self.cmdID = int(cmdID)
        self._state = self.Ready
        self._textMsg = ""
        self._hubMsg = ""
        self._cmdToTrack = None
        self._linkedCommands = []
        self._parentCmd = None
        self._writeToUsers = None # set by baseActor.ExpandCommand
        # set by baseActor.newCmd to flag this as a command created
        # from socket input
        self.userCommanded = False
        self._timeoutTimer = Timer()
        self.setTimeLimit(timeLim)

        AddCallback.BaseMixin.__init__(self, callFunc)

    @property
    def parentCmd(self):
        return self._parentCmd

    @property
    def eldestParentCmd(self):
        if self.parentCmd is None:
            return self
        else:
            return self.parentCmd.eldestParentCmd

    @property
    def timeLim(self):
        return self._timeLim

    @property
    def cmdStr(self):
        return self._cmdStr

    @property
    def didFail(self):
        """Command failed or was cancelled
        """
        return self._state in self.FailedStates

    @property
    def isActive(self):
        """Command is running, canceling or failing
        """
        return self._state in self.ActiveStates

    @property
    def isDone(self):
        """Command is done (whether successfully or not)
        """
        return self._state in self.DoneStates

    @property
    def isFailing(self):
        """Command is being cancelled or is failing
        """
        return self._state in self.FailingStates

    @property
    def msgCode(self):
        """The hub message code appropriate to the current state
        """
        return self._MsgCodeDict[self._state]

    @property
    def hubMsg(self):
        """The hub message or "" if none
        """
        return self._hubMsg

    @property
    def textMsg(self):
        """The text message or "" if none
        """
        return self._textMsg

    @property
    def state(self):
        """The state of the command, as a string which is one of the state constants, e.g. self.Done
        """
        return self._state

    def setWriteToUsers(self, writeToUsersFunc):
        if self._writeToUsers is not None:
            raise RuntimeError("Write to users is already set")
        else:
            self._writeToUsers = writeToUsersFunc

    def writeToUsers(self, msgCode, msgStr, userID=None, cmdID=None):
        # see doc in baseActor.
        # self._writeToUsers is set in BaseActor.newCmd()
        # or is is set at the time of any command linkage
        # get the top most command for writing to users
        # it will be the original cmd
        topCmd = self.eldestParentCmd
        if topCmd._writeToUsers is None:
            print("%s writeToUsers not set: "%str(self), msgCode, msgStr, topCmd, userID, cmdID, "!!!")
        else:
            topCmd._writeToUsers(msgCode, msgStr, topCmd, userID, cmdID)

    def addCallback(self, callFunc, callNow=False):
        """Add a callback function

        @param[in] callFunc  callback function:
        - it receives one argument: this command
        - it is called whenever the state changes, and immediately if the command is already done
            or callNow is True
        @param[in] callNow  if True, call callFunc immediately
        """
        if self.isDone:
            AddCallback.safeCall2("%s.addCallback callFunc =" % (self,), callFunc, self)
        else:
            AddCallback.BaseMixin.addCallback(self, callFunc, callNow=callNow)

    def getMsg(self):
        """Get minimal message in simple format, prefering _textMsg

        @return _textMsg (if available), else _hubMsg (which may be blank).
        """
        return self._textMsg or self._hubMsg

    def getKeyValMsg(self, textPrefix=""):
        """Get full message data as (msgCode, msgStr), where msgStr is in keyword-value format

        @param[in] textPrefix  a prefix added to self._textMsg
        @return two values:
        - msgCode: message code (e.g. "W")
        - msgStr: message string: a combination of _textMsg and _hubMsg in keyword-value format.
            Warning: he "Text" keyword will be repeated if _textMsg is non-empty and _hubMsg contains "Text="
        """
        msgCode = self._MsgCodeDict[self._state]
        msgInfo = []
        if self._hubMsg:
            msgInfo.append(self._hubMsg)
        if self._textMsg or textPrefix:
            msgInfo.append("text=%s" % (quoteStr(textPrefix + self._textMsg),))
        msgStr = "; ".join(msgInfo)
        return (msgCode, msgStr)

    def setState(self, newState, textMsg=None, hubMsg=None):
        """Set the state of the command and call callbacks.

        If new state is done then remove all callbacks (after calling them).

        @param[in] newState  new state of command
        @param[in] textMsg  a message to be printed using the Text keyword; if None then not changed
        @param[in] hubMsg  a message in keyword=value format (without a header); if None then not changed

        You can set both textMsg and hubMsg, but typically only one or the other will be displayed
        (depending on the situation).

        If the new state is Failed then please supply a textMsg and/or hubMsg.

        Error conditions:
        - Raise RuntimeError if this command is finished.
        """
        # print("%r.setState(newState=%s, textMsg=%r, hubMsg=%r); self._cmdToTrack=%r" % (self, newState, textMsg, hubMsg, self._cmdToTrack))
        if self.isDone:
            raise RuntimeError("Command %s is done; cannot change state" % str(self))
        if newState not in self.AllStates:
            raise RuntimeError("Unknown state %s" % newState)
        if self._state == self.Ready and newState in self.ActiveStates and self._timeLim:
            self._timeoutTimer.start(self._timeLim, self._timeout)
        self._state = newState
        if textMsg is not None:
            self._textMsg = str(textMsg)
        if hubMsg is not None:
            self._hubMsg = str(hubMsg)
        log.info(str(self))
        self._basicDoCallbacks(self)
        if self.isDone:
            self._timeoutTimer.cancel()
            self._removeAllCallbacks()
            self.untrackCmd()

    def setTimeLimit(self, timeLim):
        """Set a new time limit

        If the new limit is 0 or None then there is no time limit.
        If the new limit is < 0, it is ignored and a warning is printed to stderr

        If the command is has not started running, then the timer starts when the command starts running.
        If the command is running the timer starts now (any time spent before now is ignored).
        If the command is done then the new time limit is silently ignored.
        """
        if timeLim and float(timeLim) < 0:
            sys.stderr.write("Negative time limit received: %0.2f, and ignored\n"%timeLim)
            return
        self._timeLim = float(timeLim) if timeLim else None
        if self._timeLim:
            if self.isActive:
                self._timeoutTimer.start(self._timeLim, self._timeout)
        else:
            self._timeoutTimer.cancel()

    def trackCmd(self, cmdToTrack):
        """Tie the state of this command to another command

        When the state of cmdToTrack changes then state, textMsg and hubMsg are copied to this command.

        @warning: if this command times out before trackCmd is finished,
        or if the state of this command is set finished, then the link is broken.
        """
        if self.isDone:
            raise RuntimeError("Finished; cannot track a command")
        if self._cmdToTrack:
            raise RuntimeError("Already tracking a command")
        self._cmdToTrack = cmdToTrack
        if cmdToTrack.isDone:
            self._cmdCallback(cmdToTrack)
        else:
            cmdToTrack.addCallback(self._cmdCallback)

    def untrackCmd(self):
        """Stop tracking a command if tracking one, else do nothing
        """
        if self._cmdToTrack:
            self._cmdToTrack.removeCallback(self._cmdCallback)
            self._cmdToTrack = None

    def removeChildren(self):
        for cmd in self._linkedCommands:
            cmd.removeCallback(self.linkCmdCallback)
        self._linkedCommands = []

    def setParentCmd(self, cmd):
        self._parentCmd = cmd

    def linkCommands(self, cmdList):
        """Tie the state of this command to a list of commands

        If any command in the list fails, so will this command
        """
        if self.isDone:
            raise RuntimeError("Finished; cannot link commands")
        if self._cmdToTrack:
            raise RuntimeError("Already tracking a command")
        self._linkedCommands.extend(cmdList)
        for cmd in cmdList:
            cmd.setParentCmd(self)
            if not cmd.isDone:
                cmd.addCallback(self.linkCmdCallback)
        # call right away in case all sub-commands are already done
        self.linkCmdCallback()

    def linkCmdCallback(self, dumCmd=None):
        """!Callback to be added to each device cmd

        @param[in] dumCmd  sub-command issuing the callback (ignored)
        """
        # if any linked commands have become active and this command is not yet active
        # set it cto the running state!
        if self.state == self.Ready and True in [linkedCommand.isActive for linkedCommand in self._linkedCommands]:
            self.setState(self.Running)

        if not all(linkedCommand.isDone for linkedCommand in self._linkedCommands):
            # not all device commands have terminated so keep waiting
            return

        failedCmdSummary = "; ".join("%s: %s" % (linkedCommand.cmdStr, linkedCommand.getMsg()) for linkedCommand in self._linkedCommands if linkedCommand.didFail)
        if failedCmdSummary:
            # at least one device command failed, fail the user command and say why
            # note, do we want to match the type of failure? If a subcommand was cancelled
            # should the mainCmd state be cancelled too?
            state = self.Failed
            textMsg = failedCmdSummary
        else:
            # all device commands terminated successfully
            # set user command to done
            state = self.Done
            textMsg = ""
        self.setState(state, textMsg = textMsg)

    @classmethod
    def stateFromMsgCode(cls, msgCode):
        """Return the command state associated with a particular message code
        """
        return cls._InvMsgCodeDict[msgCode]

    def _cmdCallback(self, cmdToTrack):
        """Tracked command's state has changed; copy state, textMsg and hubMsg
        """
        self.setState(cmdToTrack.state, textMsg=cmdToTrack.textMsg, hubMsg=cmdToTrack.hubMsg)

    def _timeout(self):
        """Call when command has timed out
        """
        if not self.isDone:
            self.setState(self.Failed, textMsg="Timed out")

    def _getDescrList(self, doFull=False):
        """Get list of descriptive strings for __str__ and __repr__
        """
        descrList = [
            repr(self.cmdStr),
            "state=%s" % (self._state,),
        ]
        if doFull:
            descrList += [
                "userID=%r" % (self.userID,),
                "cmdID=%r" % (self.cmdID,),
                "timeLim=%r" % (self._timeLim,),
            ]
        if self._textMsg:
            descrList.append("textMsg=%r" % (self._textMsg,))
        if self._hubMsg:
            descrList.append("hubMsg=%r" % (self._hubMsg,))
        if doFull and self._cmdToTrack:
            descrList.append("cmdToTrack=%r" % (self._cmdToTrack,))
        return descrList

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, ", ".join(self._getDescrList(doFull=False)))

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, ", ".join(self._getDescrList(doFull=True)))


class DevCmd(BaseCmd):
    """Generic device command

    You may wish to subclass to override the following:
    * fullCmdStr returns: locCmdID cmdStr

    Useful attributes:
    - dev: the value specified in the constructor
    - userCmd: the value specified in the constructor
    - locCmdID: command ID number (assigned when the device command is created);
        this is the command ID for the command sent to the device
    - showReplies: the value specified in the constructor
    """
    _LocCmdIDGen = Alg.IDGen(startVal=1, wrapVal=sys.maxsize)
    def __init__(self,
        cmdStr,
        callFunc = None,
        userCmd = None,
        timeLim = None,
        dev = None,
        showReplies = False,
    ):
        """Construct a DevCmd

        @param[in] cmdStr  command string
        @param[in] callFunc  function to call when command changes state, or None;
            receives one argument: this command
        @param[in] userCmd  user command whose state is to track this command, or None
        @param[in] timeLim  time limit for command (sec); if None or 0 then no time limit
        @param[in] dev  device being commanded; for simple actors and devices this can probably be left None,
            but for complex actors it can be very helpful information, e.g. for callback functions
        @param[in] showReplies  print all replies as raw text; useful for breakthrough commands and debugging

        If userCmd is specified then its state is set to the same state as the device command
        when the device command is done (e.g. Cancelled, Done or Failed). However, if the userCmd times out
        then
        If callFunc and userCmd are both specified, callFunc is called before userCmd's state is changed.
        """
        self.locCmdID = next(self._LocCmdIDGen)
        self.dev = dev
        self.showReplies = bool(showReplies)
        BaseCmd.__init__(self,
            cmdStr = cmdStr,
            callFunc = callFunc,
            timeLim = timeLim,
        )

        if userCmd:
            self.userID = userCmd.userID
            self.cmdID = userCmd.cmdID
            userCmd.trackCmd(self)

    @property
    def fullCmdStr(self):
        """The command string formatted for the device

        This version returns: locCmdID cmdStr
        if you want another format then subclass DevCmd
        """
        return "%s %s" % (self.locCmdID, self.cmdStr)

    def _getDescrList(self, doFull=False):
        descrList = BaseCmd._getDescrList(self)
        descrList.insert(0, str(self.dev))
        return descrList


class DevCmdVar(BaseCmd):
    """Device command wrapper around opscore.actor.CmdVar
    """
    def __init__(self,
        cmdVar,
        callFunc = None,
        userCmd = None,
        timeLim = None,
        dev = None,
        showReplies = False,
    ):
        """Construct an DevCmdVar

        @param[in] cmdVar  the command variable to wrap (an instance of opscore.actor.CmdVar)
        @param[in] callFunc  function to call when command changes state;
            receives one argument: this command
        @param[in] userCmd  a user command that will track this new device command
        @param[in] timeLim  time limit for command (sec); if None or 0 then no time limit
        @param[in] dev  device being commanded; for simple actors and devices this can probably be left None,
            but for complex actors it can be very helpful information, e.g. for callback functions
        @param[in] showReplies  print all replies as raw text; useful for breakthrough commands and debugging
        """
        self.dev = dev
        self.showReplies = bool(showReplies)
        BaseCmd.__init__(self,
            cmdStr = "", # instead of copying cmdVar.cmdStr, override the cmdStr property below
            callFunc = callFunc,
            timeLim = timeLim,
        )

        if userCmd:
            self.userID = userCmd.userID
            self.cmdID = userCmd.cmdID
            userCmd.trackCmd(self)
        self.userCmd=userCmd

        self.cmdVar = cmdVar
        self.cmdVar.addCallback(self._cmdVarCallback)

    @property
    def cmdStr(self):
        return self.cmdVar.cmdStr

    @property
    def locCmdID(self):
        return self.cmdVar.cmdID

    def _cmdVarCallback(self, cmdVar=None):
        if not self.cmdVar.isDone:
            return
        textMsg = None
        hubMsg = None
        if not self.cmdVar.didFail:
            newState = self.Done
        else:
            newState = self.Failed
            keyList = []
            textMsg = None
            if self.cmdVar.lastReply:
                for key in self.cmdVar.lastReply.keywords:
                    if key.name.lower() == "text":
                        textMsg = key.values[0]
                    else:
                        keyList.append("%s=%s" % (key.name, ", ".join(repr(val) for val in key.values)))
            if keyList:
                hubMsg = "; ".join(keyList)
        self.setState(newState, textMsg=textMsg, hubMsg=hubMsg)

    def _getDescrList(self, doFull=False):
        descrList = BaseCmd._getDescrList(self)
        descrList.insert(0, str(self.dev))
        return descrList


class UserCmd(BaseCmd):
    """A command from a user (typically the hub)

    Attributes:
    - cmdBody   command after the header
    """
    _HeaderBodyRE = re.compile(r"((?P<cmdID>\d+)(?:\s+\d+)?\s+)?((?P<cmdBody>[A-Za-z_].*))?$")
    def __init__(self,
        userID = 0,
        cmdStr = "",
        callFunc = None,
        timeLim = None,
    ):
        """Construct a UserCmd

        @param[in] userID    ID of user (always 0 if a single-user actor)
        @param[in] cmdStr    full command
        @param[in] callFunc  function to call when command finishes or fails;
                    the function receives two arguments: this UserCmd, isOK
        @param[in] timeLim  time limit for command (sec); if None or 0 then no time limit
        """
        BaseCmd.__init__(self,
            cmdStr = cmdStr,
            userID = userID,
            callFunc = callFunc,
            timeLim = timeLim,
        )
        self.parseCmdStr(cmdStr)

    def parseCmdStr(self, cmdStr):
        """Parse command

        @param[in] cmdStr  command string (see module doc string for format)
        """
        cmdMatch = self._HeaderBodyRE.match(cmdStr)
        if not cmdMatch:
            raise CommandError("Could not parse command %r" % cmdStr)

        cmdDict = cmdMatch.groupdict("")
        cmdIDStr = cmdDict["cmdID"]
        #self.cmdID = int(cmdIDStr) if cmdIDStr else 0
        if cmdIDStr:
            self.cmdID = int(cmdIDStr)
        else:
            self.cmdID = 0
        self.cmdBody = cmdDict.get("cmdBody", "")

def expandUserCmd(userCmd):
    """!If userCmd is None, make a new one; if userCmd is done, raise RuntimeError

    @param[in] userCmd  user command (twistedActor.UserCmd) or None
    @return userCmd: return supplied userCmd if not None, else a new twistedActor.UserCmd
    @throw RuntimeError if userCmd is done
    """
    if userCmd is None:
        userCmd = UserCmd()
    elif userCmd.isDone:
        raise RuntimeError("userCmd=%s already finished" % (userCmd,))
    return userCmd
