from twistedActor import CommunicationChain, Actor, TCPDevice, getOpenPort, Commander
from twisted.trial.unittest import TestCase
import twisted
from twisted.internet import reactor
from twisted.internet.defer import Deferred
#twisted.internet.base.DelayedCall.debug = True

class DevShell(TCPDevice):
    def handleReply(self, reply):
        """Simply print any reply
        """
        print 'dev reply!', reply

class ActorShell(Actor):
    def initialConn(self):
        """Do nothing, connections are handled by test framework.
        This method is called automatically upon construction of an Actor
        """
        pass

    def logMsg(self, msg):
        """This method must also be specified.  In this case "log" to screen
        """
        print 'log msg', msg    

def getActorShell():
    """Return an ActorShell actor which listens on an open random port
    @return two items:
        portNum - port on which the actor listens
        actor - the instance of the actor
    """
    openPort = getOpenPort()
    return openPort, ActorShell(openPort)

def getActorDevShell(devConnPort):
    """Return an ActorShell which contains a device and listens on a random port.  
    Device connects to a specified port.
    @param[in] devConnPort: port which the device should connect to
    @return two items:
        portNum - port on which the actor listens
        actor - the instance of the actor
    """
    dev = DevShell(name = 'dev', host = "localhost", port = devConnPort)
    openPort = getOpenPort()
    return openPort, ActorShell(userPort = openPort, devs=(dev,))


class ActorTestCase(TestCase):
    def setUp(self):
        self.cc = CommunicationChain()
        pt1, act1 = getActorShell() # deviceless actor listens on pt1
        #pt2, act2 = getActorDevShell(pt1) # device connects to pt1, actor listens on pt2
        self.cc.addActor(act1)
       # self.cc.addActor(act2)
        self.cc.addCommander(Commander(pt1, "mirror"))
        return self.cc.startUp()

    def testNothing(self):
        print "Testing Nothing!!!!"

    def tearDown(self):
        return self.cc.shutDown()

if __name__ == '__main__':
    from unittest import main
    main()