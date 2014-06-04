from __future__ import absolute_import, division
"""Make a startup script for a given actor
"""

def makeStartupScript(actorName, pkgName, binScript, logDirVar="TWISTED_LOG_DIR"):
    """Return a startup bash script as a long string

    @param[in]
    - actorName: name of actor. Used only for messages.
    - pkgName: eups package name of actor.
    - binScript: script that starts the actor, e.g. "tcc35m.py";
        if it is not on $PATH, then it must be specified relative to its package directory.
    - logDirVar: name of environment variable for the directory into which to write logs
    """
    argDict = dict(
        actorName = actorName,
        pkgDirVar = "%s_DIR" % (pkgName,),
        binScript = binScript,
        logDirVar = logDirVar,
    )

    return """#!/bin/bash

if test -z "$TCC_DIR"; then
    echo "The %(actorName)s is not setup" >&1
    exit 1
fi

echo
echo ====================== Using %(actorName)s in %(pkgDirVar)s=$%(pkgDirVar)s
echo

usage() {
    echo "usage: $0 start|stop|restart|status" >&2
    exit 1
}

if test $# != 1; then
    usage
fi
cmd=$1

# in case binScript is not on $PATH
cd $%(pkgDirVar)s

# Return the actor's pid, or the empty string.
#
get_pid() {
    PID=""
    pid=`/bin/ps -e -ww -o pid,user,command | egrep -v 'awk|grep' | grep '%(binScript)s' | awk '{print $1}'`
    PID=$pid
    
    if test "$pid"; then
        echo "%(actorName)s is running as process $pid"
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
    
    echo "Starting new %(actorName)s...\c"

    now=`date -u +"%%Y-%%m-%%dT%%H:%%M:%%SZ"`
    (cd $%(logDirVar)s; rm -f current.log; ln -s $now current.log)
    %(binScript)s >$%(logDirVar)s/%(actorName)s_stdout_$now 2>&1 &        
    
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

# Query a running actor for simple status.
#
do_status() {
    get_pid
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
        
        # Query it for essential liveness
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
""" % argDict
