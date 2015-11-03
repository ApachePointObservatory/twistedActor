#!/usr/bin/env python2
from __future__ import division, absolute_import
"""Test parser.  Use arctics command set, copied directly below
"""
import unittest

from twistedActor.parse import Command, CommandSet, KeywordValue, Float, String, Int, UniqueMatch, RestOfLineString

optionalExposeArgs = [
    KeywordValue(
        keyword="basename",
        value=String(helpStr="string help"),
        isMandatory=False,
        helpStr="basename help"
    ),
    KeywordValue(
        keyword="comment",
        value=String(helpStr="comment help"),
        isMandatory=False,
        helpStr="comment help"
    ),
]

timeArg = [
    KeywordValue(
        keyword="time",
        value=Float(helpStr="float help"),
        helpStr="time help"
    )
]

arcticCommandSet = CommandSet(
    commandList = [
        # set command
        Command(
            commandName = "set",
            floatingArguments = [
                KeywordValue(
                    keyword="bin",
                    value=Int(nElements=(1,2), helpStr="an int"),
                    isMandatory=False,
                    helpStr="bin help"
                    ),
                KeywordValue(
                    keyword="window",
                    value=String(nElements=(1,4), helpStr="window list value help"), # must be string to support "full"
                    isMandatory=False,
                    helpStr="window help"
                    ),
                KeywordValue(
                    keyword="amps",
                    value=UniqueMatch(["LL", "UL", "UR", "LR", "Quad", "Auto"], helpStr="unique match"),
                    isMandatory=False,
                    helpStr="amps help"
                    ),
                KeywordValue(
                    keyword="readoutRate",
                    value=UniqueMatch(["Slow", "Medium", "Fast"], helpStr="unique match"),
                    isMandatory=False,
                    helpStr="readoutRate help"
                    ),
                KeywordValue(
                    keyword="filter",
                    value=String(helpStr="a name or number"),
                    isMandatory=False,
                    helpStr="filter help"
                    ),
                KeywordValue(
                    keyword="temp",
                    value=Float(helpStr="temp set point"),
                    isMandatory=False,
                    helpStr="temp help"
                    ),
            ],
            helpStr="set command help"
        ),
        Command(
            commandName = "expose",
            subCommandList = [
                Command(
                    commandName="Object",
                    floatingArguments = timeArg + optionalExposeArgs,
                    helpStr="object subcommand help"
                ),
                Command(
                    commandName="Flat",
                    floatingArguments = timeArg + optionalExposeArgs,
                    helpStr="flat subcommand help"
                ),
                Command(
                    commandName="Dark",
                    floatingArguments = timeArg + optionalExposeArgs,
                    helpStr="dark subcommand help"
                ),
                Command(
                    commandName="Bias",
                    floatingArguments = optionalExposeArgs,
                    helpStr="bias subcommand help"
                ),
                Command(
                    commandName="pause",
                    helpStr="pause subcommand help"
                ),
                Command(
                    commandName="resume",
                    helpStr="resume subcommand help"
                ),
                Command(
                    commandName="stop",
                    helpStr="stop subcommand help"
                ),
                Command(
                    commandName="abort",
                    helpStr="abort subcommand help"
                ),
            ]
        ),
        Command(
            commandName = "camera",
            positionalArguments = [UniqueMatch(["status", "init"], helpStr="unique match help")],
            helpStr = "camera help"
        ),
        Command(
            commandName = "filter",
            subCommandList = [
                Command(
                    commandName = "status",
                    helpStr = "subcommand status help"
                ),
                Command(
                    commandName = "init",
                    helpStr = "subcommand init help"
                ),
                Command(
                    commandName = "connect",
                    helpStr = "subcommand connect help"
                ),
                Command(
                    commandName = "disconnect",
                    helpStr = "subcommand disconnect help"
                ),
                Command(
                    commandName = "home",
                    helpStr = "subcommand home help"
                ),
                Command(
                    commandName = "talk",
                    positionalArguments = [RestOfLineString(helpStr="text to send to filter")],
                    helpStr = "subcommand talk help"
                ),
            ]
        ),
        Command(
            commandName = "init",
            helpStr = "init help"
        ),
        Command(
            commandName = "status",
            helpStr = "status help"
        ),
        Command(
            commandName = "connDev",
            helpStr = "connect device(s)"
        ),
        Command(
            commandName = "disconnDev",
            helpStr = "disconnect device(s)"
        ),
        Command(
            commandName = "ping",
            helpStr = "show alive"
        ),
    ]
)

commandList = [
    "set bin=2 window=full amps=auto filter=2 temp=100.6 readoutRate=fast",
    "set bin=2 window=2,2,400,800 amps=auto filter=2 temp=100 readoutRate=medium",
    "set bin=4 window=2,2,400,800 amps=auto filter=2 temp=100 readoutRate=slow",
    "set bin=1 window=2,2,400,800 amps=auto filter=u temp=100 readoutRate=fast",
    "set bin=0 amps=quad window=0,2,400,800 filter=2 temp=100 readoutRate=medium",
    "set bin=0 window=0,2,400,800 amps=auto filter=2 temp=1e10 readoutRate=medium",
    "set bin=0 window=0,2,400,800 filter=2 amps=ll readoutRate=medium temp=1E10",
    "set bin=0 window=full amps=auto filter=2 temp=100.6 readoutRate=medium",
    "set bin=1 window=0,0,400,800 amps=auto filter=g temp=100 readoutRate=medium",
    "set bin=1 window=full amps=auto filter=r readoutRate=fast temp=100",
    "expose object time=100",
    "expose object time=100 basename=test",
    "expose object time=100 basename=test/path",
    "expose object time=100 basename='test'",
    "Expose object time=100 basename='test/path'",
    "expose object time=100 basename=test comment=atest",
    "expose object time=100 basename=test comment='a comment with a test'",
    "expose object time=100 basename=test comment=\"a comment with a test\"",
    "exp obj tim=100 base=test comm=atest",
    "expose flat time=100",
    "expose flat time=100 basename=test",
    "expose flat time=100 basename=test/path",
    "expose flat time=100 basename='test'",
    "expose flat time=100 basename='test/path'",
    "expose flat time=100 basename=test comment=atest",
    "expose flat time=100 basename=test comment='a comment with a test'",
    "expose flat time=100 basename=test comment=\"a comment with a test\"",
    "expose pause",
    "expose resume",
    "expose stop",
    "expose abort",
    "camera status",
    "camera init",
    "filter status",
    "filter init",
    "filter home",
    "filter talk talk to camera text",
    "filter talk \"talk to camera text\"",
    "filter talk 'talk to camera text'",
    "init",
    "status",
]

class TestParser(unittest.TestCase):

    def testCommandList(self):
        for cmdStr in commandList:
            print "cmdStr: ", cmdStr
            parsedCommand = arcticCommandSet.parse(cmdStr)

    def testHTML(self):
        print(arcticCommandSet.toHTML())



if __name__ == "__main__":
    unittest.main()