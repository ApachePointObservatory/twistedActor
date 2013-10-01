import collections
import itertools
import sys
import traceback

from RO.Comm.TwistedTimer import Timer
from RO.SeqUtil import isSequence
from RO.AddCallback import safeCall
from RO.StringUtil import quoteStr
from twistedActor import UserCmd

__all__ = ["DeviceSet"]

DefaultTimeLim = 5

class DevCmdInfo(object):
    """Information about a device command

    Intended to be passed to callback functions for DeviceSet commands
    """
    def __init__(self, slot, dev, devCmd, userCmd):
        self.slot = slot
        self.dev = dev
        self.devCmd = devCmd
        self.userCmd = userCmd

class DeviceSet(object):
    """A collection of related devices (e.g. axes or mirrors), some of which may not exist

    Note that a DeviceSet has a list of slot names that is independent of
    the actual devices. This is because a particular device may not exist
    (but its slot should still have a slot), or multiple devices may exist
    that can be swapped out in one slot. For example: suppose a telescope has
    multiple instrument rotator and one can be in use at a particular time (perhaps none).
    In that case the axis DeviceSet's slot names might be ("az", "alt", "rot"),
    while the rotator device in the set might be None or might have a slot such as "rot1" or "rot2".
    """
    def __init__(self, actor, slotList, devList):
        """Construct a DeviceSet

        @param[in] actor: actor (instance of twistedActor.BaseActor);
            used for writeToUsers in this class, and subclasses may make additonal use of it
        @param[in] slotList: slot of each device slot (even if device does not exist)
        @param[in] devList: sequence of devices;
            each device is either an instances of twistedActor.Device or is None if the device is unavailable

        @raise RuntimeError if:
        - len(devList) != len(slotList)
        - names in slotList are not unique
        """
        if len(slotList) != len(devList):
            raise RuntimeError("devList=%s and slotList=%s are not the same length" % \
                (devList, slotList))
        
        self.actor = actor
        # dict of slot name: index
        self._slotIndexDict = dict((slot, i) for i, slot in enumerate(slotList))
        # ordered dict of slot name: device
        self._slotDevDict = collections.OrderedDict((slot, dev) for slot, dev in itertools.izip(slotList, devList))
        # dict of dev.name: slot name
        self._devNameSlotDict = dict((dev.name, slot) for (slot, dev) in self._slotDevDict.iteritems() if dev)

        if len(self._slotDevDict) < len(slotList):
            raise RuntimeError("Names in slotList=%s are not unique" % (slotList,))

        for dev in self.devList:
            if dev:
                self._addDevCallbacks(dev)

    def checkSlotList(self, slotList):
        """Raise RuntimeError if any slots in slotList do not contain a device
        """
        try:
            emptySlotList = [slot for slot in slotList if not self[slot]]
        except KeyError:
            invalidSlotList = [slot for slot in slotList if not slot in self._slotDevDict]
            raise RuntimeError("One or more slots is unknown: %s" % (", ".join(invalidSlotList),))

        if emptySlotList:
            raise RuntimeError("One or more slots is empty: %s" % (", ".join(emptySlotList),))

    def connect(self, slotList=None, userCmd=None, timeLim=DefaultTimeLim):
        """Connect devices specified by slot name

        @param[in] doConnect: if True, connect the specified devices, else disconnect them
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] userCmd: user command whose set state is set to Done or Failed when the command is done

        @return userCmd: the specified userCmd or a newly generated one

        @raise RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        cd = ConnectDevices(devSet=self, slotList=slotList, doConnect=True, userCmd=userCmd, timeLim=timeLim)
        return cd.userCmd

    def disconnect(self, slotList=None, userCmd=None, timeLim=DefaultTimeLim):
        """Connect devices specified by slot name

        @param[in] doConnect: if True, connect the specified devices, else disconnect them
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] userCmd: user command whose set state is set to Done or Failed when the command is done

        @return userCmd: the specified userCmd or a newly generated one

        @raise RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        cd = ConnectDevices(devSet=self, slotList=slotList, doConnect=False, userCmd=userCmd, timeLim=timeLim)
        return cd.userCmd

    def expandSlotList(self, slotList):
        """Expand a collection of slot names, changing None to the correct list and checking the list

        @param[in] slotList: collection of slot names, or None for all filled slots

        @raise RuntimeError if slotList contains an unknown or empty slot name
        """
        if slotList is None:
            return self.filledSlotList

        self.checkSlotList(slotList)
        return slotList

    @property
    def devExists(self):
        """Return a list of bools, one per device: True if device exists
        """
        return [dev is not None for dev in self._slotDevDict.itervalues()]

    @property
    def devList(self):
        """Return the list of devices
        """
        return self._slotDevDict.values()

    @property
    def slotList(self):
        """Return the list of slot names
        """
        return self._slotDevDict.keys()

    @property
    def filledSlotList(self):
        """Return the list of names of filled slots
        """
        return [slot for slot, dev in self._slotDevDict.iteritems() if dev]

    def getIndex(self, slot):
        """Get the index of the slot

        @raise KeyError if slot does not exist
        """
        return self._slotIndexDict[slot]

    def slotFromDevName(self, devName):
        """Get the slot name from the device name
        """
        return self._devNameSlotDict[devName]

    def replaceDev(self, slot, dev, userCmd=None):
        """Replace or remove one device

        The old device (if it exists) is closed by calling init()

        @param[in] slot: slot slot of device (must match a slot in slotList)
        @param[in] dev: the new device, or None to remove the existing device

        @return userCmd: the supplied userCmd or a newly created UserCmd

        @raise RuntimeError if slot is not in slotList
        """
        if slot not in self._slotDevDict:
            raise RuntimeError("Invalid slot %s" % (slot,))
        oldDev = self._slotDevDict[slot]
        if oldDev:
            self._removeDevCallbacks(oldDev)
            oldDev.init()
        self._slotDevDict[slot] = dev
        self._devNameDict[dev.name] = slot
        self._addDevCallbacks(dev)
        return dev.connect(userCmd=userCmd)

    def startCmd(self, cmdStrOrList, slotList=None, callFunc=None, userCmd=None, timeLim=DefaultTimeLim):
        """Start a command or list of commands on one or more devices

        The same command or list of commands is sent to each device;
        use startCmdDict to send different commands to different devices.

        @param[in] cmdStrOrList: command to send
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            See the description in startCmdList for details.
        @param[in] userCmd: user command whose set state is set to Done or Failed when all device commands are done;
            if None a new UserCmd is created and returned
        @return userCmd: the supplied userCmd or a newly created UserCmd
        @param[in] timeLim: time limit for command; if None then the time limit in userCmd is used
            (if any) else there is no time limit

        @raise RuntimeError if:
        - slotList has empty or non-existent slots
        - userCmd is already done
        """
        if slotList is None: # don't call expandSlotList because startCmdDict checks the slot names
            slotList = self.filledSlotList
        cmdDict = collections.OrderedDict((slot, cmdStrOrList) for slot in slotList)
        return self.startCmdDict(cmdDict=cmdDict, callFunc=callFunc, userCmd=userCmd)

    def startCmdDict(self, cmdDict, callFunc=None, userCmd=None, timeLim=DefaultTimeLim):
        """Start a dictionary of commands on one or more devices

        @param[in] cmdDict: a dict of slot: command string or sequence of command strings
            if the slot is empty or unknown then an exception is raised
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
            The function may return a new devCmd, in which case the completion of the full set of commands
            is delayed until the new command is finished; one use case is to initialize an actuator if a move fails.
        @param[in] userCmd: user command whose set state is set to Done or Failed when all device commands are done;
            if None a new UserCmd is created and returned
        @param[in] timeLim: time limit for command; or None if no limit
        @return userCmd: the supplied userCmd or a newly created UserCmd

        @raise RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        rcd = RunCmdDict(devSet=self, cmdDict=cmdDict, callFunc=callFunc, userCmd=userCmd, timeLim=timeLim)
        return rcd.userCmd

    def _addDevCallbacks(self, dev):
        """Add device-specific callbacks

        Called when adding a device
        """
        pass

    def _removeDevCallbacks(self, dev):
        """Remove device-specific callbacks

        Called when removing a device
        """
        pass

    def __getitem__(self, slot):
        """Return the device in the specified slot
        """
        return self._slotDevDict[slot]

    def __len__(self):
        """Return number of slots"""
        return len(self._slotDevDict)


class ConnectDevices(object):
    """Connect or disconnect one or more devices
    """
    def __init__(self, devSet, slotList, doConnect, userCmd, timeLim):
        """Start connecting or disconnecting one or more devices
        """
        self.devSet = devSet
        self.doConnect = bool(doConnect)
        self.timeLim = timeLim

        slotList = devSet.expandSlotList(slotList)
        if not slotList:
            if self.userCmd:
                self.userCmd.setState(self.userCmd.Done, textMsg="No slots specified; nothing done")

        if userCmd is None:
            userCmd = UserCmd()
        elif userCmd.isDone:
            raise RuntimeError("userCmd=%s already finished" % (userCmd,))
        self.userCmd = userCmd

        self.devList = []
        self.connDevDict = dict()
        self.connTimer = Timer()

        if self.timeLim:
            self.connTimer.start(self.timeLim, self.finish)
        for slot in slotList:
            dev = devSet[slot]
            self.devList.append(dev)
            self.connDevDict[id(dev.conn)] = dev
            dev.conn.addStateCallback(self.connCallback)
            if self.doConnect:
                dev.conn.connect()
            else:
                safeCall(dev.init)
                dev.conn.disconnect()
        self.connCallback()

    def connCallback(self, conn=None):
        """Callback for dev.conn and for initial check if all done
        """
        if conn and conn.isConnected:
            dev = self.connDevDict[id(conn)]
            safeCall(dev.init)
        if all(dev.conn.isDone for dev in self.devList):
            # all connections finished
            self.finish()

    def finish(self):
        """Call to finish command -- for success or failure
        """
        self.connTimer.cancel()
        for dev in self.devList:
            dev.conn.removeStateCallback(self.connCallback)
        if not self.userCmd.isDone:
            if self.doConnect:
                failDevList = [dev.name for dev in self.devList if not dev.conn.isConnected]
                opStr = "connect"
            else:
                failDevList = [dev.name for dev in self.devList if dev.conn.isConnected]
                opStr = "disconnect"

            if failDevList:
                self.userCmd.setState(self.userCmd.Failed,
                    textMsg="One or more devices failed to %s: %s" % (opStr, ", ".join(failDevList)))
            else:
                self.userCmd.setState(self.userCmd.Done)


class RunCmdDict(object):
    """Run a dictionary of commands
    """
    def __init__(self, devSet, callFunc, cmdDict, userCmd, timeLim):
        """Start running a command dict

        @param[in] devSet: device set
        @param[in] cmdDict: a dict of slot name: command string or sequence of command strings
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
            The function may return a new devCmd, in which case the completion of the full set of commands
            is delayed until the new command is finished; one use case is to initialize an actuator if a move fails.
        @param[in] userCmd: user command to track progress of this command
        @param[in] timeLim: time limit for command; or None if no limit
        """
        devSet.checkSlotList(cmdDict.keys())
        if userCmd is None:
            userCmd = UserCmd()
        elif userCmd.isDone:
            raise RuntimeError("userCmd=%s already finished" % (userCmd,))
        self.userCmd = userCmd
        
        self.devCmdDict = dict()
        self.failSlotSet = set()

        for slot, cmdStrOrList in cmdDict.iteritems():
            dev = devSet[slot]

            def devCmdCallback(devCmd, slot=slot, dev=dev):
                if devCmd.didFail:
                    self.failSlotSet.add(slot)
                
                self.devCmdDict[slot] = devCmd

                if callFunc:
                    try:
                        newDevCmd = callFunc(DevCmdInfo(slot=slot, dev=dev, devCmd=devCmd, userCmd=self.userCmd))
                        if newDevCmd:
                            # the callback function started a new command;
                            # update self.devCmdDict and checkDone when it is done, but do NOT run callFunc again
                            self.devCmdDict[slot] = newDevCmd
                            def newDevCmdCallback(devCmd, slot=slot, dev=dev):
                                self.devCmdDict[slot] = devCmd
                                self.checkDone()

                            newDevCmd.addCallback(newDevCmdCallback)
                            self.devCmdDict[slot] = newDevCmd
                    except Exception:
                        self.failSlotSet.add(slot)
                        textBody = "%s command %r failed" % (slot, devCmd.cmdStr)
                        msgStr = "Text=%s" % (quoteStr(textBody),)
                        self.actor.writeToUsers("f", msgStr=msgStr)
                        traceback.print_exc(file=sys.stderr)

                self.checkDone()

            if not isSequence(cmdStrOrList):
                devCmd = dev.startCmd(cmdStrOrList, timeLim=timeLim)
            else:
                devCmd = dev.startCmdList(cmdStrOrList, timeLim=timeLim)
            self.devCmdDict[slot] = devCmd
            devCmd.addCallback(devCmdCallback)

        self.checkDone()

    def checkDone(self, dumArg=None):
        """If all device commands are finished, then set self.userCmd state to Failed or Done as appropriate
        """
        for slot, devCmd in self.devCmdDict.iteritems():
            if not devCmd.isDone:
                return
            if devCmd.didFail:
                self.failSlotSet.add(slot)

        if not self.userCmd.isDone:
            if self.failSlotSet:
                failedAxisStr = ", ".join(slot for slot in self.failSlotSet)
                self.userCmd.setState(self.userCmd.Failed, textMsg="Command failed for %s" % (failedAxisStr,))
            else:
                self.userCmd.setState(self.userCmd.Done)
