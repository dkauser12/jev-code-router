# jev filter: semantic grep -- -v, --with-prob, exit codes, partial output on error.
from __future__ import annotations

from base import JevTestCase
from mock_server import MockDecisionsServer


class FilterTests(JevTestCase):
    def test_matching_lines_pass_through(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            text = "YES keep me\nNO drop me\nYES keep me too\n"
            proc = self.run_jev(["filter", "q"], input=text, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.splitlines(), ["YES keep me", "YES keep me too"])

    def test_invert_prints_non_matching_lines(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            text = "YES keep me\nNO drop me\n"
            proc = self.run_jev(["filter", "q", "-v"], input=text, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.splitlines(), ["NO drop me"])

    def test_with_prob_prefixes_probability(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["filter", "q", "--with-prob"], input="YES line\n", env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "0.90\tYES line")

    def test_no_matches_exits_1(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["filter", "q"], input="NO one\nNO two\n", env=env)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout, "")

    def test_error_on_one_line_exits_2_but_prints_matches_found(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            text = "YES first\nTRIGGER_PLAIN_ERROR\nYES second\n"
            proc = self.run_jev(["filter", "q"], input=text, env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout.splitlines(), ["YES first", "YES second"])
            self.assertIn("Something went wrong", proc.stderr)


if __name__ == "__main__":
    import unittest

    unittest.main()
