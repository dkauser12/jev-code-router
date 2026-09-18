# jev yes: exit codes, --quiet, --true/--false, threshold.
from __future__ import annotations

from base import JevTestCase
from mock_server import MockDecisionsServer


class YesTests(JevTestCase):
    def test_yes_exit_0_and_plain_output(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "是否是问题", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "yes\t0.90")

    def test_no_exit_1(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "是否是问题", "-s", "NO case"], env=env)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout.strip(), "no\t0.10")

    def test_quiet_suppresses_stdout_but_keeps_exit_code(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--quiet"], env=env)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")

            proc = self.run_jev(["yes", "q", "-s", "NO case", "--quiet"], env=env)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout, "")

    def test_true_false_are_sent_as_criteria(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["yes", "q", "-s", "YES case", "--true", "是紧急情况", "--false", "是常规情况"],
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = mock.requests[-1]["body"]
            self.assertEqual(
                body["questions"]["answer"]["criteria"],
                {"true": "是紧急情况", "false": "是常规情况"},
            )

    def test_threshold_moves_the_cutoff(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            # canned p=0.90 for "YES case"; -t 0.95 pushes it below the cutoff.
            proc = self.run_jev(["yes", "q", "-s", "YES case", "-t", "0.95"], env=env)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout.strip(), "no\t0.90")

    def test_json_output_has_enriched_answer(self):
        import json

        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertTrue(out["answer"]["yes"])
            self.assertAlmostEqual(out["answer"]["noul"], 0.9)


if __name__ == "__main__":
    import unittest

    unittest.main()
