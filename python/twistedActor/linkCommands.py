

__all__ = ["LinkCommands"]

class LinkCommands(object):
    """!Link commands such that completion of the main command depends on one or more sub-commands

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
        """!Link a main command to a collection of sub-commands

        @param[in] mainCmd  the main command, a BaseCmd
        @param[in] subCmdList  a collection of sub-commands, each a BaseCmd
        """
        if hasattr(mainCmd, 'isLinked'):
            raise RuntimeError("Cannont link main command %s, it is already linked elsewhere!"%str(mainCmd))
        self.mainCmd = mainCmd
        self.mainCmd.isLinked = True
        self.subCmdList = subCmdList
        for subCmd in self.subCmdList:
            # give each sub command a copy of the 'mainCommand'
            # mostly for writing responses to it
            subCmd.mainCmd = mainCmd
            if not subCmd.isDone:
                subCmd.addCallback(self.subCmdCallback)

        # call right away in case all sub-commands are already done
        self.subCmdCallback()

    def subCmdCallback(self, dumCmd=None):
        """!Callback to be added to each device cmd

        @param[in] dumCmd  sub-command issuing the callback (ignored)
        """
        if not all(subCmd.isDone for subCmd in self.subCmdList):
            # not all device commands have terminated so keep waiting
            return

        failedCmdSummary = "; ".join("%s: %s" % (subCmd.cmdStr, subCmd.getMsg()) for subCmd in self.subCmdList if subCmd.didFail)
        if failedCmdSummary:
            # at least one device command failed, fail the user command and say why
            # note, do we want to match the type of failure? If a subcommand was cancelled
            # should the mainCmd state be cancelled too?
            state = self.mainCmd.Failed
            textMsg = "Sub-command(s) failed: %s" % (failedCmdSummary,)
        else:
            # all device commands terminated successfully
            # set user command to done
            state = self.mainCmd.Done
            textMsg = ""
        self.mainCmd.setState(state, textMsg = textMsg)
