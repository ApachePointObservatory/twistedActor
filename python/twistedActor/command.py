"""Command objects for the Tcl Actor
"""
__all__ = ["CommandError", "BaseCmd", "DevCmd", "UserCmd"]

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
    def __init__(self, cmdStr, userID=0, callFunc=None, timeLimit=None):
        self.userID = int(userID)
        self.cmdID = 0
        self.cmdStr = cmdStr
        self.state = "ready"
        self.textMsg = ""
        self.hubMsg = ""
        self.callFunc = callFunc
        self.timeLimit = timeLimit
        self.cmdToTrack = None
        RO.AddCallback.BaseMixin.__init__(self, callFunc)
    
    def getMsgCode(self):
        """Return the hub message code appropriate to the current state"""
        return self._MsgCodeDict[self.state]
    
    def isDone(self):
        return self.state in self.DoneStates
    
    def isFailing(self):
        return self.state in ("cancelling", "failing")

    def getState(self):
        """Return state, textMsg, hubMsg"""
        return (self.state, self.textMsg, self.hubMsg)
    
    def hubFormat(self):
        """Return (msgCode, msgStr) for output of status as a hub-formatted message"""
        msgCode = self._MsgCodeDict[self.state]
        msgInfo = []
        if self.hubMsg:
            msgInfo.append(self.hubMsg)
        if self.textMsg:
            msgInfo.append("Text=%s" % (quoteStr(self.textMsg),))
        msgStr = "; ".join(msgInfo)
        return (msgCode, msgStr)
    
    def setState(self, newState, textMsg="", hubMsg=""):
        """Set the state of the command and (if new state is done) remove all callbacks.

        If the new state is Failed then please supply a textMsg and/or hubMsg.
        
        Error conditions:
        - Raise RuntimeError if this command is finished.
        """
        if self.isDone():
            raise RuntimeError("Command is done; cannot change state")
        if newState not in self.StateSet:
            raise RuntimeError("Unknown state %s" % newState)
        self.state = newState
        self.textMsg = str(textMsg)
        self.hubMsg = str(hubMsg)
        self._basicDoCallbacks(self)
        if self.isDone():
            self._removeAllCallbacks()
            self.cmdToTrack = None
    
    def trackCmd(self, cmdToTrack):
        """Tie the state of this command to another command"""
        if self.isDone():
            raise RuntimeError("Finished; cannot track a command")
        if self.cmdToTrack:
            raise RuntimeError("Already tracking a command")
        cmdToTrack.addCallback(self.trackUpdate)
        self.cmdToTrack = cmdToTrack
    
    def trackUpdate(self, cmdToTrack):
        """Tracked command's state has changed"""
        state, textMsg, hubMsg = cmdToTrack.getState()
        self.setState(state, textMsg, hubMsg)
    
    def untrackCmd(self):
        """Stop tracking a command if tracking one, else do nothing"""
        if self.cmdToTrack:
            self.cmdToTrack.removeCallback(self.trackUpdate)
            self.cmdToTrack = None
    
    def __str__(self):
        return "%s(%r)" % (self.__class__.__name__, self.cmdStr)


class DevCmd(BaseCmd):
    """Generic device command that assumes all commands have the format "verb arguments"
    
    If your device wants a command ID for each command then send it devCmd.getCmdWithID();
    otherwise send it devCmd.cmdStr.
    
    If you are talking to a device with different rules then please make your own subclass of BaseCmd.
    """
    _LocCmdIDGen = RO.Alg.IDGen(startVal=1, wrapVal=sys.maxint)
    def __init__(self,
        cmdStr,
        callFunc = None,
        userCmd = None,
    ):
        self.locCmdID = self._LocCmdIDGen.next()
        BaseCmd.__init__(self, cmdStr, callFunc=callFunc)
        self.parseCmdStr(cmdStr)

        if userCmd:
            self.userID = userCmd.userID
            self.cmdID = userCmd.cmdID
            userCmd.trackCmd(self)
    
    def parseCmdStr(self, cmdStr):
        """Parse a user command string and set cmdVerb and cmdArgs.
        
        Inputs:
        - cmdStr: command string (see module doc string for format)
        """
        cmdVerbArgs = cmdStr.split(None, 1)
        self.cmdVerb = cmdVerbArgs[0]
        #self.cmdArgs = cmdVerbArgs[1] if len(cmdVerbArgs) > 1 else ""
        if len(cmdVerbArgs) > 1:
            self.cmdArgs = cmdVerbArgs[1]
        else:
            self.cmdArgs = ""
    
    def getCmdWithID(self):
        """Return the command string with local command ID as a prefix
        """
        return "%s %s" % (self.locCmdID, self.cmdStr)


class UserCmd(BaseCmd):
    """A command from a user (typically the hub)
    
    This particular version assumes a unix-ish command syntax for the command body:
    verb args
    and lowercases the verb for ease of matching to known command verbs.
    However, feel free to make your own version that overrides parseCmdBody (or even parseCmdStr).
    
    Inputs:
    - userID    ID of user (always 0 if a single-user actor)
    - cmdStr    full command
    - callFunc  function to call when command finishes or fails;
                the function receives two arguments: this UserCmd, isOK
    Attributes:
    - cmdBody   command after the header
    - cmdVerb   command verb in lowercase
    - cmdArgs   command arguments (in original case)
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
        self.parseCmdBody()
    
    def parseCmdBody(self):
        """Parse self.cmdBody
        
        This version sets self.cmdVerb and self.cmdArgs
        """
        self.cmdVerb = ""
        self.cmdArgs = ""
        if self.cmdBody:
            res = self.cmdBody.split(None, 1)
            if len(res) > 1:
                self.cmdVerb, self.cmdArgs = res
            else:
                self.cmdVerb = res[0]
