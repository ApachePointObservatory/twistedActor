"""Contains objects for managing multiple commands at once.
"""
from bisect import insort_left

from .command import UserCmd

__all__ = ["LinkCommands", "CommandQueue"]

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

        failedCmds = ["%s: %s" % (subCmd.cmdStr, subCmd.textMsg) for subCmd in self.subCmdList if subCmd.didFail]
        if failedCmds:
            # at least one device command failed, fail the user command and say why
            state = self.mainCmd.Failed
            summaryStr = "; ".join(failedCmds)
            textMsg = "Sub-command(s) failed: %s" % (summaryStr,)
        else:
            # all device commands terminated successfully
            # set user command to done
            state = self.mainCmd.Done
            textMsg = ""
        self.mainCmd.setState(state, textMsg = textMsg)


class QueuedCommand(object):
    def __init__(self, cmd, priority, callFunc):
        """The type of object queued in the CommandQueue.

            @param[in] cmd: a twistedActor BaseCmd, but must have a cmdVerb attribute!!!!
            @param[in] priority: an integer, or CommandQueue.Immediate
            @param[in] callFunc: function to call when cmd is exectued,
                receives no arguments (use lambda to pass arguments!)
        """
        if not hasattr(cmd, 'cmdVerb'):
            raise RuntimeError('QueuedCommand must have a cmdVerb')
        if not callable(callFunc):
            raise RuntimeError('QueuedCommand must receive a callable function')
        try:
            priority = int(priority)
        except:
            if priority != CommandQueue.Immediate:
                raise RuntimeError('QueuedCommand must receive a priority ' \
                    'which is an integer or QueuedCommand.Immediate')
        self.cmd = cmd
        self.priority = priority
        self.callFunc = callFunc

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
        self.currExeCmd = QueuedCommand(dumCmd, 0, lambda: '')
        self.killFunc = killFunc
        self.priorityDict = priorityDict
        self.ruleDict = {}


    def __getitem__(self, ind):
        return self.cmdQueue[ind]

    def __len__(self):
        return len(self.cmdQueue)

    def addRule(self, action, newCmds, queuedCmds):
        """Add special case rules for collisions.

        @param[in] action: one of CancelNew, CancelQueued, KillRunning
        @param[in] newCmds: a list of incoming commands to which this rule applies
        @param[in] queuedCmds: a list of the commands presently on the queue
            (or running) to which this rule applies
        """
        for cmdName in newCmds + queuedCmds:
            if cmdName not in self.priorityDict:
                raise RuntimeError('Cannont add rule to unrecognized command: %s' % (cmdName,))
        if action not in (self.CancelNew, self.CancelQueued, self.KillRunning):
            raise RuntimeError(
                'Rule action must be one of %s, %s, or %s. Received: %s' % \
                (self.CancelNew, self.CancelQueued, self.KillRunning, action)
            )
        for nc in newCmds:
            if not nc in self.ruleDict:
                self.ruleDict[nc] = {}
            for qc in queuedCmds:
                if qc in self.ruleDict[nc]:
                    raise RuntimeError(
                        'Cannot set Rule: %s for new command %s vs queued' \
                        ' command %s.  Already set to %s' % \
                        (action, nc, qc, self.ruleDict[nc][qc])
                    )
                self.ruleDict[nc][qc] = action

    def getRule(self, newCmd, queuedCmd):
        if (newCmd in self.ruleDict) and (queuedCmd in self.ruleDict[newCmd]):
            return self.ruleDict[newCmd][queuedCmd]
        else:
            return None

    def addCmd(self, cmd, callFunc):
        """ Add a command to the queue.

            @param[in] cmd: a twistedActor command object
            @param[in] callFunc: callback function to add to the command
        """
        if cmd.cmdVerb not in self.priorityDict:
            raise RuntimeError('Cannot queue unrecognized command: %s' % (cmd.cmdVerb,))

        toQueue = QueuedCommand(
            cmd = cmd,
            priority = self.priorityDict[cmd.cmdVerb],
            callFunc = callFunc
        )

#         if self.currExeCmd.cmd.isActive and (self.currExeCmd.priority == CommandQueue.Immediate):
#             # queue is locked until the immediate priority command is finished
#             toQueue.cmd.setState(
#                 toQueue.cmd.Cancelled,
#                 'Cancelled by a currently executing command %s' % (self.currExeCmd.cmd.cmdVerb)
#             )
#             return

        toQueue.cmd.addCallback(self.runQueue)

        if toQueue.priority == CommandQueue.Immediate:
            # clear the cmdQueue
            ditchTheseCmds = [q.cmd for q in self.cmdQueue] # will be canceled
            insort_left(self.cmdQueue, toQueue)
            for sadCmd in ditchTheseCmds:
                sadCmd.setState(sadCmd.Cancelled)
            if not self.currExeCmd.cmd.isDone:
                self.killFunc(self.currExeCmd.cmd)
            self.runQueue()
        else:
            for cmdOnStack in self.cmdQueue[:]: # looping through queue from highest to lowest priority
                if cmdOnStack < toQueue:
                    # all remaining queued commands
                    # are of lower priority.
                    # and will not effect the incoming command in any way
                    break
                # check for rule between incoming command and the existing commands
                # ahead on the queue
                action = self.getRule(toQueue.cmd.cmdVerb, cmdOnStack.cmd.cmdVerb)
                if action:
                    if (action==self.CancelNew):
                        # cancel the incoming command before ever running
                        # never reaches the queue
                        toQueue.cmd.setState(
                            toQueue.cmd.Cancelled,
                            'Cancelled by a preceeding command in the queue %s' % (cmdOnStack.cmd.cmdVerb)
                        )
                        return
                    else:
                        # must be a cancel other command
                        assert action in (self.CancelQueued, self.KillRunning)
                        # cancel the queued command, only other action option
                        # note the command will automatically remove itself from the queue
                        cmdOnStack.cmd.setState(
                            cmdOnStack.cmd.Cancelled,
                            'Cancelled by a new command added to the queue %s' % (toQueue.cmd.cmdVerb)
                        )
                elif cmdOnStack.cmd.cmdVerb == toQueue.cmd.cmdVerb:
                    # newer command should supersede the old
                    cmdOnStack.cmd.setState(
                        cmdOnStack.cmd.Cancelled,
                        'Superseded by a new command added to the queue %s' % (toQueue.cmd.cmdVerb)
                    )

            insort_left(self.cmdQueue, toQueue) # inserts in sorted order
            self.runQueue()

    def runQueue(self, optCmd=None):
        """ Manage Executing commands

        @param[in] optCmd: a BaseCommand, to be used incase of callback
        """
        if optCmd != None:
            if not optCmd.isDone:
                return
        # prune the queue, throw out done commands
        self.cmdQueue = [qc for qc in self.cmdQueue[:] if (not qc.cmd.isDone)]
        if len(self.cmdQueue) == 0:
            # the command queue is empty, nothing to run
            pass
        elif self.currExeCmd.cmd.isDone:
            # begin the next command on the queue
            self.currExeCmd = self.cmdQueue.pop(-1)
            self.currExeCmd.cmd.setState(self.currExeCmd.cmd.Running)
            self.currExeCmd.callFunc()
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