from __future__ import division, absolute_import
"""Basic framework for a hub actor or ICC based on the Twisted event loop.
"""
import sys

import RO.Comm.TwistedSocket
from RO.StringUtil import quoteStr, strFromException

from .command import UserCmd
from .log import log

__all__ = ["BaseActor"]

class BaseActor(object):
    """Base class for a hub actor or instrument control computer with no assumption about command format
    other than commands may start with 0, 1 or 2 integers

    Subclass this and define parseAndDispatchCmd to parse and dispatch commands.
    """
    def __init__(self,
        userPort,
        maxUsers = 0,
        doDebugMsgs = False,
        version = "?",
        name = "BaseActor",
    ):
        """Construct a BaseActor

        Inputs:
        - userPort      port on which to listen for users
        - maxUsers      the maximum allowed # of users; if 0 then there is no limit
        - doDebugMsgs   print debug messages?
        - version       actor version str
        - name          a name, used for logging
        """
        self.name = name
        self.maxUsers = int(maxUsers)
        self.doDebugMsgs = bool(doDebugMsgs)
        self.version = str(version)

        # entries are: userID, socket
        self.userDict = dict()

        self.server = RO.Comm.TwistedSocket.TCPServer(
            connCallback = self.newUser,
            stateCallback = self.serverStateCallback,
            port = userPort,
        )

    def _cancelTimers(self):
        """Cancel all timers
        """
        pass

    def close(self):
        """Close the connection and cancel any timers
        """
        self.server.close()
        self._cancelTimers()

    def cmdCallback(self, cmd):
        """Called when a user command changes state; report completion or failure
        """
        if not cmd.isDone:
            return
        log.info("%s %s" % (self, cmd))
        msgCode, msgStr = cmd.getKeyValMsg()
        self.writeToUsers(msgCode, msgStr, cmd=cmd)

    @staticmethod
    def formatUserOutput(msgCode, msgStr, userID=None, cmdID=None):
        """Format a string to send to the all users.
        """
        return "%d %d %s %s" % (cmdID, userID, msgCode, msgStr)
        # changed from:
        #return "%d %d %s %s" % (userID, cmdID, msgCode, msgStr)

    @staticmethod
    def getUserCmdID(msgCode=None, cmd=None, userID=None, cmdID=None):
        """Return userID, cmdID based on user-supplied information.

        @param[in] msgCode: used to determine if cmd is a valid default:
            if cmd is provided and cmd.isDone and msgCode is not a done code, then cmd is ignored (treated as None).
            This allows you to continue to use a completed command to send informational messages,
            which can simplify code. Note that it is also possible to send multiple done messages for a command,
            but that indicates a serious bug in your code.
        @param[in] cmd: user command; used as a default for userID and cmdID, but see msgCode
        @param[in] userID: user ID: if None then use cmd.cmdID, but see msgCode
        @param[in] cmdID: command ID: if None then use cmd.userID, but see msgCode
        """
        if cmd is not None and msgCode is not None and cmd.isDone:
            state = cmd.stateFromMsgCode(msgCode)
            if state not in cmd.DoneStates:
                # ignore command
                cmd = None
        return (
            userID if userID is not None else (cmd.userID if cmd else 0),
            cmdID if cmdID is not None else (cmd.cmdID if cmd else 0),
        )

    def newCmd(self, sock):
        """Called when a command is read from a user.

        Note: command name collisions are resolved as follows:
        - local commands (cmd_<foo> methods of this actor)
        - commands handled by devices
        - direct device access commands (device name)
        """
        cmdStr = sock.readLine()
        log.info("%s.newCmd(%r)" % (self, cmdStr))
        #print "%s.newCmd; cmdStr=%r" % (self, cmdStr,)
        if not cmdStr:
            return
        userID = getSocketUserID(sock)
        try:
            cmd = UserCmd(userID, cmdStr, self.cmdCallback)
        except Exception, e:
            self.writeToUsers("f", "Could not parse the following as a command: %r"%cmdStr)
            return
        try:
            self.parseAndDispatchCmd(cmd)
        except Exception, e:
            cmd.setState(cmd.Failed, "Command %r failed: %s" % (cmd.cmdBody, strFromException(e)))

    def newUser(self, sock):
        """A new user has connected. Assign an ID and report it to the user.
        """
        if self.maxUsers and len(self.userDict) >= self.maxUsers:
            sock.writeLine("0 0 E NoFreeConnections")
            sock.close()
            return

        currIDs = set(self.userDict.keys())
        userID = 1
        while userID in currIDs:
            userID += 1
        # add userID as an attribute that is likely to be unique
        setSocketUserID(sock, userID)

        self.userDict[userID] = sock
        sock.setReadCallback(self.newCmd)
        sock.addStateCallback(self.userSocketClosing)

        # report user information and additional info
        fakeCmd = UserCmd(userID=userID)
        self.showNewUserInfo(fakeCmd)
        return fakeCmd

    def showNewUserInfo(self, fakeCmd):
        """Show information for new users; called automatically when a new user connects

        Inputs:
        - fakeCmd: a minimal command that just contains the ID of the new user
        """
        self.showUserInfo(fakeCmd)
        self.showVersion(fakeCmd, onlyOneUser=True)

    def parseAndDispatchCmd(self, cmd):
        """Dispatch a user command
        """
        raise NotImplementedError()

    def serverStateCallback(self, sock):
        """Server socket state callback
        """
        if self.server.isReady:
            print "%s listening on port %s" % (self, self.server.port)
        log.info("%s.server.state=%s" % (self, self.server.state))

    def showUserInfo(self, cmd):
        """Show user information including your userID.
        """
        numUsers = len(self.userDict)
        if numUsers == 0:
            return
        msgData = [
            "YourUserID=%s" % (cmd.userID,),
            "NumUsers=%s" % (numUsers,),
        ]
        msgStr = "; ".join(msgData)
        self.writeToOneUser("i", msgStr, cmd=cmd)
        self.showUserList(cmd)

    def showUserList(self, cmd=None):
        """Show a list of connected users
        """
        userIdList = sorted(self.userDict.keys())
        for userId in userIdList:
            sock = self.userDict[userId]
            msgStr = "UserInfo=%s, %s" % (userId, sock.host)
            self.writeToUsers("i", msgStr, cmd=cmd)

    def userSocketClosing(self, sock):
        """Called when a user socket is closing

        Technically this is called for any state change, but it amounts to "when closing"
        because the socket is connected before the callback is registered,
        and once a socket starts closing this callback is deregistered.
        """
        if sock.isReady: # paranoia; don't discard a connected user
            sys.err.write("Warning: userSocketClosing(sock=%s) but socket.isReady=True, socket.state=%r\n" % \
                (sock, sock.state))
            return

        try:
            del self.userDict[getSocketUserID(sock)]
        except KeyError:
            sys.stderr.write("Warning: user socket closed but could not find user %s in userDict\n" %
                (getSocketUserID(sock),))
        sock.removeStateCallback(self.userSocketClosing, doRaise=False) # I'm done with this socket; I don't want to know when it is fully closed
        self.showUserList(cmd=UserCmd(userID=0))

    def showVersion(self, cmd, onlyOneUser=False):
        """Show actor version
        """
        msgStr = "Version=%s" % (quoteStr(self.version),)
        if onlyOneUser:
            self.writeToOneUser("i", msgStr, cmd=cmd)
        else:
            self.writeToUsers("i", msgStr, cmd=cmd)

    def writeToUsers(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to all users.

        @param[in] msgCode: message code (e.g. "i"); see command.py for a full list of message codes.
        @param[in] cmd: user command; used as a default for userID and cmdID, but see msgCode
        @param[in] userID: user ID: if None then use cmd.cmdID, but see msgCode
        @param[in] cmdID: command ID: if None then use cmd.userID, but see msgCode

        cmdID and userID are obtained from cmd unless overridden by the explicit argument. Both default to 0.
        However, if cmd.isDone and msgCode is not a done code, then cmd is ignored.
        This allows you to continue to use a completed command to send informational messages,
        which can simplify code. (It is a serious bug to send multiple done messages for any command.)
        """
        userID, cmdID = self.getUserCmdID(msgCode=msgCode, cmd=cmd, userID=userID, cmdID=cmdID)
        fullMsgStr = self.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        #print "writeToUsers(%s)" % (fullMsgStr,)
        log.info("%s.writeToUsers(%r)" % (self, fullMsgStr))
        for sock in self.userDict.itervalues():
            sock.writeLine(fullMsgStr)

    def writeToOneUser(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to one user.

        @param[in] msgCode: message code (e.g. "i"); see command.py for a full list of message codes.
        @param[in] cmd: user command; used as a default for userID and cmdID, but see msgCode
        @param[in] userID: user ID: if None then use cmd.cmdID, but see msgCode
        @param[in] cmdID: command ID: if None then use cmd.userID, but see msgCode

        cmdID and userID are obtained from cmd unless overridden by the explicit argument. Both default to 0.
        However, if cmd.isDone and msgCode is not a done code, then cmd is ignored.
        This allows you to continue to use a completed command to send informational messages,
        which can simplify code. (It is a serious bug to send multiple done messages for any command.)
        """
        userID, cmdID = self.getUserCmdID(msgCode=msgCode, cmd=cmd, userID=userID, cmdID=cmdID)
        if userID == 0:
            print "Error: writeToOneUser asked to write to userID=0; msgCode=%r; msgStr=%r; cmd=%r; userID=%r; cmdID=%r" % (msgCode, msgStr, cmd, userID, cmdID)
            raise RuntimeError("writeToOneUser cannot write to user 0")
        sock = self.userDict[userID]
        fullMsgStr = self.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        #print "writeToOneUser(%s)" % (fullMsgStr,)
        log.info("%s.writeToOneUser(%r); userID=%s" % (self, fullMsgStr, userID))
        sock.writeLine(fullMsgStr)

    @classmethod
    def writeToStdOut(cls, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to stdout.

        One use is writing properly formatted messages in the absence of an instance of BaseActor
        (note that this is a class method).

        @param[in] msgCode: message code (e.g. "i"); see command.py for a full list of message codes.
        @param[in] cmd: user command; used as a default for userID and cmdID, but see msgCode
        @param[in] userID: user ID: if None then use cmd.cmdID, but see msgCode
        @param[in] cmdID: command ID: if None then use cmd.userID, but see msgCode

        cmdID and userID are obtained from cmd unless overridden by the explicit argument. Both default to 0.
        However, if cmd.isDone and msgCode is not a done code, then cmd is ignored.
        This allows you to continue to use a completed command to send informational messages,
        which can simplify code. (It is a serious bug to send multiple done messages for any command.)
        """
        userID, cmdID = cls.getUserCmdID(msgCode=msgCode, cmd=cmd, userID=userID, cmdID=cmdID)
        fullMsgStr = cls.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        print fullMsgStr

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, self.name)

def getSocketUserID(sock):
    """Get a user ID from a socket
    """
    return sock._actor_userID

def setSocketUserID(sock, userID):
    """Set a user ID on a socket
    """
    sock._actor_userID = userID
