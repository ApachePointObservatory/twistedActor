"""Basic framework for a hub actor or ICC based on the Tcl event loop.
"""
__all__ = ["BaseActor"]

import sys
import os
import RO.Comm.TwistedSocket
from RO.StringUtil import quoteStr, strFromException
from .command import UserCmd

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
            port = userPort,
        )
    
    def logMsg(self, msgStr):
        """
        Should be specified by subclasses.
        """
        raise NotImplementedError("When coding an actor, you must supply a method for logging.")
    
    def cmdCallback(self, cmd):
        """Called when a user command changes state; report completion or failure
        """
        if not cmd.isDone:
            return
        msgCode, msgStr = cmd.hubFormat()
        self.writeToUsers(msgCode, msgStr, cmd=cmd)

    @staticmethod
    def formatUserOutput(msgCode, msgStr, userID=None, cmdID=None):
        """Format a string to send to the all users.
        """
        return "%d %d %s %s" % (cmdID, userID, msgCode, msgStr)
        # changed from:
        #return "%d %d %s %s" % (userID, cmdID, msgCode, msgStr)
    
    @staticmethod
    def getUserCmdID(cmd=None, userID=None, cmdID=None):
        """Return userID, cmdID based on user-supplied information.
        """
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
        self.logMsg("UserCmd(%s)" % (cmdStr,))
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
        sock.setStateCallback(self.userSocketClosing)
        
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
        sock.setStateCallback() # I'm done with this socket; I don't want to know when it is fully closed
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
        
        cmdID and userID are obtained from cmd unless overridden by the explicit argument. Both default to 0.
        """
        userID, cmdID = self.getUserCmdID(cmd=cmd, userID=userID, cmdID=cmdID)
        fullMsgStr = self.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        #print "writeToUsers(%s)" % (fullMsgStr,)
        self.logMsg("To All Users(%s)" % (fullMsgStr,))
        for sock in self.userDict.itervalues():
            sock.writeLine(fullMsgStr)
    
    def writeToOneUser(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to one user.

        cmdID and userID are obtained from cmd unless overridden by the explicit argument. Both default to 0.
        """
        userID, cmdID = self.getUserCmdID(cmd=cmd, userID=userID, cmdID=cmdID)
        if userID == 0:
            raise RuntimeError("Cannot write to user 0")
        sock = self.userDict[userID]
        fullMsgStr = self.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        #print "writeToOneUser(%s)" % (fullMsgStr,)
        self.logMsg("To One User(%s)" % (fullMsgStr,))
        sock.writeLine(fullMsgStr)

    @classmethod
    def writeToStdOut(cls, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to stdout.
        
        One use is writing properly formatted messages in the absence of an instance of BaseActor.
        """
        userID, cmdID = cls.getUserCmdID(cmd=cmd, userID=userID, cmdID=cmdID)
        fullMsgStr = cls.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        print fullMsgStr
    
    def __str__(self):
        return "%s(userPort=%r)" % (self.__class__.__name__, self.server.port)

def getSocketUserID(sock):
    """Get a user ID from a socket
    """
    return sock._actor_userID

def setSocketUserID(sock, userID):
    """Set a user ID on a socket
    """
    sock._actor_userID = userID
