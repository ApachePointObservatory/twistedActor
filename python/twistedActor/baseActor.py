"""Basic framework for a hub actor or ICC based on the Tcl event loop.
"""
__all__ = ["BaseActor"]

import sys
import RO.Comm.TwistedSocket
from .command import UserCmd

class BaseActor(object):
    """Base class for a hub actor or instrument control computer with no assumption about command format
    other than commands may start with 0, 1 or 2 integers
    
    Subclass this and define dispatchCmd to dispatch commands.
    
    If you want a special command parser then replace UserCmdClass
    """
    UserCmdClass = UserCmd
    def __init__(self,
        userPort,
        maxUsers = 0,
        doDebugMsgs = False,
    ):
        """Construct a BaseActor
    
        Inputs:
        - userPort      port on which to listen for users
        - maxUsers      the maximum allowed # of users; if 0 then there is no limit
        """        
        self.maxUsers = int(maxUsers)
        # entries are: user's socket: userID
        self.userDict = dict()

        self.doDebugMsgs = True
        
        self.userListener = RO.Comm.TwistedSocket.TCPServer(
            connCallback = self.newUser,
            port = userPort,
        )
    
    def cmdCallback(self, cmd):
        """Called when a user command changes state; report completion or failure
        """
        if not cmd.isDone():
            return
        msgCode, msgStr = cmd.hubFormat()
        self.writeToUsers(msgCode, msgStr, cmd=cmd)

    def formatUserOutput(self, msgCode, msgStr, userID=None, cmdID=None):
        """Format a string to send to the all users.
        """
        return "%d %d %s %s" % (userID, cmdID, msgCode, msgStr)
    
    def getUserCmdID(self, cmd=None, userID=None, cmdID=None):
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
        if not cmdStr:
            return
        userID = getSocketUserID(sock)
        
        cmd = self.UserCmdClass(userID, cmdStr, self.cmdCallback)
        self.dispatchCmd(cmd)

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
        sock.setStateCallback(self.userStateChanged)
        
        # report user information and additional info
        fakeCmd = self.UserCmdClass(userID=userID)
        self.showUserInfo(fakeCmd)
        self.showDevConnStatus(cmd=fakeCmd, onlyOneUser=True, onlyIfNotConn=True)
        self.newUserOutput(userID)
    
    def newUserOutput(self, userID):
        """Override to report additional status to the new user other than userID and bad device status
        """
        pass
    
    def dispatchCmd(self, cmd):
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
        sockList = self.userDict.values()
        sockList.sort(key=lambda x: getSocketUserID(x))
        userInfo = ["%s, %s" % (getSocketUserID(sock), sock.addr) for sock in sockList]
        userInfoStr = ",".join(userInfo)
        msgData.append("UserInfo=%s" % (userInfoStr,))
        msgStr = "; ".join(msgData)
        msgStr = self.writeToOneUser("i", msgStr, cmd=cmd)
        
    def userStateChanged(self, sock):
        """Called when a user connection changes state.
        """
        if not sock.isClosed():
            return

        try:
            del self.userDict[getSocketUserID(sock)]
        except KeyError:
            sys.stderr.write("Warning: user socket closed but could not find user %s in userDict\n" % 
                (getSocketUserID(sock),))

    def writeToUsers(self, msgCode, msgStr, cmd=None, userID=None, cmdID=None):
        """Write a message to all users.
        
        cmdID and userID are obtained from cmd unless overridden by the explicit argument. Both default to 0.
        """
        userID, cmdID = self.getUserCmdID(cmd=cmd, userID=userID, cmdID=cmdID)
        fullMsgStr = self.formatUserOutput(msgCode, msgStr, userID=userID, cmdID=cmdID)
        #print "writeToUsers(%s)" % (fullMsgStr,)
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
        sock.writeLine(fullMsgStr)

def getSocketUserID(sock):
    """Get a user ID from a socket
    """
    return sock._actor_userID

def setSocketUserID(sock, userID):
    """Set a user ID on a socket
    """
    sock._actor_userID = userID
