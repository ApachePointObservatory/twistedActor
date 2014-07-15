from __future__ import division, absolute_import
"""For allowing actors to write to sys log
"""
import syslog

DEBUG = syslog.LOG_DEBUG
INFO = syslog.LOG_INFO
WARNING = syslog.LOG_WARNING
ERROR = syslog.LOG_ERROR
CRITICAL = syslog.LOG_CRIT

# global state-tracker
StartedLogging = False

def startLogging(facility):
    """
    Start logging to a facility:
    @param[in]: facility.

    modify /etc/rsyslog.conf to define where logging to this facility goes
    this file handles all rules (like which )
    """
    global StartedLogging
    if StartedLogging:
        # logging already started do nothing, add warning to current log
        writeToLog("startLogging called, but logging is already started.", logLevel=WARNING)
        return
    syslog.openlog(facility = facility)
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
    if LogState.startedLogging:
        syslog.syslog(logLevel, msgStr)
    elif logLevel <= WARNING:
        print msgStr