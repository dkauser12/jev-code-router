# jev pick: plain output, -p, --other, --json, --min-confidence.
from __future__ import annotations

import json

from base import JevTestCase
from mock_server import MockDecisionsServer


class PickTests(JevTestCase):
    def test_plain_output_is_the_chosen_option(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["pick", "q", "bug=崩溃", "feature=功能请求", "-s", "CHOICE=feature"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "feature")

    def test_other_option_can_be_chosen(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["pick", "q", "a=A", "b=B", "--other", "-s", "CHOICE=other"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "other")
            body = mock.requests[-1]["body"]
            self.assertEqual(
                body["questions"]["answer"]["criteria"]["other"], "以上选项都不符合"
            )

    def test_probs_flag_prints_full_distribution_desc(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["pick", "q", "a=A", "b=B", "-s", "CHOICE=a", "-p"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = proc.stdout.strip().splitlines()
            self.assertEqual(lines[0].split("\t")[0], "a")
            self.assertEqual(lines[1].split("\t")[0], "b")
            pa = float(lines[0].split("\t")[1])
            pb = float(lines[1].split("\t")[1])
            self.assertGreaterEqual(pa, pb)

    def test_json_output(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["pick", "q", "a=A", "b=B", "-s", "CHOICE=a", "--json"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["answer"]["choice"], "a")
            self.assertIn("probabilities", out["answer"])

    def test_min_confidence_below_threshold_exits_1(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            # chosen option confidence is 0.8 for a 2-way pick; 0.95 is out of reach.
            proc = self.run_jev(
                ["pick", "q", "a=A", "b=B", "-s", "CHOICE=a", "--min-confidence", "0.95"],
                env=env,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout.strip(), "a")

    def test_min_confidence_met_exits_0(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["pick", "q", "a=A", "b=B", "-s", "CHOICE=a", "--min-confidence", "0.5"],
                env=env,
            )
            self.assertEqual(proc.returncode, 0)

    def test_requires_at_least_two_options(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["pick", "q", "a=A", "-s", "x"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(mock.request_count, 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
