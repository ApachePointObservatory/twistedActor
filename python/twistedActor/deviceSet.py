import collections
import itertools
import sys
import traceback

from RO.StringUtil import quoteStr
from twistedActor import UserCmd

__all__ = ["DeviceSet"]

class DevCmdInfo(object):
    """Information about a device command

    Intended to be passed to callback functions for DeviceSet commands
    """
    def __init__(self, name, dev, devCmd, userCmd):
        self.name = name
        self.dev = dev
        self.devCmd = devCmd
        self.userCmd = userCmd

class DeviceSet(object):
    """A collection of related devices (e.g. axes or mirrors), some of which may not exist

    Note that a DeviceSet has a list of device names that is independent of
    the actual devices. This is because a particular device may not exist
    (but its slot should still have a name), or multiple devices may exist
    that can be swapped out in one slot. For example: suppose a telescope has
    multiple instrument rotator and one can be in use at a particular time (perhaps none).
    In that case the axis DeviceSet's names might be ("az", "alt", "rot"),
    while the rotator device in the set might be None or might have a name such as "rot1" or "rot2".
    """
    def __init__(self, actor, nameList, devList):
        """Construct a DeviceSet

        @param[in] actor: actor (instance of twistedActor.BaseActor);
            used for writeToUsers in this class, and subclasses may make additonal use of it
        @param[in] nameList: name of each device slot (even if device does not exist)
        @param[in] devList: sequence of devices;
            each device is either an instances of twistedActor.Device or is None if the device is unavailable

        @raise RuntimeError if:
        - len(devList) != len(nameList)
        - names in nameList are not unique
        """
        if len(nameList) != len(devList):
            raise RuntimeError("devList and nameList must have the same length")
        
        self.actor = actor
        # dict of device name (from nameList): device
        self._devDict = collections.OrderedDict((name, dev) for name, dev in itertools.izip(nameList, devList))
        self._nameIndexDict = dict((name, i) for i, name in enumerate(nameList))

        if len(self._devDict) < len(nameList):
            raise RuntimeError("Names in nameList=%s not unique" % (nameList,))

    def expandDoDev(self, doDev):
        """Expand doDev, changing None to the correct list.

        @param[in] doDev: which devices to command: a sequence of bools (one per device) or None for all existing devices;
            raise RuntimeError if doDev True for a non-existent device

        Raise RuntimeError if doDev is the wrong length or is true for nonexistent device
        """
        if doDev == None:
            return self.devExists

        if len(doDev) != len(self._devDict):
            raise RuntimeError("doDev=%s; need %s values" % (doDev, len(self._devDict)))
        for dd, (name, dev) in itertools.izip(doDev, self._devDict.iteritems()):
            if dd and (dev is None):
                raise RuntimeError("doDev true for nonexistent device %s" % (name,))
        return doDev

    @property
    def devExists(self):
        """Return a list of bools, one per device: True if device exists
        """
        return [dev is not None for dev in self._devDict.itervalues()]

    @property
    def devList(self):
        """Return the list of devices
        """
        return self._devDict.values()

    def __getitem__(self, name):
        """Return the named axis
        """
        return self._devDict[name]

    @property
    def nameList(self):
        """Return the list of names
        """
        return self._devDict.keys()

    def getIndex(self, name):
        """Get the index of the device, given its name

        @raise KeyError if name does not exist
        """
        return self._nameIndexDict[name]

    def replaceDev(self, name, dev):
        """Replace one device

        @param[in] name: name of device (must match a name in nameList)
        @param[in] dev: the new device, or None if device does not exist

        @raise RuntimeError if name is not in nameList
        """
        if name not in self._devDict:
            raise RuntimeError("Invalid name %s" % (name,))
        self._devDict[name] = dev

    def startCmd(self, cmdStr, doDev=None, userCmd=None, callFunc=None):
        """Start a command in one or more devices

        @param[in] cmdStr: command to send
        @param[in] doDev: which devices to command: a sequence of bools (one per device) or None for all existing devices;
            raise RuntimeError if doDev True for a non-existent device
        @param[in] userCmd: user command whose set state is set to Done or Failed when all device commands are done;
            if None a new UserCmd is created and returned
        @param[in] callFunc: callback function when a device command is done, or None;
            see the description in startCmdList for details.
        @return userCmd: the supplied userCmd or a newly created UserCmd

        @raise RuntimeError if:
        - doDev does not have one element per device
        - doDev True for a non-existent device
        """
        doDev = self.expandDoDev(doDev)
        
        cmdList = [cmdStr if dd else None for dd in doDev]
        return self.startCmdList(cmdList=cmdList, userCmd=userCmd, callFunc=callFunc)

    def startCmdList(self, cmdList, userCmd=None, callFunc=None):
        """Start a list of commands, one per device

        @param[in] cmdList: a list of commands; one per device;
            if an entry is None or "" then the associated device is not commanded
            if the device does not exists then an exception is raised
        @param[in] userCmd: user command whose set state is set to Done or Failed when all device commands are done;
            if None a new UserCmd is created and returned
        @param[in] callFunc: callback function to call when a device command is done, or None;
            if supplied, the function receives one positional argument: a DevCmdInfo.
            The function may return a new devCmd, in which case the completion of the command
            is changed to depend on the new command instead of the supplied devCmd;
            this can be used to chain commands, e.g. to initialize an actuator if a move fails.
            If this function raises an exception then the returned command fails
        @return userCmd: the supplied userCmd or a newly created UserCmd
        
        @raise RuntimeError if
        - the wrong number of commands is specified
        - a command is specified for a non-existent device
        """
        if len(cmdList) != len(self._devDict):
            raise RuntimeError("Got %s commands but expected %s" % (len(cmdList), len(self._devDict)))

        if userCmd is None:
            userCmd = UserCmd()
        elif userCmd.isDone:
            print "Warning: %s.startOneCmd: userCmd %s is done; creating a new one" % (type(self).__name__, userCmd)
            userCmd = UserCmd()

        devCmdDict = dict()
        failNameSet = set()

        def checkDone(dumArg=None):
            """If all device commands are finished, then set userCmd to Failed or Done as appropriate
            """
            for name, devCmd in devCmdDict.iteritems():
                if not devCmd.isDone:
                    return
                if devCmd.didFail:
                    failNameSet.add(name)
            
            # all device commands are done
            if failNameSet:
                failedAxisStr = ", ".join(name for name in failNameSet)
                userCmd.setState(userCmd.Failed, textMsg="Command failed for %s" % (failedAxisStr,))
            else:
                userCmd.setState(userCmd.Done)        
       
        for i, (name, dev) in enumerate(self._devDict.iteritems()):
            if cmdList[i]:
                if dev is None:
                    raise RuntimeError("device %s does not exist" % (i,))

                def devCmdCallback(devCmd, name=name, dev=dev):
                    if not devCmd.isDone:
                        return

                    if devCmd.didFail:
                        failNameSet.add(name)
                    
                    if callFunc:
                        try:
                            newDevCmd = callFunc(DevCmdInfo(name=name, dev=dev, devCmd=devCmd, userCmd=userCmd))
                            # the callFunc will have registered any interesting callbacks it needs;
                            # all this code has to do is check for completion
                            if newDevCmd:
                                newDevCmd.addCallback(checkDone)
                                devCmdDict[name] = newDevCmd
                        except Exception:
                            failNameSet.add(name)
                            textBody = "%s command %r failed" % (name, devCmd.cmdStr)
                            msgStr = "Text=%s" % (quoteStr(textBody),)
                            self.actor.writeToUsers("f", msgStr=msgStr)
                            traceback.print_exc(file=sys.stderr)

                    checkDone()

                devCmd = dev.startCmd(cmdList[i])
                devCmdDict[dev.name] = devCmd
                devCmd.addCallback(devCmdCallback)

        checkDone()
        return userCmd
