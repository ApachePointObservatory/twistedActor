#!/usr/bin/env python
from twisted.internet import reactor
from twistedActor import Actor
class SimpleActor(Actor):
	## log method must be implemented
	def logMsg(self, msg):
		print 'log: %s' % msg

if __name__ == "__main__":
    port = 2005
    
    print "Starting up the actor on port", port
    SimpleActor(
        userPort = port,
    )


    reactor.run()
