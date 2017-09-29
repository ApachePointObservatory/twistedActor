
"""!Code to run scripts that can wait for various things without messing up the main event loop
(and thus starving the rest of your program).

ScriptRunner allows your script to wait for the following:
- wait for a given time interval using: yield waitMS(...)
- run a slow computation as a background thread using waitThread
- run a command via the keyword dispatcher using waitCmd
- run multiple commands at the same time:
  - start each command with startCmd,
  - wait for one or more commands to finish using waitCmdVars
- wait for a keyword variable to be set using waitKeyVar
- wait for a sub-script by yielding it (i.e. yield subscript(...));
  the sub-script must contain a yield for this to work; if it has no yield then just call it directly

An example is given as the test code at the end.

History:
2014-06-27 ROwen
"""
from opscore.utility.timer import Timer
from opscore.actor import keyvar
from opscore.actor import BaseScriptRunner, ScriptError

__all__ = ["ScriptError", "ScriptRunner"]

class ScriptRunner(BaseScriptRunner):
    """!Execute a script.

    Allows waiting for various things without messing up the main event loop.
    """
    def __init__(self,
        name,
        runFunc = None,
        scriptClass = None,
        dispatcher = None,
        initFunc = None,
        endFunc = None,
        stateFunc = None,
        startNow = False,
        debug = False,
    ):
        """!Create a ScriptRunner
        
        Inputs:
        - name          script name; used to report status
        - runFunc       the main script function; executed whenever
                        the start button is pressed
        - scriptClass   a class with a run method and an optional end method;
                        if specified, runFunc, initFunc and endFunc may not be specified.
        - dispatcher    actor keyword dispatcher (opscore.actor.ActorDispatcher);
                        required to use wait methods and startCmd.
        - initFunc      function to call ONCE when the ScriptRunner is constructed
        - endFunc       function to call when runFunc ends for any reason
                        (finishes, fails or is cancelled); used for cleanup
        - stateFunc     function to call when the ScriptRunner changes state
        - startNow      if True, starts executing the script immediately
                        instead of waiting for user to call start.
        - debug         if True, startCmd and wait... print diagnostic messages to stdout
                        and there is no waiting for commands or keyword variables. Thus:
                        - waitCmd and waitCmdVars return success immediately
                        - waitKeyVar returns defVal (or None if not specified) immediately
    
        All functions (runFunc, initFunc, endFunc and stateFunc) receive one argument: sr,
        this ScriptRunner object. The functions can pass information using sr.globals,
        an initially empty object (to which you can add instance variables and set or read them).
        
        Only runFunc is allowed to call sr methods that wait.
        The other functions may only run non-waiting code.
    
        WARNING: when runFunc calls any of the ScriptRunner methods that wait,
        IT MUST YIELD THE RESULT, as in:
            def runFunc(sr):
                ...
                yield sr.waitMS(500)
                ...
        All such methods are marked "yield required".
        
        If you forget to yield, your script will not wait. Your script will then halt
        with an error message when it calls the next ScriptRunner method that involves waiting
        (but by the time it gets that far it may have done some strange things).
        
        If your script yields when it should not, it will simply halt.
        """
        self._actor = dispatcher.name
        BaseScriptRunner.__init__(self,
            name = name,
            runFunc = runFunc,
            scriptClass = scriptClass,
            dispatcher = dispatcher,
            initFunc = initFunc,
            endFunc = endFunc,
            stateFunc = stateFunc,
            startNow = startNow,
            debug = False,
        )

    def startCmd(self,
        cmdStr = "",
        timeLim = 0,
        callFunc = None,
        callCodes = keyvar.DoneCodes,
        timeLimKeyVar = None,
        timeLimKeyInd = 0,
        abortCmdStr = None,
        keyVars = None,
        checkFail = True,
    ):
        """!Start a command using the same arguments as waitCmd.
        
        Inputs: same as waitCmd, which see.

        Returns a command variable that you can wait for using waitCmdVars.

        Do not use yield because it does not wait for anything.
        """
        cmdVar = keyvar.CmdVar(
            actor = self._actor,
            cmdStr = cmdStr,
            timeLim = timeLim,
            callFunc = callFunc,
            callCodes = callCodes,
            timeLimKeyVar = timeLimKeyVar,
            timeLimKeyInd = timeLimKeyInd,
            abortCmdStr = abortCmdStr,
            keyVars = keyVars,
        )

        if checkFail:
            cmdVar.addCallback(
                callFunc = self._cmdFailCallback,
                callCodes = keyvar.FailedCodes,
            )
        if self.debug:
            argList = ["cmdStr=%r" % (cmdStr,)]
            if timeLim != 0:
                argList.append("timeLim=%s" % (timeLim,))
            if callFunc != None:
                argList.append("callFunc=%r" % (callFunc,))
            if callCodes != keyvar.DoneCodes:
                argList.append("callCodes=%r" % (callCodes,))
            if timeLimKeyVar != None:
                argList.append("timeLimKeyVar=%r" % (timeLimKeyVar,))
            if abortCmdStr != None:
                argList.append("abortCmdStr=%r" % (abortCmdStr,))
            if checkFail != True:
                argList.append("checkFail=%r" % (checkFail,))
            self.debugPrint("startCmd(%s)" % ", ".join(argList))

            self._showCmdMsg("%s started" % cmdStr)
            

            # set up command completion callback
            def endCmd(self=self, cmdVar=cmdVar):
                endReply = self.dispatcher.makeReply(
                    cmdr = None,
                    cmdID = cmdVar.cmdID,
                    actor = cmdVar.actor,
                    msgCode = ":",
                )
                cmdVar.handleReply(endReply)
                self._showCmdMsg("%s finished" % cmdVar.cmdStr)
            Timer(1.0, endCmd)

        else:
            self.dispatcher.executeCmd(cmdVar)
                
        return cmdVar
    
    def waitCmd(self,
        cmdStr = "",
        timeLim = 0,
        callFunc=None,
        callCodes = keyvar.DoneCodes,
        timeLimKeyVar = None,
        timeLimKeyInd = 0,
        abortCmdStr = None,
        keyVars = None,
        checkFail = True,
    ):
        """!Start a command and wait for it to finish.
        Returns the command variable (an opscore.actor.CmdVar) in sr.value.

        A yield is required.
        
        Inputs:
        - cmdStr: the command (without a terminating \n)
        - timeLim: maximum time before command expires, in sec; 0 for no limit
        - callFunc: a function to call when the command changes state;
            see below for details.
        - callCodes: the message types for which to call the callback;
            a string of one or more choices; see keyvar.MsgCodeSeverity for the choices;
            useful constants include DoneTypes (command finished or failed)
            and AllTypes (all message types, thus any reply).
            Not case sensitive (the string you supply will be lowercased).
        - timeLimKeyVar: a keyword (opscore.actor.KeyVar) whose value at index timeLimKeyInd
            is used as a time within which the command must finish (in seconds).
        - timeLimKeyInd: see timeLimKeyVar; ignored if timeLimKeyVar omitted.
        - abortCmdStr: a command string that will abort the command. This string is sent to the actor
            if the command is aborted, e.g. if the script is cancelled while the command is executing.
        - keyVars: a sequence of 0 or more keyword variables (opscore.actor.KeyVar) to monitor.
            Any data for those variables that arrives IN RESPONSE TO THIS COMMAND is saved in the cmdVar
            returned in sr.value and can be retrieved using cmdVar.getKeyVarData or cmdVar.getLastKeyVarData
        - checkFail: check for command failure?
            if True (the default) command failure will halt your script

        The callback receives one argument: the command variable (an opscore.actor.CmdVar).
        
        Note: timeLim and timeLimKeyVar work together as follows:
        - The initial time limit for the command is timeLim
        - If timeLimKeyVar is seen before timeLim seconds have passed
          then self.maxEndTime is updated with the new value
          
        Also the time limit is a lower limit. The command is guaranteed to
        expire no sooner than this but it may take a second longer.
        """
        self._waitCheck(setWait = False)
        
        self.debugPrint("waitCmd calling startCmd")

        cmdVar = self.startCmd (
            cmdStr = cmdStr,
            timeLim = timeLim,
            callFunc = callFunc,
            callCodes = callCodes,
            timeLimKeyVar = timeLimKeyVar,
            timeLimKeyInd = timeLimKeyInd,
            abortCmdStr = abortCmdStr,
            keyVars = keyVars,
            checkFail = False,
        )
        
        self.waitCmdVars(cmdVar, checkFail=checkFail, retVal=cmdVar)
