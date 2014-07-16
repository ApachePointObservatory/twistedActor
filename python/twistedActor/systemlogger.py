from __future__ import division, absolute_import
"""For allowing actors to write to syslog
"""
import syslog

DEBUG = syslog.LOG_DEBUG
INFO = syslog.LOG_INFO
WARNING = syslog.LOG_WARNING
ERROR = syslog.LOG_ERROR
CRITICAL = syslog.LOG_CRIT

facilityDict = {
    "local1": syslog.LOG_LOCAL1,  # these shoud be configured in syslog/rsyslog.conf
    "local2": syslog.LOG_LOCAL2,
    "local3": syslog.LOG_LOCAL3
}

# global state-tracker
StartedLogging = False

def startLogging(facility):
    """
    Start logging to a facility:
    @param[in]: facility, one of "local1", "local2", or "local3"

    modify /etc/rsyslog.conf to define where logging to this facility goes
    this file handles all rules (like which )
    """
    if facility not in ["local1", "local2", "local3"]:
        print "Unrecognized logging facility: %s. Use one of local1, local2, or local3" % facility
    global StartedLogging
    if StartedLogging:
        # logging already started do nothing, add warning to current log
        writeToLog("startLogging called, but logging is already started.", logLevel=WARNING)
        return
    syslog.openlog(facility = facilityDict[facility])
    StartedLogging = True

def stopLogging():
    global StartedLogging
    if not StartedLogging:
        return # not currently logging, do nothing
    syslog.closelog()
    StartedLogging = False

def writeToLog(msgStr, logLevel=INFO):
    """ Write to current log.

        @param[in] msgStr: string to be logged
        @param[in] logLevel: a log level available from syslog framework

    """
    global StartedLogging
    if StartedLogging:
        syslog.syslog(logLevel, msgStr)
    elif logLevel <= WARNING:
        print msgStr