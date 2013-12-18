from twistedActor import CommunicationChain, getActorShell, getActorDevShell
from twisted.trial.unittest import TestCase

class ActorTestCase(TestCase):
    def setUp(self):
        self.cc = CommunicationChain()
        pt1, act1 = getActorShell() # deviceless actor listens on pt1
        pt2, act2 = getActorDevShell(pt1) # device connects to pt1, actor listens on pt2
        self.cc.addActor(act1)
        self.cc.addActor(act2)
        return self.cc.startUp()

    def testNothing(self):
        print "Testing Nothing!!!!"

    def tearDown(self):
        return self.cc.shutDown()

if __name__ == '__main__':
    from unittest import main
    main()