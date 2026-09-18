# jev score: labels, --range, 11-level rejection without a request, -p.
from __future__ import annotations

from base import JevTestCase
from mock_server import MockDecisionsServer


class ScoreTests(JevTestCase):
    def test_labels_low_to_high(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["score", "q", "low", "mid", "high", "-s", "SCORE=1"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            value, label = proc.stdout.strip().split("\t")
            self.assertEqual(float(value), 1.0)
            self.assertEqual(label, "mid")

    def test_range_offsets_the_value(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["score", "q", "--range", "1-5", "-s", "SCORE=2"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            value, label = proc.stdout.strip().split("\t")
            self.assertEqual(float(value), 3.0)
            self.assertEqual(label, "3")

    def test_eleven_labels_rejected_without_a_request(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            labels = [f"l{i}" for i in range(11)]
            proc = self.run_jev(["score", "q", *labels, "-s", "x"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("2-10", proc.stderr)
            self.assertEqual(mock.request_count, 0)

    def test_range_producing_eleven_levels_rejected_without_a_request(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["score", "q", "--range", "1-11", "-s", "x"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(mock.request_count, 0)

    def test_range_and_labels_together_is_a_client_error(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["score", "q", "a", "b", "--range", "1-5", "-s", "x"], env=env
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(mock.request_count, 0)

    def test_probs_flag_prints_every_level(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["score", "q", "low", "mid", "high", "-s", "SCORE=0", "-p"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = proc.stdout.strip().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].split("\t")[0], "low")


if __name__ == "__main__":
    import unittest

    unittest.main()
