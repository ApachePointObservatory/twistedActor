
"""!Contains objects for managing multiple commands at once.
"""
from bisect import insort_left

from opscore.RO.Comm.TwistedTimer import Timer

from .command import UserCmd

__all__ = ["CommandQueue"]

class QueuedCommand(object):
    # state constants
    Done = "done"
    Cancelled = "cancelled" # including superseded
    Failed = "failed"
    Ready = "ready"
    Running = "running"
    Cancelling = "cancelling"
    Failing = "failing"
    def __init__(self, cmd, priority, runFunc):
        """!The type of object queued in the CommandQueue.

            @param[in] cmd  a twistedActor BaseCmd with a cmdVerb attribute
            @param[in] priority  an integer, or CommandQueue.Immediate
            @param[in] runFunc  function that runs the command; called once, when the command is ready to run,
                just after cmd's state is set to cmd.Running; receives one argument: cmd
        """
        if not hasattr(cmd, 'cmdVerb'):
            raise RuntimeError('QueuedCommand must have a cmdVerb')
        if not callable(runFunc):
            raise RuntimeError('QueuedCommand must receive a callable function')

        if priority != CommandQueue.Immediate:
            try:
                priority = int(priority)
            except:
                raise RuntimeError("priority=%r; must be an integer or QueuedCommand.Immediate" % (priority,))
        self.cmd = cmd
        self.priority = priority
        self.runFunc = runFunc

    def setState(self, newState, textMsg=None, hubMsg=None):
        """!Set state of command; see twistedActor.BaseCmd.setState for details
        """
        # print("%r.setState(newState=%r, textMsg=%r, hubMsg=%r)" % (self, newState, textMsg, hubMsg))
        return self.cmd.setState(newState, textMsg, hubMsg)

    def setRunning(self):
        """!Set the command state to Running, and execute associated code
        """
        if self.cmd.state != self.cmd.Ready:
            raise RuntimeError("Cannot set %r running, command not ready"%self.cmd)
        self.cmd.setState(self.cmd.Running)
        # print("%s.setRunning(); self.cmd=%r" % (self, self.cmd))
        self.runFunc(self.cmd)

    @property
    def cmdVerb(self):
        return self.cmd.cmdVerb

    @property
    def cmdStr(self):
        return self.cmd.cmdStr

    @property
    def didFail(self):
        """!Command failed or was cancelled
        """
        return self.cmd.didFail

    @property
    def isActive(self):
        """!Command is running, canceling or failing
        """
        return self.cmd.isActive

    @property
    def isDone(self):
        """!Command is done (whether successfully or not)
        """
        return self.cmd.isDone

    @property
    def state(self):
        """!The state of the command, as a string which is one of the state constants, e.g. self.Done
        """
        return self.cmd.state

    # overridden methods mainly for sorting purposes
    def __lt__(self, other):
        if (self.priority == CommandQueue.Immediate) and (other.priority != CommandQueue.Immediate):
            return False
        elif (self.priority != CommandQueue.Immediate) and (other.priority == CommandQueue.Immediate):
            return True
        else:
            return self.priority < other.priority

    def __gt__(self, other):
        if self.priority == other.priority:
            return False
        else:
            return not (self < other)

    def __eq__(self, other):
        return self.priority == other.priority

    def __ne__(self, other):
        return not (self == other)

    def __le__(self, other):
        return (self == other) or (self < other)

    def __ge__(self, other):
        return (self == other) or (self > other)

    def __str__(self):
        return "%s(cmd=%s)" % (type(self).__name__, self.cmd)

    def __repr__(self):
        return "%s(cmd=%r)" % (type(self).__name__, self.cmd)


class CommandQueue(object):
    """!A command queue.  Default behavior is to queue all commands and
    execute them one at a time in order of priority.  Equal priority commands are
    executed in the order received.  Special rules may be defined for handling special cases
    of command collisions.
    """
    Immediate = 'immediate'
    CancelNew = 'cancelnew'
    CancelQueued = 'cancelqueued'
    KillRunning = 'killrunning'
    _AddActions = frozenset((CancelNew, CancelQueued, KillRunning))
    def __init__(self, priorityDict, killFunc=None):
        """ This is an object which keeps track of commands and smartly handles
            command collisions based on rules chosen by you.
            @param[in] priorityDict a dictionary keyed by cmdVerb, with integer values or Immediate
            @ param[in] killFunc: a function to call when a running command needs to be
                killed.  Accepts 2 parameters, the command to be canceled, and the command doing the killing.
                This function must eventually ensure that the running command is canceled safely
                allowing for the next queued command to go. Or None
        """
        self.cmdQueue = []
        dumCmd = UserCmd()
        dumCmd.setState(dumCmd.Done)
        dumCmd.cmdVerb = 'dummy'
        self.currExeCmd = QueuedCommand(dumCmd, 0, lambda cmdVar: None)
        self.priorityDict = priorityDict
        self.killFunc = killFunc
        self.ruleDict = {}
        self.queueTimer = Timer()
        self._enabled = True

    def __getitem__(self, ind):
        return self.cmdQueue[ind]

    def __len__(self):
        return len(self.cmdQueue)

    def addRule(self, action, newCmds="all", queuedCmds="all"):
        """!Add special case rules for collisions.

        @param[in] action  one of CancelNew, CancelQueued, KillRunning
        @param[in] newCmds  a list of incoming commands to which this rule applies or "all"
        @param[in] queuedCmds  a list of the commands (queued or running) to which this rule applies or "all"

        See documentation for the addCommand method to learn exactly how rules are evaluated
        """
        if action == self.KillRunning and self.killFunc is None:
            raise RuntimeError("must supply killFunc in CommandQueue constructor before specifying a KillRunning rule")
        checkCmds = []
        if newCmds != "all":
            checkCmds = checkCmds + newCmds
        else:
            newCmds = ["all"]
        if queuedCmds != "all":
            checkCmds = checkCmds + queuedCmds
        else:
            queuedCmds = ["all"]
        for cmdName in checkCmds:
            if cmdName not in self.priorityDict:
                raise RuntimeError('Cannot add rule to unrecognized command: %s' % (cmdName,))
        if action not in self._AddActions:
            raise RuntimeError("Rule action=%r must be one of %s" % (action, sorted(self._AddActions)))
        for nc in newCmds:
            if not nc in self.ruleDict:
                if nc == 'all':
                    # ensure any rules defined in self.ruleDict[:]["all"]
                    # are the same action:
                    for existingDict in self.ruleDict.values():
                        if "all" in existingDict and action != existingDict["all"]:
                            raise RuntimeError("May not specifiy conflicting rules pertaining to all queued commands and all new commands")
                self.ruleDict[nc] = {}
            for qc in queuedCmds:
                if qc in self.ruleDict[nc] and self.ruleDict[nc][qc] != action:
                    raise RuntimeError(
                        'Cannot set rule=%r for new command=%s vs. queued command=%s: already set to %s' % \
                        (action, nc, qc, self.ruleDict[nc][qc])
                    )
                if qc == "all":
                    if "all" in self.ruleDict:
                        for value in self.ruleDict["all"].values():
                            if value != action:
                                raise RuntimeError("May not specifiy conflicting rules pertaining to all queued commands and all new commands")
                self.ruleDict[nc][qc] = action

    def getRule(self, newCmd, queuedCmd):
        """!Get the rule for a specific new command vs. a specific queued command.

        @param[in] newCmd  the incoming command verb
        @param[in] queuedCmd  a command verb currently on the queue
        @return a rule, one of self._AddActions

        Note: there is some logic to determine which rule is grabbed:

        If a specific rule exists between the newCmd and queuedCmd, that is returned. This trumps
        the situation in which there may be a rule defined involving newCmd or queuedCmd pertaining to
        all new commands or all queued commands.

        If newCmd and queuedCmd are the same command and are not present in the ruleDict nor priorityDict
        return the default rule of CancelQueued (effectively the new cmd will replace the one on queue)

        If no specific rule exists between newCmd and queuedCmd, check if a rule is defined between both:
            1. newCmd and all queued commands
            2. all new commands and queuedCmd
        If a different rule is present for both 1 and 2, raise a RuntimeError, we have over defined things.
        Else if a rule is defined for either 1 or 2 (or the same rule is present for 1 and 2), use it.
        """
        if (newCmd in self.ruleDict) and (queuedCmd in self.ruleDict[newCmd]):
            # a command was specifically defined for these two
            # this trumps any rules that may apply to "all"
            return self.ruleDict[newCmd][queuedCmd]
        if (newCmd == queuedCmd) and (newCmd not in self.priorityDict) and (newCmd not in self.ruleDict):
            return self.CancelQueued
        if ("all" in self.ruleDict) and (queuedCmd in self.ruleDict["all"]):
            # a command was defined for all incoming commands when
            # encountering this specific command on the queue
            rule = self.ruleDict["all"][queuedCmd]
            # now for paranoia, make sure a different rule was not
            # defined for the reverse set
            if (newCmd in self.ruleDict) and ("all" in self.ruleDict[newCmd]):
                if self.ruleDict[newCmd]["all"] != rule:
                    raise RuntimeError("Conflict when trying to apply a rule 'all' commands on queue. This should have been caught in CommandQueue.addRule")
            return rule
        elif (newCmd in self.ruleDict) and ("all" in self.ruleDict[newCmd]):
            # newCmd has rule defined for all queued commands
            return self.ruleDict[newCmd]["all"]
        elif ("all" in self.ruleDict) and ("all" in self.ruleDict["all"]):
            # the rule always applies!!!
            return self.ruleDict["all"]["all"]
        else:
            return None

    def addCmd(self, cmd, runFunc):
        """ Add a command to the queue, taking rules and priority into account.

            @param[in] cmd  a twistedActor command object
            @param[in] runFunc  function that runs the command; called once, when the command is ready to run,
                just after cmd's state is set to cmd.Running; receives one argument: cmd

            Here's the logic:
            If cmd has an unrecognized priority (not defined in self.priorityDict), assign it a priority of 0
            If cmd as a priority of Immediate:
                - Completely clear the queue, and kill the currently executing command (if it is still active)
                - Add the command to the now empty queue
            Else:
                Look for rules.  You may want to read the documentation for getRule, as there is some logic in the
                way rules are selected.  First, run through all commands currently on the queue.  If any queued
                command has a rule CancelNew pertaining to this command, then cancel the incoming command and return
                (it never reaches the queue). If the command wasn't canceled, run through the queue again to determine
                if this command should cancel any commands on the queue.

                Then check to see if this cmd should kill any currently executing command.

                Lastly insert the command in the queue in order based on it's priority.
        """
        if not hasattr(cmd, "cmdVerb"):
            # give it a dummy command verb
            cmd.cmdVerb = "dummy"
        if cmd.cmdVerb not in self.priorityDict:
            # no priority pre-defined.  Assign lowest priority
            priority = 0
        else:
            priority = self.priorityDict[cmd.cmdVerb]

        toQueue = QueuedCommand(
            cmd = cmd,
            priority = priority,
            runFunc = runFunc,
        )
        if toQueue.priority == CommandQueue.Immediate:
            # cancel each command in the cmdQueue;
            # iterate over a copy because the queue is updated for each cancelled command,
            # and extract the cmd from the queuedCmd since we don't need the wrapped command
            cmdList = [queuedCmd.cmd for queuedCmd in self.cmdQueue]
            for sadCmd in cmdList:
                if not sadCmd.isDone:
                    sadCmd.setState(
                        sadCmd.Cancelled,
                        textMsg = "Cancelled on queue by immediate priority command %r" % (cmd.cmdStr,),
                    )
            if not self.currExeCmd.cmd.isDone:
                self.currExeCmd.cmd.setState(
                    self.currExeCmd.cmd.Cancelled,
                    textMsg = "Killed by immediate priority command %r" % (cmd.cmdStr,),
                )
        else:
            # check new command against queued commands
            # iterate over a copy because the queue is updated for each cancelled command,
            # and extract the cmd from the queuedCmd since we don't need the wrapped command
            cmdList = [queuedCmd.cmd for queuedCmd in self.cmdQueue]
            for queuedCmd in cmdList:
                # first check if toQueue should be cancelled by any existing
                # command on the queue
                if queuedCmd.isDone:
                    # ignore completed commands (not that any on the stack will have been run yet,
                    # but they can be cancelled elsewhere)
                    continue

                action = self.getRule(toQueue.cmd.cmdVerb, queuedCmd.cmdVerb)
                if action == self.CancelNew:
                    toQueue.cmd.setState(
                        toQueue.cmd.Cancelled,
                        "Cancelled before queueing by queued command %r" % (queuedCmd.cmdStr),
                    )
                    return # queue not altered; no need to do anything else
            for queuedCmd in cmdList:
                # next check if toQueue should cancel any commands existing on the
                # queue
                if queuedCmd.isDone:
                    # ignore completed commands
                    continue
                action = self.getRule(toQueue.cmd.cmdVerb, queuedCmd.cmdVerb)
                if action in (self.CancelQueued, self.KillRunning):
                    queuedCmd.setState(
                        queuedCmd.Cancelled,
                        "Cancelled while queued by new command %r" % (toQueue.cmd.cmdStr),
                    )

            # should new command kill currently executing command?
            if not self.currExeCmd.cmd.isDone:
                action = self.getRule(toQueue.cmd.cmdVerb, self.currExeCmd.cmd.cmdVerb)
                if action == self.CancelNew:
                    toQueue.cmd.setState(
                        toQueue.cmd.Cancelled,
                        "Cancelled before queueing by running command %r" % (self.currExeCmd.cmd.cmdStr),
                    )
                    return # queue not altered; no need to do anything else
                if action == self.KillRunning:
                    self.killFunc(self.currExeCmd.cmd, toQueue.cmd)

        insort_left(self.cmdQueue, toQueue) # inserts in sorted order
        self.scheduleRunQueue()

    def killAll(self):
        """!Kill all commands without trying to execute any

        Use when there is no hope of sending commands, e.g. at shutdown
        """
        self._enabled = False
        try:
            cmdList = [queuedCmd.cmd for queuedCmd in self.cmdQueue]
            for cmd in cmdList:
                if not cmd.isDone:
                    cmd.setState(cmd.Failed, textMsg="disconnected")
            self.cmdQueue = []
            if not self.currExeCmd.cmd.isDone:
                self.currExeCmd.setState(self.currExeCmd.Failed, textMsg="disconnected")
        finally:
            self._enabled = True

    def scheduleRunQueue(self, cmd=None):
        """!Run the queue on a zero second timer

        @param[in] cmd  command; if provided and not Done then the queue is not run (a BaseCmd);
            this allows use of scheduleRunQueue as a command callback
        """
        if not self._enabled:
            return
        if cmd and not cmd.isDone:
            return
        self.queueTimer.start(0., self.runQueue)

    def runQueue(self):
        """ Manage Executing commands
        """
        if not self._enabled:
            return
        # prune the queue, throw out done commands
        self.cmdQueue = [qc for qc in self.cmdQueue if not qc.cmd.isDone]
        if len(self.cmdQueue) == 0:
            # the command queue is empty, nothing to run
            pass
        elif self.currExeCmd.cmd.isDone:
            # begin the next command on the queue
            self.currExeCmd = self.cmdQueue.pop(-1)
            self.currExeCmd.setRunning()
            self.currExeCmd.cmd.addCallback(self.scheduleRunQueue)

    def __repr__(self):
        cmdList = ", ".join([x.cmdStr for x in self.cmdQueue])
        return "[" + cmdList + "]"
