"""Contains objects for managing multiple commands at once.
"""
from collections import deque

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
    def __init__(self, cmdVerb, rejectMeBehind, cancelQueued, cancelRunning):
        """ An object for defining collision rules. Default behavior is to queue
        
            @param[in] cmdVerb: a command verb string
            @param[in] rejectMeBehind: a set of command names behind which 
                this command should be rejected. 
            @param[in] cancelQueued: a set of command names to automatically
                cancel if they are queued infront of this command
            @param[in] cancelRunning: a set of command names to automatically cancel if
                running during the reception of this command on the stack. If a command in 
                cancelRunning is not present in cancelQueued, it is added to cancelQueued
        """
        for cmd in cancelRunning:
            if not (cmd in cancelQueued):
                cancelQueued += (cmd,) 
            
        self.cmdVerb = cmdVerb   
        self.rejectMeBehind = tuple(rejectMeBehind)
        self.cancelQueued = tuple(cancelQueued)
        self.cancelRunning = tuple(cancelRunning)
        
class CommandQueue(object):
    """This is an object which keeps track of commands and smartly handles 
    command collisions based on rules chosen by you.
    
    Intended use:
    After construction, define collision rules via addRule().  Commands are compared 
    using their cmdVerb attribue.  If a command is running on the queue, and a higher
    priority command arrives and wants to cancel the current command, it's state is set
    to: CANCELLING. IT IS UP FOR THE EXTERNAL CODE TO FULLY CANCEL THE COMMAND.
    The callFunc associated with every command added to the queue received a copy
    of the command, so the outside code should be monitoring for a cancelling state to
    to any special cleanup before fully canceling the command.
    """
    # queue rules
    def __init__(self):
        self.cmdQueue = []
        self.ruleDict = {}
 
    def __getitem__(self, ind):
        return self.cmdQueue[ind]

    def __len__(self):
        return len(self.cmdQueue)
        
    def addRule(self, cmdVerb, rejectMeBehind=(), cancelQueued=(), cancelRunning=()):
        """ Add a rule. See CommandRule Docs.
        """ 
        self.ruleDict[cmdVerb] = CommandRule(cmdVerb, rejectMeBehind, cancelQueued, cancelRunning)
        
    def addCmd(self, cmd, callFunc, *args):
        """ @param[in] cmd: a twistedActor BaseCmd, but must have a cmdVerb attribute!!!!
            @param[in] callFunc: function to call when cmd is exectued, receives *args, and the keywordArg userCmd=cmd
            @param[in] *args, any additional arguments to be passed to callFunc
            
            A command is added to the stack.  A new attribute is appended to the command:
            cmd.exe, this is the callable that will be run when this command is to be run.
            callFunc must at least a userCmd argument
        """
        if not hasattr(cmd, 'cmdVerb'):
            raise RuntimeError('command on a CommandQueue must have a cmdVerb attribute')
        
        # compare cmd with current commands on the queue
        for cmdOnStack, foo in self.cmdQueue[:]:
            # copy self.cmdQueue because collideCmds may be cancelling
            # commands in self.cmdQueue and such commands have a callback registered
            # to remove themselves from the queue when they are done!
            self.collideCmds(cmd, cmdOnStack)
            if cmd.isDone:
                # incoming command was rejected
                return 
        
        def removeWhenDone(cbCmd):
            """add this callback to the command so it will automatically remove
            itself from the list when it had been set to done.
            """
            if not cbCmd.isDone:
                return
            # command is done, find it in the queue and pop it.
            for ind in range(len(self.cmdQueue)):
                qCmd, foo = self.cmdQueue[ind]
                if (qCmd.userID==cbCmd.userID) and (qCmd.cmdID==cbCmd.cmdID):
                    #delattr(qCmd, 'exe') # delete the callable attribute
                    del self.cmdQueue[ind] # remove the command from the queue, it's done
                    self.runQueue() # run the queue (if another command is waiting, get it going)
                    return
        cmd.addCallback(removeWhenDone)
        self.cmdQueue.append((cmd, lambda: callFunc(*args, userCmd=cmd)))
        self.runQueue()

    def collideCmds(self, incommingCmd, cmdOnStack):
        """set the state (or not) of incommingCmd and/or cmdOnStack based on previously defined
        rules.
        """
        if cmdOnStack.state == cmdOnStack.Cancelling:
            # command is in the process of being cancelled, treat as if it is not present
            return
        # find rule for incommingCmd
        try:
            rule = self.ruleDict[incommingCmd.cmdVerb]
        except KeyError:
            # no rules have been added pertaining to this command, do nothing.
            # it will remain queued
            return
        # first check if cmdOnStack is currently running.
        if (cmdOnStack.state == cmdOnStack.Running) and (cmdOnStack.cmdVerb in rule.cancelRunning):
            # this command is running and it should be cancelled, set 
            # the state to cancelling and let outside code (which should be listening
            # for cancelling state) handle any needed cleanup before fully cancelling.
            cmdOnStack.setState(cmdOnStack.Cancelling)
        elif cmdOnStack.cmdVerb in rule.cancelQueued:
            assert cmdOnStack.state == cmdOnStack.Ready
            # command is not running, so it must be queued and ready
            cmdOnStack.setState(
                cmdOnStack.Cancelled, 
                'Queued Command: %s cancelled by higher priority command: %s' % \
                (cmdOnStack.cmdVerb, incommingCmd.cmdVerb)
            )
        elif cmdOnStack.cmdVerb in rule.rejectMeBehind:
            # automatically reject the incommingCmd
            incommingCmd.setState(
                incommingCmd.Cancelled,
                'Command %s may not be queued behind command: s' %\
                (incommingCmd.cmdVerb, cmdOnStack.cmdVerb)
            )
        else:
            # do nothing, leave the incommingCmd on the queue.
            pass
    
    def runQueue(self):
        """Go through the queue, start any ready commands, handle collisions, etc
        
        This is executed when a new command is added to the queue, and anytime
        a old command pops off the queue.
        """
        if len(self.cmdQueue) == 0:
            # no commands on queue, nothing happening.
            return
        oldestCmd, exe = self.cmdQueue[0]
        if oldestCmd.state == oldestCmd.Ready:
            # start it running
            oldestCmd.setState(oldestCmd.Running)
            exe()