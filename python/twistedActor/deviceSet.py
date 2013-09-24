import collections
import itertools
import sys
import traceback

import RO.SeqUtil
from RO.StringUtil import quoteStr
from twistedActor import UserCmd

__all__ = ["DeviceSet"]

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
            raise RuntimeError("devList and slotList must have the same length")
        
        self.actor = actor
        # ordered dict of slot slot: device
        self._devDict = collections.OrderedDict((slot, dev) for slot, dev in itertools.izip(slotList, devList))
        self._slotIndexDict = dict((slot, i) for i, slot in enumerate(slotList))

        if len(self._devDict) < len(slotList):
            raise RuntimeError("Names in slotList=%s not unique" % (slotList,))

    def checkSlotList(self, slotList):
        """Raise RuntimeError if any slots in slotList do not contain a device
        """
        try:
            emptySlotList = [slot for slot in slotList if not self[slot]]
        except KeyError:
            invalidSlotList = [slot for slot in slotList if not slot in self._devDict]
            raise RuntimeError("One or more slots is unknown: %s" % (", ".join(invalidSlotList),))

        if emptySlotList:
            raise RuntimeError("One or more slots is empty: %s" % (", ".join(emptySlotList),))

    def expandSlotList(self, slotList):
        """Expand a collection of slot names, changing None to the correct list and checking the list

        @param[in] slotList: collection of slot names, or None for all filled slots

        @raise RuntimeError if slotList contains an unknown or empty slot name
        """
        if slotList is None:
            return self.slotList

        self.checkSlotList(slotList)
        return slotList

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

    def __getitem__(self, slot):
        """Return the device in the specified slot
        """
        return self._devDict[slot]

    @property
    def slotList(self):
        """Return the list of slot names
        """
        return self._devDict.keys()

    @property
    def fullSlotList(self):
        """Return the list of names of filled slots
        """
        return [slot for slot, dev in self._devDict.iteritems() if dev]

    def getIndex(self, slot):
        """Get the index of the slot

        @raise KeyError if slot does not exist
        """
        return self._slotIndexDict[slot]

    def replaceDev(self, slot, dev):
        """Replace one device

        @param[in] slot: slot slot of device (must match a slot in slotList)
        @param[in] dev: the new device, or None if device does not exist

        @raise RuntimeError if slot is not in slotList
        """
        if slot not in self._devDict:
            raise RuntimeError("Invalid slot %s" % (slot,))
        self._devDict[slot] = dev

    def startCmd(self, cmdStrOrList, slotList=None, callFunc=None, userCmd=None):
        """Start a command or list of commands on one or more devices

        The same command or list of commands is sent to each device;
        use startCmdDict to send different commands to different devices.

        @param[in] cmdStrOrList: command to send
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] callFunc: callback function when a device command is done, or None;
            see the description in startCmdList for details.
        @param[in] userCmd: user command whose set state is set to Done or Failed when all device commands are done;
            if None a new UserCmd is created and returned
        @return userCmd: the supplied userCmd or a newly created UserCmd

        @raise RuntimeError if slotList has empty or non-existent slots
        """
        if slotList is None:
            slotList = self.fullSlotList
        cmdDict = collections.OrderedDict((slot, cmdStrOrList) for slot in slotList)
        return self.startCmdDict(cmdDict=cmdDict, callFunc=callFunc, userCmd=userCmd)

    def startCmdDict(self, cmdDict, callFunc=None, userCmd=None):
        """Start a dictionary of commands on one or more devices

        @param[in] cmdDict: a dict of slot: command string or sequence of command strings
            if the slot is empty or unknown then an exception is raised
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
            The function may return a new devCmd, in which case the completion of the full set of commands
            is delayed until the new command is finished; one use case is to initialize an actuator if a move fails.
        @param[in] userCmd: user command whose set state is set to Done or Failed when all device commands are done;
            if None a new UserCmd is created and returned
        @return userCmd: the supplied userCmd or a newly created UserCmd.
        
        @raise RuntimeError if a command is specified for an empty or unknown slot
        """
        if userCmd is None:
            userCmd = UserCmd()
        elif userCmd.isDone:
            print "Warning: %s.startCmdDict: userCmd %s is done; creating a new one" % (type(self).__name__, userCmd)
            userCmd = UserCmd()

        devCmdDict = dict()
        failSlotSet = set()

        def checkDone(dumArg=None):
            """If all device commands are finished, then set userCmd to Failed or Done as appropriate
            """
            for slot, devCmd in devCmdDict.iteritems():
                if not devCmd.isDone:
                    return
                if devCmd.didFail:
                    failSlotSet.add(slot)
            
            # all device commands are done
            if failSlotSet:
                failedAxisStr = ", ".join(slot for slot in failSlotSet)
                userCmd.setState(userCmd.Failed, textMsg="Command failed for %s" % (failedAxisStr,))
            else:
                userCmd.setState(userCmd.Done)        

        self.checkSlotList(cmdDict.keys())
        for slot, cmdStrOrList in cmdDict.iteritems():
            dev = self[slot]

            def devCmdCallback(devCmd, slot=slot, dev=dev):
                if devCmd.didFail:
                    failSlotSet.add(slot)
                
                devCmdDict[slot] = devCmd

                if callFunc:
                    try:
                        newDevCmd = callFunc(DevCmdInfo(slot=slot, dev=dev, devCmd=devCmd, userCmd=userCmd))
                        if newDevCmd:
                            # the callback function started a new command;
                            # update devCmdDict and checkDone when it is done, but do NOT run callFunc again
                            devCmdDict[slot] = newDevCmd
                            def newDevCmdCallback(devCmd, slot=slot, dev=dev):
                                devCmdDict[slot] = devCmd
                                checkDone()

                            newDevCmd.addCallback(newDevCmdCallback)
                            devCmdDict[slot] = newDevCmd
                    except Exception:
                        failSlotSet.add(slot)
                        textBody = "%s command %r failed" % (slot, devCmd.cmdStr)
                        msgStr = "Text=%s" % (quoteStr(textBody),)
                        self.actor.writeToUsers("f", msgStr=msgStr)
                        traceback.print_exc(file=sys.stderr)

                checkDone()

            if not RO.SeqUtil.isSequence(cmdStrOrList):
                devCmd = dev.startCmd(cmdStrOrList)
            else:
                devCmd = dev.startCmdList(cmdStrOrList)
            devCmdDict[slot] = devCmd
            devCmd.addCallback(devCmdCallback)

        checkDone()
        return userCmd
