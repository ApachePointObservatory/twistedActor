"""Command objects for the Tcl Actor
"""
__all__ = ["CommandError", "BaseCmd", "DevCmd", "DevCmdVar", "UserCmd", "LinkCommands", "CommandQueue"]

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


class LinkCommands(object):
    """Link commands such that completion of the main command depends on one or more sub-commands
    
    The main command is done when all sub-commands are done; the main command finishes
    successfully only if all sub-commands finish successfully.
    
    @note: To use, simply construct this object; you need not keep a reference to the resulting instance.
    
    @note: if early termination behavior is required it can easily be added as follows:
    - add an alternate callback function that fails early;
        note that on early failure it must remove the callback on any sub-commands that are not finished
        (or fail the sub-commands, but that is probably too drastic)
    - add a failEarly argument to __init__ and have it assign the alternate callback
    """
    def __init__(self, mainCmd, subCmdList):
        """Link a main command to a collection of sub-commands
        
        @param[in] mainCmd: the main command, a BaseCmd
        @param[in] subCmdList: a collection of sub-commands, each a BaseCmd
        """
        self.mainCmd = mainCmd
        self.subCmdList = subCmdList
        for subCmd in self.subCmdList:
            if not subCmd.isDone:
                subCmd.addCallback(self.subCmdCallback)

        # call right away in case all sub-commands are already done
        self.subCmdCallback()

    def subCmdCallback(self, dumCmd=None):
        """Callback to be added to each device cmd

        @param[in] dumCmd: sub-command issuing the callback (ignored)
        """
        if not all(subCmd.isDone for subCmd in self.subCmdList):
            # not all device commands have terminated so keep waiting
            return

        failedCmds = [(subCmd.cmdStr, subCmd.fullState) for subCmd in self.subCmdList if subCmd.didFail]
        if failedCmds:
            # at least one device command failed, fail the user command and say why
            state = self.mainCmd.Failed
            textMsg = "Sub-command(s) failed: %s" % failedCmds
        else:
            # all device commands terminated successfully
            # set user command to done
            state = self.mainCmd.Done
            textMsg = ''
        self.mainCmd.setState(state, textMsg = textMsg)

class CommandRule(object):
    """simple object for defining collision rules
    """
    def __init__(self, cmdVerb, action, otherCmdVerbs):
        """ @param[in] cmdVerb: a command verb string
            @param[in] action: an action string, either 'supersedes' or 'waitsfor'
            @param[in] otherCmdVerbs: a list of all other cmd verbs that the action
                should apply to. 'all' will apply action to any command. 
                Default action is to fail the command.
        """ 
        if action.lower() not in ['supersedes', 'waitsfor']:
            raise RuntimeError('action must be on of "supersedes" or "waitsfor"')
        self.cmdVerb = cmdVerb
        self.action = action
        self.otherCmdVerbs = otherCmdVerbs

class CommandQueue(object):
    """This is an object which keeps track of commands and smartly handles 
    command collisions based on rules chosen by you.
    
    This modifies original commands to be callable.  The callable is 
    specified by outside code (likely a Device) when a command is added to the queue.
    The __call__ attribue is deleted once a command is removed from the queue
    """
    def __init__(self):
        self.cmdQueue = []
        self.ruleDict = {}
        self._interrupt = None
 
    def __getitem__(self, ind):
        return self.cmdQueue[ind]

    def __len__(self):
        return len(self.cmdQueue)
        
    def addRule(self, cmdVerb, action, otherCmdVerbs=['all']):
        """ @param[in] cmdVerb: a command verb string
            @param[in] action: an action string, either 'supersedes' or 'waitsfor'
            @param[in] otherCmdVerbs: a list of all other cmd verbs that the action
                should apply to. 'all' will apply action to any command. 
                Default action is to fail the command.
        """ 
        self.ruleDict[cmdVerb] = CommandRule(cmdVerb, action, otherCmdVerbs)
 
    @property
    def interrupt(self):
        if self._interrupt == None:
            raise NotImplementedError('must specify interruption code')
        else:
            return self._interrupt

    def addInterrupt(self, callable):
        """callable receives 2 arguments, the interrupting command and the command being interupted.
        should set the interrupted command to done.
        """
        #self._interrupt = callable
        setattr(self, '_interrupt', callable)  
        
    def addCmd(self, cmd, callFunc, *args):
        """ @param[in] cmd: a twistedActor BaseCmd, but must have a cmdVerb attribute!!!!
            @param[in] callFunc: function to call when cmd is exectued, receives *args
            @param[in] *args, any additional arguments to be passed to callFunc
        """
        
        # make the cmd callable
        setattr(cmd, 'exe', lambda: callFunc(*args, userCmd=cmd)) # pass any args and the cmd itself
        self.cmdQueue.append(cmd)
        def removeWhenDone(cbCmd):
            """add this callback to the command to remove
            itself from the list when it had been set to done.
            """
            if not cbCmd.isDone:
                return
            # command is done, find it in the queue and pop it.
            for ind in range(len(self.cmdQueue)):
                qCmd = self.cmdQueue[ind]
                if (qCmd.userID==cbCmd.userID) and (qCmd.cmdID==cbCmd.cmdID):
                    delattr(qCmd, 'exe') # delete the callable attribute
                    del self.cmdQueue[ind] # remove the command from the queue, it's done
                    self.runQueue() # run the queue (if another command is waiting, get it going)
                    return
        cmd.addCallback(removeWhenDone)
        self.runQueue()
    
    def runQueue(self):
        """Go through the queue, start any ready commands, handle collisions, etc
        unless defined in the self.cmdPriority definitions, an earlier command
        has priority and any later commands are failed immediately.  A command
        must be told to queue itself, or to supersede (cancel) earlier commands
        
        this is executed when a new command is added to the queue, and each time
        a command on the queue is set to a done state and thus removed from the
        queue
        """
        if len(self.cmdQueue) == 0:
            # no commands on queue, nothing happening.
            return
        mostRecentCmd = self.cmdQueue[-1]
        # start from 2nd most recent command, and loop towards the oldest
        # (counting backwards)
        for olderCmd in self.cmdQueue[-2::-1]:
            # note: will never enter this loop if the mostRecentCmd is
            # the only command in the queue...
            if olderCmd.state == olderCmd.Cancelling:
                continue
            try:
                rule = self.ruleDict[mostRecentCmd.cmdVerb]
            except KeyError:
                # no rule for this command, fail it, because there are other 
                # commands in the queue.
                mostRecentCmd.setState(
                    mostRecentCmd.Failed, 
                    'Command rejected, current commands executing/queued'
                )
            else:
                # rule is specified for mostRecentCmd
                if not ((olderCmd.cmdVerb in rule.otherCmdVerbs) or ('all' in rule.otherCmdVerbs)):
                    # no rule specified for this olderCmd, fail the mostRecentCmd
                    # as there are other commands currently in the queue (executing or not).
                    mostRecentCmd.setState(
                        mostRecentCmd.Failed, 
                        'Command rejected, current commands executing/queued'
                    )                      
                else:
                    # a rule pertains, sort it out  
                    if rule.action == 'waitsfor':
                        # easy, do nothing, but leave it in the queue where it is.
                        pass
                    elif olderCmd.state == olderCmd.Running:
                        # action is supersede and the command is running
                        olderCmd.setState(olderCmd.Cancelling)
                        #self.interrupt(mostRecentCmd, olderCmd)
                        #olderCmd.setState(olderCmd.Failed, '%s cancelled whilst running by the higher priority command: %s' % (olderCmd.cmdVerb, mostRecentCmd.cmdVerb,))
                    else:
                        # action is supersed and command is ready (not running)
                        olderCmd.setState(olderCmd.Cancelled, '%s command cancelled whilst queued behind higher priority command: %s'% (olderCmd.cmdVerb, mostRecentCmd.cmdVerb,))
        oldestCmd = self.cmdQueue[0]
        if oldestCmd.state == oldestCmd.Ready:
            # start it running
            oldestCmd.setState(oldestCmd.Running)
            oldestCmd.exe()

    