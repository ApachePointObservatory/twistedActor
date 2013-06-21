"""Ensure that command.LinkCommands works correctly
"""
import unittest

from twistedActor import LinkCommands, BaseCmd

class TestLinker(unittest.TestCase):
    def setUp(self):
        # all commands are initialized in ready state
        self.subCmdList = []
        for ind in range(5):
            self.subCmdList.append(BaseCmd('subCmd'+str(ind)))
        self.mainCmd = BaseCmd('main')
        LinkCommands(self.mainCmd, self.subCmdList)
        
    def testPass(self):
        # pass all subcommands
        for cmd in self.subCmdList:
            cmd.setState("done")
        self.assertTrue(self.mainCmd.state=="done")
    
    def testFail(self):
        for ind, cmd in enumerate(self.subCmdList):
            if ind == 2:
                cmd.setState("failed")
            else:
                cmd.setState("done")
        self.assertTrue(self.mainCmd.state=="failed")

    def testCancel(self):
        # fail a single subcommand
        for ind, cmd in enumerate(self.subCmdList):
            if ind == 2:
                cmd.setState("cancelled")
            else:
                cmd.setState("done")
        self.assertTrue(self.mainCmd.state=="failed")   
             

if __name__ == "__main__":
    unittest.main()