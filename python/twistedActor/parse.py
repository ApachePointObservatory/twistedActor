from __future__ import division, absolute_import

import sys

import pyparsing as pp

import RO.Alg.MatchList as MatchList
from RO.SeqUtil import isSequence#, isString
from RO.StringUtil import unquoteStr

"""@todo:
pretty printing __str__, __repr__
help strings, self documentation
support comments?
support brackets around list?
add qualifier indicator
"""
class INF(int):
    def __str__(self):
        return "parse.INF"
    def __repr__(self):
        return "parse.INF"

inf = INF(sys.maxint)

class CommandDefinitionError(Exception):
    pass

class ParseError(Exception):
    pass

class PyparseItems(object):

    @property
    def _word(self):
        return pp.Word(pp.alphas + pp.alphanums, pp.alphas + '_:.' + pp.alphanums)

    @property
    def float(self):
        # set up a float, allow scientific notation
        point = pp.Literal( "." )
        e     = pp.CaselessLiteral( "E" )
        ppFloat = pp.Combine( pp.Word( "+-"+pp.nums, pp.nums ) +
            pp.Optional( point + pp.Optional( pp.Word( pp.nums ) ) ) +
            pp.Optional( e + pp.Word( "+-"+pp.nums, pp.nums ) ) )
        def onParse(token):
            return float(token[0])
        ppFloat.setParseAction(onParse)
        return ppFloat

    @property
    def int(self):
        def onParse(token):
            return int(token[0])
        return pp.Word(pp.nums).setParseAction(onParse)

    @property
    def restOfLine(self):
        def onParse(token):
            return str(token[0])
        return pp.restOfLine.setParseAction(onParse)

    @property
    def string(self):
        def onParse(token):
            return str(token[0])
        return self.quotedStr ^ pp.Word(pp.alphanums + "/:.-").setParseAction(onParse)

    @property
    def quotedStr(self):
        def onParse(token):
            return unquoteStr(token[0])
        return pp.quotedString.setParseAction(onParse)

    @property
    def word(self):
        def onParse(tolken):
            return str(tolken[0])
        return self._word.setParseAction(onParse)

    def uniqueMatch(self, matchList):
        """matchList: A RO MatchList object
        """
        matchList = MatchList(matchList)
        def onParse(tolken):
            kw = str(tolken[0])
            # see if keyword is in list, else raise a parse error
            try:
                fullKW = matchList.getUniqueMatch(kw)
            except ValueError:
                raise ParseError("%s not uniquely defined in %s"%(kw, str(matchList.valueList)))
            return fullKW
        return self._word.setParseAction(onParse)

    # def keyVal(self, keyword, ppVal):
    #     """ keyword: string
    #         ppVal: a fully defined pyparsing element
    #     """
    #     kw = keyword.lower()
    #     kw = pp.Literal(keyword) + pp.Literal("=") + ppVal

    @property
    def extractKeys(self):
        datum = self.int ^ self.word ^ self.string ^ self.quotedStr ^ self.float
        # only extract any keywords where keyword=valueList, ignore everything else
        return pp.ZeroOrMore( self.word + pp.Suppress(pp.Literal("=")) + pp.Suppress(self.list(datum)) ^ pp.Suppress(self.list(datum)))


    def list(self, ppVal):
        return pp.Suppress(pp.Optional(pp.Literal("(")^pp.Literal("["))) + pp.delimitedList(ppVal) + pp.Suppress(pp.Optional(pp.Literal("]")^pp.Literal(")")))

pyparseItems = PyparseItems()

class ArgumentBase(object):

    def __init__(self, pyparseItem, nElements=1, helpStr="", name=""):
        """@param[in] nElements: an integer in [1,parse.INF] or an ascending 2 element sequence of integers each in [0, parse.INF].
        """
        self.name = name if name else "arg"
        self.helpStr = helpStr
        # verify that nElements is in a useable format
        self.lowerBound, self.upperBound = self.getBounds(nElements)
        self.pyparseItem = pp.delimitedList(pyparseItem) + pp.Optional(pp.Suppress(pp.Literal("]")))
        # allow brackets or parentheses if this is a list
        if self.upperBound > 1:
            self.pyparseItem = pp.Suppress(pp.Optional(pp.Literal("(")^pp.Literal("["))) + self.pyparseItem + pp.Suppress(pp.Optional(pp.Literal("]")^pp.Literal(")")))


    def getBounds(self, nElements):
        if isSequence(nElements):
            if len(nElements) != 2:
                raise CommandDefinitionError("nElements must be either integer or sequence of 2 integers")
            # verify, try to cast to correct types
            nElements = list(nElements) # make it mutable (incase of tuple)
            for ind in range(2):
                nElements[ind] = self.checkInt(nElements[ind])
            if nElements[1] < nElements[0]:
                raise CommandDefinitionError("nElements[1] must be greater than nElements[0]")
            if nElements[0]==nElements[1]==int(0):
                raise CommandDefinitionError("may not specifiy nElement=(0,0)")
            if nElements[0]==inf:
                raise CommandDefinitionError("may not specify infinite lower bound for nElements")
            if True in [element<0 for element in nElements]:
                raise CommandDefinitionError("may not specify any negative value in nElements")
            lowerBound, upperBound = nElements
        else:
            # not a sequence, we expect an exact amount of values for this argument
            nElements = self.checkInt(nElements)
            if nElements <= 0:
                raise CommandDefinitionError("may not specify nElement<=0")
            if nElements == inf:
                raise CommandDefinitionError("may not specify nElement=inf, use range (lowerbound ,inf) instead")
            # set upper and lower bounds equal
            lowerBound, upperBound = [nElements]*2
        return lowerBound, upperBound

    def checkInt(self, possibleInt):
        # isinstance used incase of my custom INF subclass of int
        # to avoid recasting back to an int
        if not isinstance(possibleInt, int):
            try:
                possibleInt = int(possibleInt)
            except:
                raise CommandDefinitionError("could not cast possibleInt = %s to integer"%(possibleInt))
        return possibleInt

    def scanString(self, stringToSearch):
        # scanString returns a generator, it should be of length 1, call next to get it.
        # returns a pyparsing ParseResult and beg/end positions of the match
        scanGenerator = self.pyparseItem.scanString(stringToSearch)
        pyparseResultObj, begPos, endPos = scanGenerator.next()
        # verify that this was a unique match (shouldn't have found more than one)
        try:
            scanGenerator.next()
        except StopIteration:
            # this is expected
            pass
        else:
            raise ParseError("scanString found more than one match for arg: %s in string: %s"%(self.name, stringToSearch))
        values = pyparseResultObj.asList()
        if not self.lowerBound <= len(values)<=self.upperBound:
            raise ParseError("expected between %i and %i values for %s, received: %i"%(self.lowerBound, self.upperBound, self.name, len(values)))
        return values, (begPos, endPos)

class Float(ArgumentBase):
    def __init__(self, nElements=1, helpStr=""):
        ArgumentBase.__init__(self, pyparseItems.float, nElements, helpStr)

class Int(ArgumentBase):
    def __init__(self, nElements=1, helpStr=""):
        ArgumentBase.__init__(self, pyparseItems.int, nElements, helpStr)

class String(ArgumentBase):
    def __init__(self, nElements=1, helpStr=""):
        ArgumentBase.__init__(self, pyparseItems.string, nElements, helpStr)

class RestOfLineString(ArgumentBase):
    def __init__(self, helpStr=""):
        ArgumentBase.__init__(self, pyparseItems.restOfLine, nElements=1, helpStr=helpStr)

class Keyword(ArgumentBase):
    def __init__(self, keyword, nElements=1, helpStr=""):
        self.keyword = keyword
        ArgumentBase.__init__(self, pyparseItems.word, nElements, helpStr)

class KeywordValue(Keyword):
    def __init__(self, keyword, value, isMandatory=True, helpStr=""):
        """keyword: string
        value: must be of type ArgumentBase
        """
        self.helpStr = helpStr
        self.isMandatory = isMandatory
        self.lowerBound = value.lowerBound
        self.upperBound = value.upperBound
        self._parsedAbbreviation = None
        # keywords may either appear once or not at all
        if not isinstance(value, ArgumentBase):
            raise CommandDefinitionError("value must be of type ArgumentBase in KeywordValue.")
        self.value = value
        self.keyword = keyword

    @property
    def name(self):
        return self.keyword

    @property
    def parsedAbbreviation(self):
        return self._parsedAbbreviation

    def setParseAbbreviation(self, abbreviation):
        self._parsedAbbreviation = abbreviation

    @property
    def pyparseItem(self):
        return pp.Suppress(pp.Literal(self.parsedAbbreviation)) + pp.Suppress(pp.Literal("=")) + self.value.pyparseItem

class UniqueMatch(ArgumentBase):
    def __init__(self, matchList, nElements=1, helpStr=""):
        if not isSequence(matchList):
            raise CommandDefinitionError("matchlist must be a sequence")
        ArgumentBase.__init__(self, pyparseItems.uniqueMatch(matchList), nElements, helpStr)

class CommandSet(object):
    def __init__(self, commandList):
        """! Generate a command set
        @param[in] commandList: a list of Command objects
        """
        # turn list of commands into a dictionary
        self.commandDict = {}
        for command in commandList:
            self.commandDict[command.commandName] = command
        self.createHelpCmd()
        self.commandMatchList = MatchList(valueList = self.commandDict.keys())
        # explicitly set the "help command"

    def createHelpCmd(self):
        """Create a help command add it to the command dict.
        """
        helpCmd = Command(
            commandName = "help",
            positionalArguments = [UniqueMatch(self.commandDict.keys(), nElements=(0,1))],
            helpStr="print help for a command or the whole command set"
        )
        self.commandDict[helpCmd.commandName] = helpCmd

    def getCommand(self, cmdName):
        """! Get a command in the set from a command name. Name may be abbreviated
        as long as it is unique to the command set.
        """
        return self.commandDict[self.commandMatchList.getUniqueMatch(cmdName)]

    def parse(self, cmdStr):
        """! Parse a command string.

        @param[in] cmdStr, the command string to be parsed
        @return ParsedCommand object
        """
        # use pyparsing instead? any advantage?
        # determine which command we are parsing
        try:
            cmdName, cmdArgs = cmdStr.split(" ", 1)
        except ValueError:
            # split didn't work (need more than one value to unpack)
            # means that no cmdArgs were passed!
            cmdName = cmdStr
            cmdArgs = ""
        cmdName = cmdName.strip()
        cmdArgs = cmdArgs.strip()
        cmdObj = self.getCommand(cmdName) # cmdName abbreviations allowed!
        return cmdObj.parse(cmdArgs)

class ArgumentSet(object):
    def __init__(self, argumentList):
        self.pyparseItem = pp.Empty() # build a pyparsing representation
        for arg in argumentList:
            if not isinstance(arg, ArgumentBase):
                raise CommandDefinitionError("argument %s must be of type ArgumentBase"%arg)
            self.pyparseItem += arg.pyparseItem
        self.argumentList = argumentList

    def parse(self, argString):
        """@param[in] argString: a string containing arguments to be parsed
        order matters.  If the string isn't completely consume raise ParseError
        """
        if not argString:
            # empty string, are there mandatory positional args?
            if True in [arg.lowerBound>0 for arg in self.argumentList]:
                raise ParseError("Mandatory positional arguments not found: %s"%", ".join(str(arg) for arg in self.argumentList if arg.lowerBound>0))
            # no positional args passed, and no positinal args mandatory...
            return []
        try:
            ppOut = self.pyparseItem.parseString(argString, parseAll=True).asList()
            assert len(ppOut)==1
        except:
            raise ParseError("could not parse positional args: %s"%argString)
        return ppOut

    def __nonzero__(self):
        return bool(self.argumentList)

class FloatingArgumentSet(ArgumentSet):
    def __init__(self, floatingArguments):
        # turn list of commands into a dictionary
        # floating Arguments must be of Keyword type
        self.floatingArgDict = {}
        self.appendArguments(floatingArguments)

    def __nonzero__(self):
        return bool(self.floatingArgDict)

    def appendArguments(self, floatingArguments):
        "note any duplicated arguments will be over written."
        for arg in floatingArguments:
            if not isinstance(arg, Keyword):
                raise CommandDefinitionError("argument %s must be of type Keyword"%arg)
        for arg in floatingArguments:
            self.floatingArgDict[arg.keyword] = arg

    @property
    def argMatchList(self):
        return MatchList(valueList = self.floatingArgDict.keys())

    def parse(self, argString):
        """@param[in] argString: a string containing keyword-type arguments to be
        parsed
        @ raise ParseError if mandatory keyword not present, or unknown keyword is present.
        @ return tuple of parsedArguments and a string containing uncomsumed/unparsed elements
        """
        # figure out which keywords we got, abbreviations allowed!
        gotKeys = set()
        # searchString returns ParseResult
        try:
            abbrevKWs = pyparseItems.extractKeys.searchString(argString)[0]
        except IndexError:
            # found no keywords
            abbrevKWs = []
        for abbrevKW in abbrevKWs:
            try:
                keyword = self.argMatchList.getUniqueMatch(abbrevKW)
                gotKeys.add(keyword)
                # associate this (potentially) abbreviated keyword with this argument
                self.floatingArgDict[keyword].setParseAbbreviation(abbrevKW)
            except:
                raise ParseError("Could not identify keyword %s, as one of %s"%(abbrevKW, self.floatingArgDict.keys()))
        # determine which keywords were not received
        missingKeys = set(self.floatingArgDict.keys()) - gotKeys
        # ensure that any missing keys were optional arguments
        # else raise a ParseError
        for key in missingKeys:
            if self.floatingArgDict[key].isMandatory:
                raise ParseError("Mandatory keyword argument: %s not specified"%key)
        # next parse values associated with the present keys
        parsedDict = {}
        stringPosList = []
        for key in gotKeys:
            parsedDict[key], begEndPos = self.floatingArgDict[key].scanString(argString)
            stringPosList.append(begEndPos)
        # based on beginning/end match positions in argString, prune string
        # such that it contains only pieces not yet parsed that is
        # only string characters not in any of the ranges collected by
        # stringPosList
        prunedString = ""
        # look for possible way to speed up
        # eg numpy indexing
        # or operator.itemgetter?
        for ind, char in enumerate(argString):
            if not True in [beg<=ind<end for beg,end in stringPosList]:
                prunedString += char
        # ditch surrounding whitespace, even though innocous
        prunedString = prunedString.strip()
        return parsedDict, prunedString


class Command(object):
    def __init__(self,
        commandName,
        subCommandList=None,
        positionalArguments=None,
        floatingArguments=None,
        helpStr="",
        ):
        """Command may only be a keyword with arguments or subcommands, no value.
        """
        if subCommandList:
            if positionalArguments:
                raise CommandDefinitionError("May not specify subCommandList AND positionalArguments")
            if floatingArguments:
                # floatingArguments should be transferred to every command in subcommand list
                for command in subCommandList:
                    # note these may overwrite any defined explicitly in subcommand
                    command.floatingArgumentSet.appendArguments(floatingArguments)
                floatingArguments = None
            self.subCommandSet = CommandSet(subCommandList)
        else:
            self.subCommandSet = None
        self.commandName = commandName
        self.positionalArgumentSet = ArgumentSet(positionalArguments or [])
        self.floatingArgumentSet = FloatingArgumentSet(floatingArguments or [])
        self.helpStr=helpStr

    def parse(self, argString):
        """! parse a raw command string
        @param[in] argString, string to be parsed.
        """
        # first, look for subcommands.

        parsedCommand = ParsedCommand(self.commandName)
        if self.subCommandSet:
            # parse the remaining argument string just like a full command
            parsedCommand.setSubCommand(self.subCommandSet.parse(argString))
        else:
            # look for floating arguments of type keyword=value in order
            # overwrite argString (remove the key=values after they have been parsed)
            # note if no floating arguments are found, the argString is unmodified
            parsedFloatingArgs, argString = self.floatingArgumentSet.parse(argString)
            parsedCommand.setParsedFloatingArgs(parsedFloatingArgs)
            # then parse positional arguments
            parsedCommand.setParsedPositionalArgs(self.positionalArgumentSet.parse(argString))
        return parsedCommand


class ParsedCommand(object):

    def __init__(self, cmdName):
        self.cmdName = cmdName
        self.subCommand = None
        self.parsedPositionalArgs = None
        self.parsedFloatingArgs = None

    def setSubCommand(self, parsedCmd):
        self.subCommand = parsedCmd

    def setParsedFloatingArgs(self, parsedFloatingArgs):
        self.parsedFloatingArgs = parsedFloatingArgs

    def setParsedPositionalArgs(self, parsedPositionalArgs):
        self.parsedPositionalArgs = parsedPositionalArgs













