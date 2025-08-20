import unittest
from click.testing import CliRunner
from localpkg.main import cli


class TestCLI(unittest.TestCase):
    def test_help(self):
        res = CliRunner().invoke(cli, ["--help"])
        self.assertEqual(0, res.exit_code)
        if res.exception:
            raise res.exception
        self.assertIn("apk", res.output)
        self.assertIn("deb", res.output)
        self.assertIn("rpm", res.output)
        self.assertIn("tar", res.output)
