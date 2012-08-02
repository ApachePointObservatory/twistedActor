"""Command objects for the Tcl Actor
"""
__all__ = ["CommandError", "BaseCmd", "DevCmd", "DevCmdVar", "UserCmd"]

import re
import sys
import RO.AddCallback
import RO.Alg
from RO.StringUtil import quoteStr

class CommandError(Exception):
    """Raise for a "normal" command failure when you want the explanation to be
    nothing more than the text of the exception.
    """
    pass


class BaseCmd(RO.AddCallback.BaseMixin):
    """Base class for commands of all types (user and device).
    """
    # state constants
    Done = "done"
    Cancelled = "cancelled"
    Failed = "failed"
    Ready = "ready"
    Running = "running"
    Cancelling = "cancelling"
    Failing = "failing"
    DoneStates = set(("done", "cancelled", "failed"))
    StateSet = DoneStates | set(("ready", "running", "cancelling", "failing"))
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
        
        @warning: this class does not enforce timeLim
        """
        self._cmdStr = cmdStr
        self.userID = int(userID)
        self.cmdID = int(cmdID)
        self._timeLim = timeLim

        self.state = "ready"
        self._textMsg = ""
        self._hubMsg = ""
        self._cmdToTrack = None

        RO.AddCallback.BaseMixin.__init__(self, callFunc)
    
    @property
    def cmdStr(self):
        return self._cmdStr
    
    @property
    def isDone(self):
        """Command is done (whether successfully or not)"""
        return self.state in self.DoneStates

#     @property
#     def isFailing(self):
#         """Command is failing"""
#         return self.state in ("cancelling", "failing")
    
    @property
    def didFail(self):
        """Command failed or was cancelled"""
        return self.state in ("cancelled", "failed")

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
        """Set the state of the command and (if new state is done) remove all callbacks.
        
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
        if newState not in self.StateSet:
            raise RuntimeError("Unknown state %s" % newState)
        self.state = newState
        self._textMsg = str(textMsg)
        self._hubMsg = str(hubMsg)
        self._basicDoCallbacks(self)
        if self.isDone:
            self._removeAllCallbacks()
            self._cmdToTrack = None
    
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
    
    def __str__(self):
        return "%s(%r)" % (self.__class__.__name__, self.cmdStr)


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
    ):
        """Construct a DevCmd
        
        Inputs:
        - cmdStr: command string
        - callFunc: function to call when command changes state;
            receives one argument: this command
        - userCmd: a user command that will track this new device command
        """
        self.locCmdID = self._LocCmdIDGen.next()
        BaseCmd.__init__(self,
            cmdStr = cmdStr,
            callFunc = callFunc,
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
    ):
        """Construct an DevCmdVar
        
        Inputs:
        - cmdVar: the command variable to wrap (an instance of opscore.actor.CmdVar)
        - callFunc: function to call when command changes state;
            receives one argument: this command
        - userCmd: a user command that will track this new device command
        """
        BaseCmd.__init__(self,
            cmdStr = "", # instead of copying cmdVar.cmdStr, override the cmdStr property below
            callFunc = callFunc,
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
        if self.cmdVar.didFail:
            newState = self.Done
        else:
            newState = self.Failed
            textMsg = self.cmdVar.lastReply.string
        self.setState(state, textMsg=textMsg)


class UserCmd(BaseCmd):
    """A command from a user (typically the hub)
    
    Inputs:
    - userID    ID of user (always 0 if a single-user actor)
    - cmdStr    full command
    - callFunc  function to call when command finishes or fails;
                the function receives two arguments: this UserCmd, isOK

    Attributes:
    - cmdBody   command after the header
    """
    _HeaderBodyRE = re.compile(r"((?P<cmdID>\d+)(?:\s+\d+)?\s+)?((?P<cmdBody>[A-Za-z_].*))?$")
    def __init__(self,
        userID = 0,
        cmdStr = "",
        callFunc = None,
    ):
        BaseCmd.__init__(self, cmdStr, userID=userID, callFunc=callFunc)
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
