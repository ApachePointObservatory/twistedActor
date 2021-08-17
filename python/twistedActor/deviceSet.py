

from collections import OrderedDict
import itertools

from opscore.RO.SeqUtil import asSequence

from .device import expandUserCmd
from .linkCommands import LinkCommands

__all__ = ["DeviceSet"]

class DevCmdInfo(object):
    """!Information about a device command

    Intended to be passed to callback functions for DeviceSet commands
    """
    def __init__(self, slot, dev, devCmd, userCmd):
        self.slot = slot
        self.dev = dev
        self.devCmd = devCmd
        self.userCmd = userCmd

    def __str__(self):
        return "%s(slot=%s, devCmd=%s)" % \
            (type(self).__name__, self.slot, self.devCmd)

    def __repr__(self):
        return "%s(slot=%s, dev=%s, devCmd=%r, userCmd=%r)" % \
            (type(self).__name__, self.slot, self.dev, self.devCmd, self.userCmd)


class DeviceSet(object):
    """!A collection of related devices (e.g. axes or mirrors), some of which may not exist

    Note that a DeviceSet has a list of slot names that is independent of
    the actual devices. This is because a particular device may not exist
    (but its slot should still have a slot), or multiple devices may exist
    that can be swapped out in one slot. For example: suppose a telescope has
    multiple instrument rotator and one can be in use at a particular time (perhaps none).
    In that case the axis DeviceSet's slot names might be ("az", "alt", "rot"),
    while the rotator device in the set might be None or might have a slot such as "rot1" or "rot2".
    """
    DefaultTimeLim = 5 # default time limit, in seconds; subclasses may override
    def __init__(self, actor, slotList, devList, connStateKeyword):
        """!Construct a DeviceSet

        @param[in] actor  actor (instance of twistedActor.BaseActor);
            used for writeToUsers in this class, and subclasses may make additonal use of it
        @param[in] slotList  name of each device slot (even if that slot has no device)
        @param[in] devList  sequence of devices;
            each device is either an instances of twistedActor.Device or is None if the device is unavailable
        @param[in] connStateKeyword  connection state keyword;
            format is &lt;connStateKeyword&gt;=state0, state1...
            where stateN is the state of the device in slot N, or None if no device

        @throw RuntimeError if:
        - len(devList) != len(slotList)
        - names in slotList are not unique
        """
        if len(slotList) != len(devList):
            raise RuntimeError("devList=%s and slotList=%s are not the same length" % \
                (devList, slotList))

        self.actor = actor
        self._connStateKeyword = connStateKeyword
        self._lastDevStateList = None # last reported device connection state

        # dict of slot name: index
        self._slotIndexDict = dict((slot, i) for i, slot in enumerate(slotList))
        # ordered dict of slot name: device
        self._slotDevDict = OrderedDict((slot, dev) for slot, dev in zip(slotList, devList))
        # dict of dev.name: slot name for current devices
        self._devNameSlotDict = dict((dev.name, slot) for (slot, dev) in self._slotDevDict.items() if dev)

        if len(self._slotDevDict) < len(slotList):
            raise RuntimeError("Names in slotList=%s are not unique" % (slotList,))

        for ind, dev in enumerate(self.devList):
            if dev:
                self._addDevCallbacks(dev, self.slotFromIndex(ind))

    def checkSlotList(self, slotList):
        """!Raise RuntimeError if any slots in slotList do not contain a device
        """
        try:
            emptySlotList = [slot for slot in slotList if not self[slot]]
        except KeyError:
            invalidSlotList = [slot for slot in slotList if not slot in self._slotDevDict]
            raise RuntimeError("One or more slots is unknown: %s" % (", ".join(invalidSlotList),))

        if emptySlotList:
            raise RuntimeError("One or more slots is empty: %s" % (", ".join(emptySlotList),))

    def connect(self, slotList=None, userCmd=None, timeLim=DefaultTimeLim):
        """!Connect devices specified by slot name

        @param[in] slotList  collection of slot names, or None for all filled slots
        @param[in] userCmd  user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim  time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @throw RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        # print("%s.connect(slotList=%s, userCmd=%r, timeLim=%r" % (self, slotList, userCmd, timeLim))
        return self._connectOrDisconnect(doConnect=True, slotList=slotList, userCmd=userCmd, timeLim=timeLim)

    def disconnect(self, slotList=None, userCmd=None, timeLim=DefaultTimeLim):
        """!Connect devices specified by slot name

        @param[in] slotList  collection of slot names, or None for all filled slots
        @param[in] userCmd  user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim  time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @throw RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        # print("%s.disconnect(slotList=%s, userCmd=%r, timeLim=%r" % (self, slotList, userCmd, timeLim))
        return self._connectOrDisconnect(doConnect=False, slotList=slotList, userCmd=userCmd, timeLim=timeLim)

    def expandSlotList(self, slotList, connOnly=False):
        """!Expand a collection of slot names, changing None to the correct list and checking the list

        @param[in] slotList  collection of slot names, or None for all filled slots
        @param[in] connOnly  if True and slotList is None then only include connected devices
            (typically used for status); ignored unless slotList is None
        @return expanded slot list

        @throw RuntimeError if slotList contains an unknown or empty slot name
        """
        if slotList is None:
            slotList = self.filledSlotList
            if connOnly:
                slotList = [slot for slot in slotList if self._slotDevDict[slot].isConnected]

        self.checkSlotList(slotList)
        return slotList

    @property
    def devExists(self):
        """!Return a list of bools, one per device: True if device exists
        """
        return [dev is not None for dev in self._slotDevDict.values()]

    @property
    def devList(self):
        """!Return the list of devices
        """
        return list(self._slotDevDict.values())

    @property
    def slotList(self):
        """!Return the list of slot names
        """
        return list(self._slotDevDict.keys())

    @property
    def filledSlotList(self):
        """!Return the list of names of filled slots
        """
        return [slot for slot, dev in self._slotDevDict.items() if dev]

    def get(self, slot, default=None):
        """!Return the device in the specified slot, or default if no such slot
        """
        return self._slotDevDict.get(slot, default)

    def getIndex(self, slot):
        """!Get the index of the slot

        @throw KeyError if slot does not exist
        """
        return self._slotIndexDict[slot]

    def showConnState(self, userCmd=None):
        """!Show connection state in slot order

        @param[in] userCmd  user command to use for reporting, or None; its state is not set
            if userCmd is None state is reported only if has changed since last time it was reported,
            or if not all existing devices are connected
        """
        devStateList = [dev.state if dev else "NotAvailable" for dev in self._slotDevDict.values()]
        if not all(dev.isConnected for dev in self._slotDevDict.values() if dev):
            msgCode = "w"
            doReport = True
        else:
            msgCode = "i"
            doReport = userCmd is not None or devStateList != self._lastDevStateList
        self._lastDevStateList = devStateList

        if doReport:
            msgStr = "%s=%s" % (self._connStateKeyword, ", ".join(devStateList))
            self.actor.writeToUsers(msgCode=msgCode, msgStr=msgStr, cmd=userCmd)

    def slotListFromBoolList(self, boolList):
        """!Return a list of slot names given a list of bools

        @param[in] boolList  a list of bool values of length len(self);

        @return a list of slot names corresponding to True values in boolList

        @warning there is no checking that the slot is filled.
        """
        if len(boolList) != len(self):
            raise RuntimeError("Expected %s bools but got %s" % (len(self), boolList))
        slotList = list(self._slotDevDict.keys())
        return [slotList[ind] for ind, boolVal in enumerate(boolList) if boolVal]

    def slotFromDevName(self, devName):
        """!Get the slot name from the device name, or None if this device is not current
        """
        return self._devNameSlotDict.get(devName)

    def slotFromIndex(self, index):
        """!Get the slot name from the index
        """
        return list(self._slotDevDict.keys())[index]

    def _setDev(self, slot, dev):
        """!Set the device at a particular slot

        This is a low-level command that does not connect or disconnect devices

        @param[in] slot  slot slot of device (must match a slot in slotList)
        @param[in] dev  device to go in this slot, or None if slot is empty
        @return the existing device in that slot
        """
        oldDev = self._slotDevDict[slot]
        self._slotDevDict[slot] = dev
        self._devNameSlotDict = dict((dev.name, slot)
            for slot, dev in self._slotDevDict.items() if dev is not None)
        return oldDev

    def replaceDev(self, slot, dev, userCmd=None, timeLim=DefaultTimeLim):
        """!Replace or remove one device

        The old device (if it exists) is disconnected, which initializes it

        @param[in] slot  slot slot of device (must match a slot in slotList)
        @param[in] dev  the new device, or None to remove the existing device
        @param[in] userCmd  user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim  time limit for each command (sec); None or 0 for no limit

        @return userCmd: the supplied userCmd or a newly created UserCmd

        @throw RuntimeError if slot is not in slotList
        """
        if slot not in self._slotDevDict:
            raise RuntimeError("Invalid slot %s" % (slot,))
        userCmd = expandUserCmd(userCmd)

        # disconnect and purge existing device, after removing callbacks
        oldDev = self._setDev(slot, None)
        if oldDev:
            self._removeDevCallbacks(oldDev, slot)
            oldDev.disconnect()

        if dev is None:
            # no new device, so disconnecting the old device is all we need to do
            # and we don't have to wait for it to fully disconnect
            if not userCmd.isDone:
                userCmd.setState(userCmd.Done)
            return userCmd

        # connect new device
        self._setDev(slot, dev)
        self._addDevCallbacks(dev, slot)
        dev.connect(userCmd=userCmd)
        return userCmd

    def startCmd(self, cmdStrOrList, slotList=None, callFunc=None, userCmd=None, timeLim=DefaultTimeLim):
        """!Start a command or list of commands on one or more devices

        The same command or list of commands is sent to each device;
        use startCmdDict to send different commands to different devices.

        @param[in] cmdStrOrList  command to send
        @param[in] slotList  collection of slot names, or None for all filled slots
        @param[in] callFunc  callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
        @param[in] userCmd  user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim  time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @throw RuntimeError if:
        - slotList has empty or non-existent slots
        - userCmd is already done
        """
        if slotList is None: # don't call expandSlotList because startCmdDict checks the slot names
            slotList = self.filledSlotList
        cmdDict = OrderedDict((slot, cmdStrOrList) for slot in slotList)
        return self.startCmdDict(cmdDict=cmdDict, callFunc=callFunc, userCmd=userCmd, timeLim=timeLim)

    def startCmdDict(self, cmdDict, callFunc=None, userCmd=None, timeLim=DefaultTimeLim):
        """!Start a dictionary of commands on one or more devices

        @param[in] cmdDict  a dict of slot: command string or sequence of command strings
            if the slot is empty or unknown then an exception is raised
        @param[in] callFunc  callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
        @param[in] userCmd  user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim  time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @throw RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        userCmd = expandUserCmd(userCmd)
        devCmdList = []
        for slot, cmdStrOrList in cmdDict.items():
            dev = self.get(slot)
            for cmd in asSequence(cmdStrOrList):
                devCmdList.append(dev.startCmd(cmd))
        LinkCommands(userCmd, devCmdList)
        return userCmd

    def _addDevCallbacks(self, dev, slot):
        """!Called when adding a device

        Called after device is registered in slot dictionary, but possibly before it is connected.
        Use to add callbacks to the device.

        @param[in] dev  device that has been removed
        @param[in] slot  slot the device occupied
        """
        dev.addCallback(self._devStateCallback)

    def _removeDevCallbacks(self, dev, slot):
        """!Called when removing a device

        Called after the device is deregistered from the slot dictionary, but before it is disconnected.
        Use this to remove callbacks from the device and to clear information about it.

        @param[in] dev  device that has been removed
        @param[in] slot  slot the device occupied
        """
        dev.removeCallback(self._devStateCallback)

    def _connectOrDisconnect(self, doConnect, slotList, userCmd, timeLim):
        """!Connect or disconnect a set of devices

        @param[in] doConnect  if True connect the specified devices, else disconnect them
        @param[in] slotList  collection of slot names, or None for all filled slots
        @param[in] userCmd  user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim  time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one
        """
        userCmd = expandUserCmd(userCmd)

        slotList = self.expandSlotList(slotList)
        userCmdList = []
        for slot in slotList:
            dev = self[slot]
            if dev:
                if doConnect:
                    connUserCmd = dev.connect(timeLim=timeLim)
                    userCmdList.append(connUserCmd)
                else:
                    disconnUserCmd = dev.disconnect(timeLim=timeLim)
                    userCmdList.append(disconnUserCmd)
        LinkCommands(userCmd, userCmdList)
        return userCmd

    def _devStateCallback(self, dev):
        self.showConnState()

    def __getitem__(self, slot):
        """!Return the device in the specified slot
        """
        return self._slotDevDict[slot]

    def __len__(self):
        """!Return number of slots"""
        return len(self._slotDevDict)

    def __repr__(self):
        return type(self).__name__

    def __contains__(self, slot):
        """!Return True if the slot exists
        """
        return slot in self._slotDevDict
