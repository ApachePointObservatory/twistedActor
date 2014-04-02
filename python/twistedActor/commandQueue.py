from __future__ import division, absolute_import
"""Contains objects for managing multiple commands at once.
"""
from bisect import insort_left

from RO.Comm.TwistedTimer import Timer

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
        """The type of object queued in the CommandQueue.

            @param[in] cmd: a twistedActor BaseCmd with a cmdVerb attribute
            @param[in] priority: an integer, or CommandQueue.Immediate
            @param[in] runFunc: function that runs the command; called once, when the command is ready to run,
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

    def setState(self, newState, textMsg="", hubMsg=""):
        """Set state of command; see twistedActor.BaseCmd.setState for details
        """
        # print "%r.setState(newState=%r, textMsg=%r, hubMsg=%r)" % (self, newState, textMsg, hubMsg)
        return self.cmd.setState(newState, textMsg, hubMsg)

    def setRunning(self):
        """Set the command state to Running, and execute associated code
        """
        self.cmd.setState(self.cmd.Running)
        # print "%s.setRunning(); self.cmd=%r" % (self, self.cmd)
        self.runFunc(self.cmd)

    @property
    def cmdVerb(self):
        return self.cmd.cmdVerb

    @property
    def cmdStr(self):
        return self.cmd.cmdStr

    @property
    def didFail(self):
        """Command failed or was cancelled
        """
        return self.cmd.didFail

    @property
    def isActive(self):
        """Command is running, canceling or failing
        """
        return self.cmd.isActive

    @property
    def isDone(self):
        """Command is done (whether successfully or not)
        """
        return self.cmd.isDone

    @property
    def state(self):
        """The state of the command, as a string which is one of the state constants, e.g. self.Done
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
        return "%s(cmdVerb=%r)" % (type(self).__name__, self.cmdVerb)

    def __repr__(self):
        return "%s(cmd=%r)" % (type(self).__name__, self.cmd)


class CommandQueue(object):
    """A command queue.  Default behavior is to queue all commands and
    execute them one at a time in order of priority.  Equal priority commands are
    executed in the order received.  Special rules may be defined for handling special cases
    of command collisions.
    """
    Immediate = 'immediate'
    CancelNew = 'cancelnew'
    CancelQueued = 'cancelqueued'
    KillRunning = 'killrunning'
    _AddActions = frozenset((CancelNew, CancelQueued, KillRunning))
    def __init__(self, killFunc, priorityDict):
        """ This is an object which keeps track of commands and smartly handles
            command collisions based on rules chosen by you.

            @ param[in] killFunc: a function to call when a running command needs to be
                killed.  Accepts 1 parameter, the command to be canceled.  This function
                must eventually ensure that the running command is canceled safely
                allowing for the next queued command to go.
            @ a dictionary keyed by cmdVerb, with integer values or Immediate
        """
        self.cmdQueue = []
        dumCmd = UserCmd()
        dumCmd.setState(dumCmd.Done)
        dumCmd.cmdVerb = 'dummy'
        self.currExeCmd = QueuedCommand(dumCmd, 0, lambda cmdVar: None)
        self.killFunc = killFunc
        self.priorityDict = priorityDict
        self.ruleDict = {}
        self.queueTimer = Timer()

    def __getitem__(self, ind):
        return self.cmdQueue[ind]

    def __len__(self):
        return len(self.cmdQueue)

    def addRule(self, action, newCmds, queuedCmds):
        """Add special case rules for collisions.

        @param[in] action: one of CancelNew, CancelQueued, KillRunning
        @param[in] newCmds: a list of incoming commands to which this rule applies
        @param[in] queuedCmds: a list of the commands (queued or running) to which this rule applies
        """
        for cmdName in newCmds + queuedCmds:
            if cmdName not in self.priorityDict:
                raise RuntimeError('Cannot add rule to unrecognized command: %s' % (cmdName,))
        if action not in self._AddActions:
            raise RuntimeError("Rule action=%r must be one of %s" % (action, sorted(self._AddActions)))
        for nc in newCmds:
            if not nc in self.ruleDict:
                self.ruleDict[nc] = {}
            for qc in queuedCmds:
                if qc in self.ruleDict[nc]:
                    raise RuntimeError(
                        'Cannot set rule=%r for new command=%s vs. queued command=%s: already set to %s' % \
                        (action, nc, qc, self.ruleDict[nc][qc])
                    )
                self.ruleDict[nc][qc] = action

    def getRule(self, newCmd, queuedCmd):
        """Get the rule for a specific new command vs. a specific queued command
        """
        if (newCmd in self.ruleDict) and (queuedCmd in self.ruleDict[newCmd]):
            return self.ruleDict[newCmd][queuedCmd]
        else:
            return None

    def addCmd(self, cmd, runFunc):
        """ Add a command to the queue.

            @param[in] cmd: a twistedActor command object
            @param[in] runFunc: function that runs the command; called once, when the command is ready to run,
                just after cmd's state is set to cmd.Running; receives one argument: cmd
        """
        if cmd.cmdVerb not in self.priorityDict:
            raise RuntimeError('Cannot queue unrecognized command: %s' % (cmd.cmdVerb,))

        # print "Queue. Incoming: %r, on queue: " %cmd, [q.cmd for q in self.cmdQueue]
        toQueue = QueuedCommand(
            cmd = cmd,
            priority = self.priorityDict[cmd.cmdVerb],
            runFunc = runFunc,
        )

        if toQueue.priority == CommandQueue.Immediate:
            # cancel each command in the cmdQueue;
            # iterate over a copy because the queue is updated for each cancelled command,
            # and extract the cmd from the queuedCmd since we don't need the queued command
            cmdList = [queuedCmd.cmd for queuedCmd in self.cmdQueue]
            for sadCmd in cmdList:
                if not sadCmd.isDone:
                    sadCmd.setState(sadCmd.Cancelled, "Cancelled on queue by immediate priority command: %r" % cmd)
            if not self.currExeCmd.cmd.isDone:
                self.killFunc(self.currExeCmd.cmd)
        else:
            for cmdOnStack in self.cmdQueue[:]: # looping through queue from highest to lowest priority
                if cmdOnStack < toQueue or cmdOnStack.isDone:
                    # command is lower priority or done; don't worry about it
                    break

                action = self.getRule(toQueue.cmd.cmdVerb, cmdOnStack.cmd.cmdVerb)
                if action and action==self.CancelNew:
                    # cancel the incoming command before ever running
                    # never reaches the queue
                    toQueue.cmd.setState(
                        toQueue.cmd.Cancelled,
                        'Cancelled by a preceeding command in the queue %s' % (cmdOnStack.cmd.cmdVerb),
                    )
                    return
                elif action and action in (self.CancelQueued, self.KillRunning):
                    # cancel this command
                    # note the command will automatically remove itself from the queue
                    cmdOnStack.cmd.setState(
                        cmdOnStack.cmd.Cancelled,
                        'Cancelled by a new command added to the queue %s' % (toQueue.cmd.cmdVerb),
                    )

            # finially check if this incoming command should kill an executing command
            action = self.getRule(toQueue.cmd.cmdVerb, self.currExeCmd.cmd.cmdVerb)
            if action and action == self.KillRunning and not self.currExeCmd.cmd.isDone:
                self.killFunc(self.currExeCmd.cmd)
        insort_left(self.cmdQueue, toQueue) # inserts in sorted order
        self.scheduleRunQueue()

    def scheduleRunQueue(self, optCmd=None):
        """Run the queue on a zero second timer
        """
        # self.runQueue(optCmd)
        self.queueTimer.start(0., self.runQueue, optCmd)

    def runQueue(self, optCmd=None):
        """ Manage Executing commands

        @param[in] optCmd: a BaseCommand, to be used incase of callback
        """
        if optCmd != None:
            if not optCmd.isDone:
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

        elif self.currExeCmd.cmd.state == self.currExeCmd.cmd.Cancelling:
            # leave it alone
            pass
        elif self.getRule(self.cmdQueue[0].cmd.cmdVerb, self.currExeCmd.cmd.cmdVerb):
            action = self.getRule(self.cmdQueue[0].cmd.cmdVerb, self.currExeCmd.cmd.cmdVerb)
            # a rule exists for this collision, check if it's a kill order
            if action == self.KillRunning:
                self.killFunc(self.currExeCmd.cmd)
            elif action == self.CancelNew:
                currCmdVerb = self.currExeCmd.cmd.cmdVerb
                qCmdVerb = self.cmdQueue[0].cmd.cmdVerb
                self.cmdQueue[0].cmd.setState(
                    self.cmdQueue[0].cmd.Cancelled,
                    '%s cancelled by currently executing command: %s' \
                        % (qCmdVerb, currCmdVerb)
                )
        else:
            # command is currently active and should remain that way
            pass
