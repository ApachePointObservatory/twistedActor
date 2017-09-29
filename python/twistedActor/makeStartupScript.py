
"""!Make a startup script for a given actor
"""
import os
import sys

from twistedActor import getLoggerFacilityName

def makeStartupScript(actorName, pkgName, binScript, userPort, facility):
    """!Return a startup bash script as a long string

    script output is redirected to the syslog using the specified facility:
    - stdout uses priority "warning"
    - stderr uses priority "error"

    @param[in] actorName  name of actor. Used only for messages.
    @param[in] pkgName  eups package name of actor.
    @param[in] binScript  script that starts the actor, e.g. "tcc35m.py";
        if it is not on $PATH, then it must be specified relative to its package directory.
    @param[in] userPort  port or list of ports on which actor will listen for commands
    @param[in] facility  logging facility (e.g. syslog.LOG_LOCAL1
    """
    pkgDirVar = "%s_DIR" % (pkgName.upper(),)
    try:
        pkgDir = os.environ[pkgDirVar]
    except KeyError:
        print("%s not setup" % (actorName,))
        sys.exit(1)

    facilityName = getLoggerFacilityName(facility)

    valDict = dict(
        actorName = actorName,
        pkgDirVar = pkgDirVar,
        pkgDir = pkgDir,
        binScript = binScript,
        userPort = userPort,
        facilityName = facilityName,
    )

    return """#!/bin/bash

if test -z $%(pkgDirVar)s; then
    echo "The %(actorName)s is not setup" >&1
    exit 1
fi

echo
echo ====================== Using %(actorName)s in $%(pkgDirVar)s='%(pkgDir)s'
echo

usage() {
    echo "usage: $0 start|stop|restart|status" >&2
    exit 1
}

if test $# != 1; then
    usage
fi
cmd=$1

# Return the actor's pid, or the empty string.
#
get_pid() {
    PID=""
    pid=`/bin/ps -e -ww -o pid,user,command | egrep -v 'awk|grep' | grep '%(binScript)s' | awk '{print $1}'`
    PID=$pid
    
    if test "$pid"; then
        echo "%(actorName)s is running on port %(userPort)s as process $pid"
    else
        echo "%(actorName)s is not running"
    fi
}

# Start a new actor. Complain if the actor is already running,  and do not start a new one.
#
do_start() {
    get_pid
    
    if test "$PID"; then
        echo "NOT starting new %(actorName)s. Use restart if you want a new one."
        return
    fi
    
    echo "Starting new %(actorName)s..."

    # run the actor, as follows:
    # disable buffering of stdout using "stdbuf -o0"
    # redirect stdout to logger at priority "warning" and stderr at priority "error"
    {
        stdbuf -o0 %(binScript)s 2>&3 | logger -p %(facilityName)s.warning
    } 3>&1 | logger -p %(facilityName)s.error &
    
    # Check that it really started...
    #
    sleep 1
    get_pid

    if test "$PID"; then
        echo " done."
    else
        echo " FAILED!"
    fi
}

# Stop any running actor. 
#
do_stop() {
    get_pid
    
    if test ! "$PID"; then
        return
    fi
    
    echo "Stopping %(actorName)s."
    kill -TERM $PID
}

# Stop any running actor fairly violently. 
#
do_stopdead() {
    get_pid
    
    if test ! "$PID"; then
        return
    fi
    
    echo "Stopping %(actorName)s gently."
    kill -TERM $PID
    sleep 2

    echo "Stopping %(actorName)s meanly."
    kill -KILL $PID
}

case $cmd in
    start) 
        do_start
        ;;
    stop)
        do_stop
        ;;
    stopdead)
        do_stopdead
        ;;
    status)
        # Check whether the actor is running
        get_pid
        ;;
    restart)
        do_stop
        sleep 2
        do_start                
        ;;
    *)
        usage
        ;;
esac

exit 0
""" % valDict
