"""Command objects for the Tcl Actor
"""
__all__ = ["CommandError", "BaseCmd", "DevCmd", "DevCmdVar", "UserCmd"]

import re
import sys
import RO.AddCallback
import RO.Alg
from RO.StringUtil import quoteStr
from RO.Comm.TwistedTimer import Timer
import copy

class CommandError(Exception):
    """Raise for a "normal" command failure
    
    Raise this error while processing a command when you want the explanation
    to be nothing more than the text of the exception, rather than a traceback.
    """
    pass


class BaseCmd(RO.AddCallback.BaseMixin):
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
    DoneStates = frozenset((Done,)) | FailedStates
    AllStates = frozenset((Ready,)) | ActiveStates | DoneStates
    _MsgCodeDict = dict(
        ready = "i",
        running = "i",
        cancelling = "w",
        failing = "w",
        cancelled = "f",
        failed = "f",
        done = ":",
    )
    def __init__(self,
        cmdStr,
        userID = 0,
        cmdID = 0,
        callFunc = None,
        timeLim = None,
    ):
        """Construct a BaseCmd
        
        Inputs:
        - cmdStr: command string
        - userID: user ID number
        - cmdID: command ID number
        - callFunc: function to call when command changes state;
            receives one argument: this command
        - timeLim: time limit for command (sec); if None or 0 then no time limit
        """
        self._cmdStr = cmdStr
        self.userID = int(userID)
        self.cmdID = int(cmdID)
        self.state = self.Ready
        self._textMsg = ""
        self._hubMsg = ""
        self._cmdToTrack = None

        self._timeoutTimer = Timer()
        self.setTimeLimit(timeLim)

        RO.AddCallback.BaseMixin.__init__(self, callFunc)
    
    @property
    def cmdStr(self):
        return self._cmdStr
    
    @property
    def isActive(self):
        """Command is running, canceling or failing"""
        return self.state in self.ActiveStates
    
    @property
    def isDone(self):
        """Command is done (whether successfully or not)"""
        return self.state in self.DoneStates

    @property
    def didFail(self):
        """Command failed or was cancelled"""
        return self.state in self.FailedStates

    @property
    def fullState(self):
        """Return state, textMsg, hubMsg"""
        return (self.state, self._textMsg, self._hubMsg)
    
    @property
    def msgCode(self):
        """Return the hub message code appropriate to the current state"""
        return self._MsgCodeDict[self.state]
    
    def hubFormat(self):
        """Return (msgCode, msgStr) for output of status as a hub-formatted message"""
        msgCode = self._MsgCodeDict[self.state]
        msgInfo = []
        if self._hubMsg:
            msgInfo.append(self._hubMsg)
        if self._textMsg:
            msgInfo.append("Text=%s" % (quoteStr(self._textMsg),))
        msgStr = "; ".join(msgInfo)
        return (msgCode, msgStr)
    
    def setState(self, newState, textMsg="", hubMsg=""):
        """Set the state of the command and call callbacks.
        
        If new state is done then remove all callbacks (after calling them).
        
        Inputs:
        - newState: new state of command
        - textMsg: a message to be printed using the Text keyword
        - hubMsg: a message in keyword=value format (without a header)

        If the new state is Failed then please supply a textMsg and/or hubMsg.
        
        Error conditions:
        - Raise RuntimeError if this command is finished.
        """
        if self.isDone:
            raise RuntimeError("Command is done; cannot change state")
        if newState not in self.AllStates:
            raise RuntimeError("Unknown state %s" % newState)
        if self.state == self.Ready and newState in self.ActiveStates and self._timeLim:
            self._timeoutTimer.start(self._timeLim, self._timeout)
        self.state = newState
        self._textMsg = str(textMsg)
        self._hubMsg = str(hubMsg)
        self._basicDoCallbacks(self)
        if self.isDone:
            self._timeoutTimer.cancel()
            self._removeAllCallbacks()
            self._cmdToTrack = None
    
    def setTimeLimit(self, timeLim):
        """Set a new time limit
        
        If the new limit is 0 or None then there is no time limit.
        
        If the command is has not started running, then the timer starts when the command starts running.
        If the command is running the timer starts now (any time spent before now is ignored).
        If the command is done then the new time limit is silently ignored.
        """
        self._timeLim = float(timeLim) if timeLim is not None else None
        if self._timeLim:
            if self._timeoutTimer.isActive:
                self._timeoutTimer.start(self._timeLim, self._timeout)
        else:
            self._timeoutTimer.cancel()

    def trackCmd(self, cmdToTrack):
        """Tie the state of this command to another command"""
        if self.isDone:
            raise RuntimeError("Finished; cannot track a command")
        if self._cmdToTrack:
            raise RuntimeError("Already tracking a command")
        cmdToTrack.addCallback(self._cmdCallback)
        self._cmdToTrack = cmdToTrack
    
    def untrackCmd(self):
        """Stop tracking a command if tracking one, else do nothing"""
        if self._cmdToTrack:
            self._cmdToTrack.addCallback(self._cmdCallback)
            self._cmdToTrack = None
    
    def _cmdCallback(self, cmdToTrack):
        """Tracked command's state has changed"""
        state, textMsg, hubMsg = cmdToTrack.fullState
        self.setState(state, textMsg=textMsg, hubMsg=hubMsg)
    
    def _timeout(self):
        """Time limit timer callback"""
        if not self.isDone:
            self.setState(self.Failed, textMsg="Timed out")
    
    def __str__(self):
        return "%s(%r)" % (self.__class__.__name__, self.cmdStr)

    
    def __repr__(self):
        return "%s(cmdStr=%r, userID=%r, cmdID=%r, timeLim=%r, state=%r)" % \
            (self.__class__.__name__, self.cmdStr, self.userID, self.cmdID, self._timeLim, self.state)

class DevCmd(BaseCmd):
    """Generic device command
    
    You may wish to subclass to override the following:
    * fullCmdStr returns: locCmdID cmdStr
    
    Useful attributes:
    - locCmdID: command ID number (assigned when the device command is created);
        this is the command ID for the command sent to the device
    """
    _LocCmdIDGen = RO.Alg.IDGen(startVal=1, wrapVal=sys.maxint)
    def __init__(self,
        cmdStr,
        callFunc = None,
        userCmd = None,
        timeLim = None,
    ):
        """Construct a DevCmd
        
        Inputs:
        - cmdStr: command string
        - callFunc: function to call when command changes state;
            receives one argument: this command
        - userCmd: a user command that will track this new device command
        - timeLim: time limit for command (sec); if None or 0 then no time limit
        """
        self.locCmdID = self._LocCmdIDGen.next()
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


class DevCmdVar(BaseCmd):
    """Device command wrapper around opscore.actor.CmdVar
    """
    def __init__(self,
        cmdVar,
        callFunc = None,
        userCmd = None,
        timeLim = None,
    ):
        """Construct an DevCmdVar
        
        Inputs:
        - cmdVar: the command variable to wrap (an instance of opscore.actor.CmdVar)
        - callFunc: function to call when command changes state;
            receives one argument: this command
        - userCmd: a user command that will track this new device command
        - timeLim: time limit for command (sec); if None or 0 then no time limit
        """
        BaseCmd.__init__(self,
            cmdStr = "", # instead of copying cmdVar.cmdStr, override the cmdStr property below
            callFunc = callFunc,
            timeLim = timeLim,
        )

        if userCmd:
            self.userID = userCmd.userID
            self.cmdID = userCmd.cmdID
            userCmd.trackCmd(self)

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
        textMsg = ""
        if not self.cmdVar.didFail:
            newState = self.Done
        else:
            newState = self.Failed
            textMsg = self.cmdVar.lastReply.string
        self.setState(newState, textMsg=textMsg)


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
    
        Inputs:
        - userID    ID of user (always 0 if a single-user actor)
        - cmdStr    full command
        - callFunc  function to call when command finishes or fails;
                    the function receives two arguments: this UserCmd, isOK
        - timeLim: time limit for command (sec); if None or 0 then no time limit
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
        
        Inputs:
        - cmdStr: command string (see module doc string for format)
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

