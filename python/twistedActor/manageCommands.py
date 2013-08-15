"""Contains objects for managing multiple commands at once.
"""
from .command import UserCmd
from bisect import insort_right
__all__ = ["LinkCommands", "CommandQueue", "QueuedCommand"]


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

class QueuedCommand(object):
    Immediate = 'immediate' # must match CommandQueue
    CancelMe = 'cancelme'
    CancelOther = 'cancelother'
    KillOther = 'killother'
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
            if priority != self.Immediate:
                raise RuntimeError('QueuedCommand must receive a priority ' \
                    'which is an integer or QueuedCommand.Immediate')
        self.cmd = cmd
        self.priority = priority
        self.callFunc = callFunc
        self.collideDict = {}
    
    def addCollideRule(self, cmdVerb, action):
        """ Add special handling behavior to commands colliding irregardless of priorities.
        
            @param[in] cmdVerb: the equal priority command ahead of this
            @param[in] action: one of CancelMe, QueueMe, CancelOther, KillOther
        """
        if action not in (self.CancelMe, self.CancelOther, self.KillOther):
            raise RuntimeError('Unknown action: %s' % action)
        self.collideDict[cmdVerb] = action   

    # overridden methods mainly for sorting purposes    
    def __lt__(self, other):
        if (self.priority == self.Immediate) and (other.priority != self.Immediate):
            return False
        elif (self.priority != self.Immediate) and (other.priority == self.Immediate):
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
    def __init__(self, killFunc):
        """ This is an object which keeps track of commands and smartly handles 
            command collisions based on rules chosen by you.
            
            @ param[in] killFunc: a function to call when a running command needs to be 
                killed.  Accepts 1 parameter, the command to be canceled.  This function
                must eventually ensure that the running command is canceled safely 
                allowing for the next queued command to go.
        """
        self.cmdQueue = []
        dumCmd = UserCmd()
        dumCmd.setState(dumCmd.Done)
        dumCmd.cmdVerb = 'dum'
        self.currExeCmd = QueuedCommand(dumCmd, 0, lambda: '')
        self.killFunc = killFunc
 
    def __getitem__(self, ind):
        return self.cmdQueue[ind]

    def __len__(self):
        return len(self.cmdQueue)
        
    def addCmd(self, toQueue):
        """ Add a command to the queue.
        
            @param[in] toQueue: a QueuedCommand object
        """
        if self.currExeCmd.cmd.isActive and (self.currExeCmd.priority == self.currExeCmd.Immediate):
            # queue is locked until the immediate priority command is finished
            toQueue.cmd.setState(
                toQueue.cmd.Cancelled, 
                'Cancelled by a currently executing command %s' % (self.currExeCmd.cmd.cmdVerb)
            )
            return            
            
        def removeWhenDone(cbCmd):
            """add this callback to the command so it will automatically remove
            itself from the list when it had been set to done.
            """
            if not cbCmd.isDone:
                return
            # command is done, find it in the queue and pop it.
            for ind in range(len(self.cmdQueue)):
                qCmd = self.cmdQueue[ind]
                if (qCmd.cmd.userID==cbCmd.userID) and (qCmd.cmd.cmdID==cbCmd.cmdID):
                    del self.cmdQueue[ind] # remove the command from the queue, it's done
                    self.runQueue() # run the queue (if another command is waiting, get it going)
                    return
            # incase command was removed from queue to be executed
            self.runQueue()
        toQueue.cmd.addCallback(removeWhenDone)
        
        if toQueue.priority == toQueue.Immediate:
            # clear the cmdQueue
            [q.cmd.setState(q.cmd.Cancelled) for q in self.cmdQueue] 
        else:
            for cmdOnStack in self.cmdQueue[:]: # looping through queue from highest to lowest priority
                if cmdOnStack < toQueue:
                    # all remaining queued commands
                    # are of lower priority.
                    # and will not effect the incoming command in any way
                    break
                if cmdOnStack.cmd.cmdVerb in toQueue.collideDict.keys():
                    # special handling of this collision is wanted
                    action = toQueue.collideDict[cmdOnStack.cmd.cmdVerb]
                    if (action==toQueue.CancelMe):
                        # cancel the incoming command before ever running
                        # never reaches the queue
                        toQueue.cmd.setState(
                            toQueue.cmd.Cancelled, 
                            'Cancelled by a preceeding command in the queue %s' % (cmdOnStack.cmd.cmdVerb)
                        )
                        return
                    else:
                        # cancel the queued command, only other action option 
                        # note the command will automatically remove itself from the queue
                        cmdOnStack.cmd.setState(
                            cmdOnStack.cmd.Cancelled,
                            'Cancelled by a new command added to the queue %s' % (toQueue.cmd.cmdVerb)
                        )
            
        insort_right(self.cmdQueue, toQueue) # inserts in sorted order
        self.runQueue() 
   
    def runQueue(self):
        """ Manage Executing commands
        """
        # prune the queue, throw out done commands
        self.cmdQueue = [qc for qc in self.cmdQueue[:] if not qc.cmd.isDone]
        if len(self.cmdQueue) == 0:
            # the command queue is empty, nothing to run
            pass
        elif self.currExeCmd.cmd.isDone:
            # begin the next command on the queue
            self.currExeCmd = self.cmdQueue.pop(0)
            self.currExeCmd.cmd.setState(self.currExeCmd.cmd.Running)
            self.currExeCmd.callFunc()
        elif self.currExeCmd.cmd.state == self.currExeCmd.cmd.Cancelling:
            # leave it alone
            pass
        elif self.cmdQueue[0] > self.currExeCmd:
            # command at top of queue beats the currently executing one.
            self.killFunc(self.currExeCmd.cmd)
        elif self.currExeCmd.cmd.cmdVerb in self.cmdQueue[0].collideDict.keys():
            # a rule exists for this collision, check if it's a kill order
            if self.cmdQueue[0].collideDict[self.currExeCmd.cmd.cmdVerb] == self.cmdQueue[0].KillOther:
                self.killFunc(self.currExeCmd.cmd)
            elif self.cmdQueue[0].collideDict[self.currExeCmd.cmd.cmdVerb] == self.cmdQueue[0].CancelMe:
                self.cmdQueue[0].cmd.setState(
                    self.cmdQueue[0].cmd.Cancelled, 
                    '%s cancelled by currently executing command: %s' \
                        % (self.cmdQueue[0].cmd.cmdVerb, self.currExeCmd.cmc.cmbVerb)
                )
        else:
            # command is currently active and should remain that way
            pass 
        
        