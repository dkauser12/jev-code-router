# jev run: spec listing, each built-in JSON spec, a custom spec in the temp
# config dir; and jev raw.
from __future__ import annotations

import json

from base import JevTestCase
from mock_server import MockDecisionsServer

BUILTIN_QUESTIONS = {
    "mail": {"category", "urgency", "needs_reply", "is_promo"},
    "feedback": {"intent", "sentiment", "needs_human", "churn_risk"},
    "signal": {"worth_reading", "topic", "novelty"},
    "commit": {"type", "has_secret", "breaking", "risk"},
    "route": {"handler", "complexity", "needs_web", "needs_private_data"},
    "code-route": {"decision"},
    "code-context": {"selected"},
    "code-escalate": {"decision"},
}


class RunListingTests(JevTestCase):
    def test_lists_only_builtins_when_no_custom_specs(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            names = {line.split("\t")[0] for line in proc.stdout.strip().splitlines()}
            self.assertEqual(names, set(BUILTIN_QUESTIONS))
            self.assertEqual(mock.request_count, 0)

    def test_custom_spec_appears_alongside_builtins(self):
        spec = {
            "description": "custom test spec",
            "questions": {"ok": {"type": "noul", "instructions": "is it ok"}},
        }
        (self.user_specs_dir() / "custom.json").write_text(
            json.dumps(spec), encoding="utf-8"
        )
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            names = {line.split("\t")[0] for line in proc.stdout.strip().splitlines()}
            self.assertEqual(names, set(BUILTIN_QUESTIONS) | {"custom"})


class RunBuiltinTests(JevTestCase):
    def test_every_builtin_spec_runs(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            for name, expected_questions in BUILTIN_QUESTIONS.items():
                proc = self.run_jev(
                    ["run", name, "-s", "YES case CHOICE=x SCORE=0", "--json"], env=env
                )
                self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")
                out = json.loads(proc.stdout)
                self.assertEqual(set(out["answers"]), expected_questions, name)

    def test_plain_table_output_has_one_row_per_question(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run", "mail", "-s", "some email text"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = proc.stdout.strip().splitlines()
            self.assertEqual(len(rows), len(BUILTIN_QUESTIONS["mail"]))


class RunCustomSpecTests(JevTestCase):
    def test_custom_spec_runs_from_config_dir(self):
        spec = {
            "description": "custom test spec",
            "threshold": 0.5,
            "questions": {
                "urgent": {
                    "type": "noul",
                    "instructions": "is this urgent",
                    "criteria": {"true": "urgent", "false": "not urgent"},
                }
            },
        }
        (self.user_specs_dir() / "custom.json").write_text(
            json.dumps(spec), encoding="utf-8"
        )
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run", "custom", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertTrue(out["answers"]["urgent"]["yes"])

    def test_one_sided_noul_criteria_rejected_before_request(self):
        spec = {
            "description": "one-sided noul criteria",
            "questions": {
                "urgent": {
                    "type": "noul",
                    "instructions": "is this urgent",
                    "criteria": {"true": "urgent"},
                }
            },
        }
        (self.user_specs_dir() / "onesided.json").write_text(
            json.dumps(spec), encoding="utf-8"
        )
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run", "onesided", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("true 和 false", proc.stderr)
            self.assertEqual(mock.request_count, 0)

    def test_unknown_question_keys_rejected_with_criteria_hint(self):
        # Yes/no descriptions placed beside instructions instead of inside
        # criteria used to be dropped silently; they must now fail loudly.
        spec = {
            "description": "misplaced noul descriptions",
            "questions": {
                "urgent": {
                    "type": "noul",
                    "instructions": "is this urgent",
                    "true": {"value": "urgent"},
                    "false": {"value": "not urgent"},
                }
            },
        }
        (self.user_specs_dir() / "misplaced.json").write_text(
            json.dumps(spec), encoding="utf-8"
        )
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run", "misplaced", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("未知字段 false, true", proc.stderr)
            self.assertIn("criteria", proc.stderr)
            self.assertEqual(mock.request_count, 0)


    def test_score_criteria_written_as_a_map_gets_a_shape_error(self):
        spec = {
            "description": "score criteria as a map",
            "questions": {
                "novelty": {
                    "type": "score",
                    "instructions": "how novel",
                    "criteria": {"low": "old news", "mid": "some", "high": "first"},
                }
            },
        }
        (self.user_specs_dir() / "scoremap.json").write_text(json.dumps(spec), encoding="utf-8")
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["run", "scoremap", "-s", "SCORE=1"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("必须是数组", proc.stderr)
            self.assertNotIn("2-10", proc.stderr)
            self.assertEqual(mock.request_count, 0)

class RawTests(JevTestCase):
    def test_raw_echoes_api_response(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            body = json.dumps(
                {
                    "model": "typesafe/jev-latest",
                    "state": "YES case",
                    "questions": {"answer": {"type": "noul", "instructions": "q?"}},
                }
            )
            proc = self.run_jev(["raw"], input=body, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["answers"]["answer"]["noul"], 0.9)

    def test_raw_requires_stdin_body(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["raw"], input="", env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(mock.request_count, 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
