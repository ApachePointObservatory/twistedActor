from __future__ import division, absolute_import
"""Command objects for the twisted actor
"""
import re
import sys

import RO.AddCallback
import RO.Alg
from RO.StringUtil import quoteStr
from RO.Comm.TwistedTimer import Timer

__all__ = ["CommandError", "BaseCmd", "DevCmd", "DevCmdVar", "UserCmd"]

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
        done = ":",
    )
    _InvMsgCodeDict = dict((val, key) for key, val in _MsgCodeDict.iteritems())
    def __init__(self,
        cmdStr,
        userID = 0,
        cmdID = 0,
        callFunc = None,
        timeLim = None,
    ):
        """Construct a BaseCmd
        
        @param[in] cmdStr: command string
        @param[in] userID: user ID number
        @param[in] cmdID: command ID number
        @param[in] callFunc: function to call when command changes state;
            receives one argument: this command
        @param[in] timeLim: time limit for command (sec); if None or 0 then no time limit
        """
        self._cmdStr = cmdStr
        self.userID = int(userID)
        self.cmdID = int(cmdID)
        self._state = self.Ready
        self._textMsg = ""
        self._hubMsg = ""
        self._cmdToTrack = None

        self._timeoutTimer = Timer()
        self.setTimeLimit(timeLim)

        RO.AddCallback.BaseMixin.__init__(self, callFunc)

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

    def addCallback(self, callFunc, callNow=False):
        """Add a callback function

        @param[in] callFunc: callback function:
        - it receives one argument: this command
        - it is called whenever the state changes, and immediately if the command is already done
            or callNow is True
        @param[in] callNow: if True, call callFunc immediately
        """
        if self.isDone:
            RO.AddCallback.safeCall(callFunc, self)
        else:
            RO.AddCallback.BaseMixin.addCallback(self, callFunc, callNow=callNow)

    def getMsg(self):
        """Get message data in the simplest form possible

        @return msgStr, where msgStr is getKeyValMsg if both _textMsg and _hubMsg are available,
            else whichever one is available, else ""
        """
        if self._hubMsg and self._textMsg:
            return self.getKeyValMsg()[1]
        else:
            return self._textMsg or self._hubMsg

    def getKeyValMsg(self, textPrefix=""):
        """Get message data as (msgCode, msgStr), where msgStr is in keyword-value format

        @param[in] textPrefix: a prefix added to self._textMsg
        @return two values:
        - msgCode: message code (e.g. "W")
        - msgStr: message string: a combination of _textMsg and _hubMsg in keyword-value format
        """
        msgCode = self._MsgCodeDict[self._state]
        msgInfo = []
        if self._hubMsg:
            msgInfo.append(self._hubMsg)
        if self._textMsg or textPrefix:
            msgInfo.append("Text=%s" % (quoteStr(textPrefix + self._textMsg),))
        msgStr = "; ".join(msgInfo)
        return (msgCode, msgStr)

    def setState(self, newState, textMsg="", hubMsg=""):
        """Set the state of the command and call callbacks.
        
        If new state is done then remove all callbacks (after calling them).
        
        @param[in] newState: new state of command
        @param[in] textMsg: a message to be printed using the Text keyword
        @param[in] hubMsg: a message in keyword=value format (without a header)

        If the new state is Failed then please supply a textMsg and/or hubMsg.
        
        Error conditions:
        - Raise RuntimeError if this command is finished.
        """
        # print "%r.setState(newState=%s); self._cmdToTrack=%r" % (self, newState, self._cmdToTrack)
        if self.isDone:
            raise RuntimeError("Command %s is done; cannot change state" % str(self))
        if newState not in self.AllStates:
            raise RuntimeError("Unknown state %s" % newState)
        if self._state == self.Ready and newState in self.ActiveStates and self._timeLim:
            self._timeoutTimer.start(self._timeLim, self._timeout)
        self._state = newState
        self._textMsg = str(textMsg)
        self._hubMsg = str(hubMsg)
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
            if self._timeoutTimer.isActive:
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
    
    def __str__(self):
        return "%s(%r)" % (self.__class__.__name__, self.cmdStr)
    
    def __repr__(self):
        return "%s(cmdStr=%r, userID=%r, cmdID=%r, timeLim=%r, state=%r)" % \
            (self.__class__.__name__, self.cmdStr, self.userID, self.cmdID, self._timeLim, self._state)

class DevCmd(BaseCmd):
    """Generic device command
    
    You may wish to subclass to override the following:
    * fullCmdStr returns: locCmdID cmdStr
    
    Useful attributes:
    - dev: device being commanded (if specified, as it will be for calls to Device.startCmd)
    - locCmdID: command ID number (assigned when the device command is created);
        this is the command ID for the command sent to the device
    """
    _LocCmdIDGen = RO.Alg.IDGen(startVal=1, wrapVal=sys.maxint)
    def __init__(self,
        cmdStr,
        callFunc = None,
        userCmd = None,
        timeLim = None,
        dev = None,
    ):
        """Construct a DevCmd
        
        @param[in] cmdStr: command string
        @param[in] callFunc: function to call when command changes state, or None;
            receives one argument: this command
        @param[in] userCmd: user command whose state is to track this command, or None
        @param[in] timeLim: time limit for command (sec); if None or 0 then no time limit
        @param[in] dev: device being commanded; for simple actors and devices this can probably be left None,
            but for complex actors it can be very helpful information, e.g. for callback functions

        If userCmd is specified then its state is set to the same state as the device command
        when the device command is done (e.g. Cancelled, Done or Failed). However, if the userCmd times out
        then
        If callFunc and userCmd are both specified, callFunc is called before userCmd's state is changed.
        """
        self.locCmdID = self._LocCmdIDGen.next()
        self.dev = dev
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
        dev = None,
    ):
        """Construct an DevCmdVar
        
        @param[in] cmdVar: the command variable to wrap (an instance of opscore.actor.CmdVar)
        @param[in] callFunc: function to call when command changes state;
            receives one argument: this command
        @param[in] userCmd: a user command that will track this new device command
        @param[in] timeLim: time limit for command (sec); if None or 0 then no time limit
        """
        BaseCmd.__init__(self,
            cmdStr = "", # instead of copying cmdVar.cmdStr, override the cmdStr property below
            callFunc = callFunc,
            timeLim = timeLim,
        )
        self.dev = dev

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
    
        @param[in] userID    ID of user (always 0 if a single-user actor)
        @param[in] cmdStr    full command
        @param[in] callFunc  function to call when command finishes or fails;
                    the function receives two arguments: this UserCmd, isOK
        @param[in] timeLim: time limit for command (sec); if None or 0 then no time limit
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
        
        @param[in] cmdStr: command string (see module doc string for format)
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
