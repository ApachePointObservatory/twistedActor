#!/usr/bin/env python
from twisted.internet import reactor
from twistedActor import Actor

if __name__ == "__main__":
    port = 2005
    
    print "Starting up the actor on port", port
    Actor(
        userPort = port,
    )

    reactor.run()
