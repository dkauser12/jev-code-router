# Multi-provider behavior (TypeSafe native default, OpenRouter alternative).
#
# Split in two styles:
#   - pure-function unit tests, loading jev/scripts/jev as a module (no
#     subprocess, no network) for normalize_model/resolve_model/
#     format_api_error/_extract_model_names/provider_headers;
#   - full CLI subprocess tests against the mock server's native + OpenRouter
#     routes, for provider resolution, headers on the wire, --json/--verbose
#     output, and native error/retry handling end to end.
#
# The native mock routes' missing-Authorization -> 403 case can't be
# triggered through a full CLI run (jev always sends an Authorization header
# once a key is resolved), so it's checked directly against the mock server
# with a bare urllib request instead -- this also documents the exact body
# shape observed against the live API per the task's research.
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import unittest
import urllib.error
import urllib.request

from base import JevTestCase, JEV_CLI
from mock_server import DEFAULT_NATIVE_MODELS, MockDecisionsServer


def _load_cli_module():
    # jev/scripts/jev has no .py suffix, so spec_from_file_location can't
    # infer a loader from the extension -- force SourceFileLoader explicitly.
    loader = importlib.machinery.SourceFileLoader("jev_cli_under_test", str(JEV_CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


jev_cli = _load_cli_module()


class ModelNormalizationTests(unittest.TestCase):
    def test_native_strips_tilde_and_typesafe_prefix(self):
        self.assertEqual(jev_cli.normalize_model("~typesafe/jev-latest", "typesafe"), "jev-latest")
        self.assertEqual(jev_cli.normalize_model("jev-latest", "typesafe"), "jev-latest")

    def test_native_appends_patch_zero_to_a_short_versioned_id(self):
        # Verified live: native only accepts jev-1.13.0 (three segments);
        # jev-1.13 and typesafe/jev-1.13 are both "Unknown model" there.
        self.assertEqual(jev_cli.normalize_model("jev-1.13", "typesafe"), "jev-1.13.0")
        self.assertEqual(jev_cli.normalize_model("typesafe/jev-1.13", "typesafe"), "jev-1.13.0")
        self.assertEqual(jev_cli.normalize_model("~typesafe/jev-1.13", "typesafe"), "jev-1.13.0")

    def test_openrouter_maps_bare_aliases(self):
        self.assertEqual(jev_cli.normalize_model("jev-latest", "openrouter"), "~typesafe/jev-latest")
        self.assertEqual(jev_cli.normalize_model("jev-preview", "openrouter"), "~typesafe/jev-preview")

    def test_openrouter_drops_patch_zero_from_a_bare_versioned_id(self):
        # OpenRouter's own versioned id has no patch segment (typesafe/jev-1.13).
        self.assertEqual(jev_cli.normalize_model("jev-1.13.0", "openrouter"), "typesafe/jev-1.13")

    def test_openrouter_prefixes_other_bare_models_unchanged(self):
        self.assertEqual(jev_cli.normalize_model("jev-1.13.1", "openrouter"), "typesafe/jev-1.13.1")

    def test_openrouter_leaves_slashed_models_alone(self):
        self.assertEqual(jev_cli.normalize_model("typesafe/jev-1.13", "openrouter"), "typesafe/jev-1.13")
        self.assertEqual(jev_cli.normalize_model("~typesafe/jev-latest", "openrouter"), "~typesafe/jev-latest")

    def test_resolve_model_precedence(self):
        self.assertEqual(
            jev_cli.resolve_model("jev-preview", "typesafe", spec_model="jev-latest"), "jev-preview"
        )
        self.assertEqual(jev_cli.resolve_model(None, "typesafe", spec_model="jev-preview"), "jev-preview")
        self.assertEqual(jev_cli.resolve_model(None, "typesafe", spec_model=None), "jev-latest")
        self.assertEqual(jev_cli.resolve_model(None, "openrouter", spec_model=None), "~typesafe/jev-latest")

    def test_resolve_model_reads_jev_model_env_below_arg_and_spec(self):
        old = os.environ.get("JEV_MODEL")
        os.environ["JEV_MODEL"] = "jev-preview"
        try:
            self.assertEqual(jev_cli.resolve_model(None, "typesafe", spec_model=None), "jev-preview")
            self.assertEqual(jev_cli.resolve_model("jev-latest", "typesafe", spec_model=None), "jev-latest")
        finally:
            if old is None:
                os.environ.pop("JEV_MODEL", None)
            else:
                os.environ["JEV_MODEL"] = old


class FormatApiErrorTests(unittest.TestCase):
    def test_native_dict_detail(self):
        body = json.dumps({"detail": {"message": "Bad thing"}})
        text = jev_cli.format_api_error(422, body, provider="typesafe")
        self.assertIn("API 错误 (HTTP 422)", text)
        self.assertIn("Bad thing", text)

    def test_native_fastapi_list_detail(self):
        body = json.dumps({"detail": [{"loc": ["body", "state"], "msg": "field required"}]})
        text = jev_cli.format_api_error(422, body, provider="typesafe")
        self.assertIn("body.state: field required", text)

    def test_native_string_detail(self):
        body = json.dumps({"detail": "nope"})
        text = jev_cli.format_api_error(400, body, provider="typesafe")
        self.assertIn("nope", text)

    def test_native_401_and_403_hint_at_auth_set(self):
        body = json.dumps({"detail": {"message": "bad key"}})
        for status in (401, 403):
            text = jev_cli.format_api_error(status, body, provider="typesafe")
            self.assertIn(f"HTTP {status}", text)
            self.assertIn("jev auth set", text)
            self.assertNotIn("--provider", text)  # typesafe is the default, no suffix

    def test_openrouter_401_hint_mentions_provider_flag(self):
        body = json.dumps({"error": {"message": "No auth credentials found"}})
        text = jev_cli.format_api_error(401, body, provider="openrouter")
        self.assertIn("OPENROUTER_API_KEY", text)
        self.assertIn("jev auth set --provider openrouter", text)

    def test_openrouter_zod_shape_unaffected_by_native_branch(self):
        body = json.dumps({"error": {"message": json.dumps([{"path": ["model"], "message": "Required"}])}})
        text = jev_cli.format_api_error(400, body, provider="openrouter")
        self.assertIn("model: Required", text)


class ExtractModelNamesTests(unittest.TestCase):
    def test_plain_list_of_strings(self):
        self.assertEqual(jev_cli._extract_model_names(["a", "b"]), ["a", "b"])

    def test_data_key_with_objects(self):
        payload = {"data": [{"id": "jev-latest"}, {"name": "jev-preview"}]}
        self.assertEqual(jev_cli._extract_model_names(payload), ["jev-latest", "jev-preview"])

    def test_models_key(self):
        self.assertEqual(jev_cli._extract_model_names({"models": ["x"]}), ["x"])

    def test_unrecognized_shape_returns_empty(self):
        self.assertEqual(jev_cli._extract_model_names({"nope": 1}), [])
        self.assertEqual(jev_cli._extract_model_names("not even a container"), [])


class ProviderHeaderTests(unittest.TestCase):
    def test_native_has_user_agent_but_no_attribution_headers(self):
        h = jev_cli.provider_headers("typesafe", "k", content_type=True)
        self.assertNotIn("X-Title", h)
        self.assertNotIn("HTTP-Referer", h)
        self.assertTrue(h["User-Agent"].startswith("jev-cli/"))
        self.assertEqual(h["Authorization"], "Bearer k")

    def test_openrouter_has_attribution_headers(self):
        h = jev_cli.provider_headers("openrouter", "k", content_type=True)
        self.assertEqual(h["X-Title"], "jev-cli")
        self.assertEqual(h["HTTP-Referer"], "https://github.com/okooo5km/jev")
        self.assertTrue(h["User-Agent"].startswith("jev-cli/"))


class EstimateCostTests(unittest.TestCase):
    def test_native_estimates_from_price_table(self):
        cost = jev_cli.estimate_cost("typesafe", 1_000_000)
        self.assertAlmostEqual(cost, 0.042)

    def test_openrouter_has_no_estimate(self):
        self.assertIsNone(jev_cli.estimate_cost("openrouter", 1_000_000))


class NativeMockFidelityTests(JevTestCase):
    """Confirms the mock's native routes match the exact bodies observed
    against the live API (see the task's research notes), for the one case
    (missing Authorization entirely) the CLI itself can never produce."""

    def test_decisions_missing_authorization_is_403(self):
        with MockDecisionsServer() as mock:
            req = urllib.request.Request(
                mock.native_base_url,
                data=json.dumps({"model": "jev-latest", "state": "x", "questions": {}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(ctx.exception.code, 403)
                body = json.loads(ctx.exception.read().decode())
            finally:
                ctx.exception.close()
            self.assertEqual(body["detail"]["error_type"], "authentication_error")
            self.assertIn("Must supply an API key", body["detail"]["message"])

    def test_models_missing_authorization_is_403(self):
        with MockDecisionsServer() as mock:
            req = urllib.request.Request(mock.native_key_url, method="GET")
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(ctx.exception.code, 403)
            finally:
                ctx.exception.close()


class ProviderResolutionTests(JevTestCase):
    def test_auto_prefers_typesafe_when_both_keys_present(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "typesafe")
            self.assertIsNone(out["id"])

    def test_auto_uses_openrouter_when_only_that_key_present(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "openrouter")

    def test_auto_uses_typesafe_when_only_that_key_present(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "typesafe")

    def test_no_key_anywhere_exits_2_mentioning_auth_set_and_makes_no_request(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "x"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("jev auth set", proc.stderr)
            self.assertEqual(mock.request_count, 0)

    def test_explicit_provider_flag_overrides_auto(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["yes", "q", "-s", "YES case", "--provider", "openrouter", "--json"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "openrouter")

    def test_jev_provider_env_overrides_auto(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(TYPESAFE_API_KEY="ts-test",
                                 JEV_BASE_URL=mock.base_url, JEV_PROVIDER="openrouter")
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "openrouter")

    def test_pinned_provider_in_config_ini_overrides_auto(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.ini").write_text("[jev]\nprovider = openrouter\n", encoding="utf-8")
        with MockDecisionsServer() as mock:
            env = self.base_env(TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "openrouter")

    def test_jev_provider_line_inside_env_file_is_ignored(self):
        # .env holds secrets only; a stray JEV_PROVIDER= line in it must not
        # affect provider resolution (only the JEV_PROVIDER env var and
        # config.ini's [jev] provider do).
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text(
            "TYPESAFE_API_KEY=ts-test\nJEV_PROVIDER=openrouter\n", encoding="utf-8"
        )
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "typesafe")

    def test_invalid_provider_in_config_ini_exits_2(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.ini").write_text("[jev]\nprovider = bogus\n", encoding="utf-8")
        env = self.base_env()
        proc = self.run_jev(["yes", "q", "-s", "x"], env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("config.ini", proc.stderr)

    def test_explicit_provider_without_its_key_errors_naming_that_provider(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)  # no TYPESAFE_API_KEY
            proc = self.run_jev(["yes", "q", "-s", "x", "--provider", "typesafe"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("TYPESAFE_API_KEY", proc.stderr)
            self.assertIn("jev auth set", proc.stderr)
            self.assertEqual(mock.request_count, 0)

    def test_invalid_provider_name_via_flag_exits_2(self):
        env = self.base_env()
        proc = self.run_jev(["yes", "q", "-s", "x", "--provider", "bogus"], env=env)
        self.assertEqual(proc.returncode, 2)

    def test_invalid_jev_provider_env_value_exits_2(self):
        env = self.base_env(JEV_PROVIDER="bogus")
        proc = self.run_jev(["yes", "q", "-s", "x"], env=env)
        self.assertEqual(proc.returncode, 2)


class ModelNormalizationE2ETests(JevTestCase):
    def test_default_model_for_native(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.requests[-1]["body"]["model"], "jev-latest")

    def test_m_flag_alias_normalized_for_native(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "-m", "~typesafe/jev-latest"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.requests[-1]["body"]["model"], "jev-latest")

    def test_bare_alias_normalized_for_openrouter(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "-m", "jev-latest"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.requests[-1]["body"]["model"], "~typesafe/jev-latest")

    def test_spec_model_is_normalized_per_provider(self):
        spec = {
            "description": "custom",
            "model": "jev-preview",
            "questions": {"ok": {"type": "noul", "instructions": "is it ok"}},
        }
        (self.user_specs_dir() / "custom.json").write_text(json.dumps(spec), encoding="utf-8")
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["run", "custom", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.requests[-1]["body"]["model"], "jev-preview")


class HeaderPerProviderE2ETests(JevTestCase):
    def test_native_headers_have_user_agent_but_not_attribution(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            headers = mock.requests[-1]["headers"]
            self.assertTrue(headers.get("user-agent", "").startswith("jev-cli/"))
            self.assertNotIn("x-title", headers)
            self.assertNotIn("http-referer", headers)

    def test_openrouter_headers_have_all_three(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            headers = mock.requests[-1]["headers"]
            self.assertTrue(headers.get("user-agent", "").startswith("jev-cli/"))
            self.assertEqual(headers.get("x-title"), "jev-cli")
            self.assertEqual(headers.get("http-referer"), "https://github.com/okooo5km/jev")


class JsonOutputProviderTests(JevTestCase):
    def test_json_has_provider_and_null_id_for_native(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "typesafe")
            self.assertIsNone(out["id"])
            self.assertEqual(out["usage"], {"input_tokens": 50, "output_tokens": 5})

    def test_json_has_provider_for_openrouter(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["provider"], "openrouter")
            self.assertEqual(out["id"], "mock-decision-0")

    def test_raw_output_is_not_touched_with_a_provider_key(self):
        # raw prints the API's response verbatim; it must NOT gain a
        # "provider" key that the API itself never sent.
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            body = json.dumps({
                "model": "typesafe/jev-latest", "state": "YES case",
                "questions": {"answer": {"type": "noul", "instructions": "q?"}},
            })
            proc = self.run_jev(["raw"], input=body, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertNotIn("provider", out)


class VerboseOutputTests(JevTestCase):
    def test_verbose_shows_provider_and_estimated_cost_for_native(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--verbose"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("[jev] typesafe ·", proc.stderr)
            self.assertIn("≈$", proc.stderr)

    def test_verbose_shows_exact_cost_for_openrouter_without_approx_prefix(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--verbose"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("[jev] openrouter ·", proc.stderr)
            self.assertNotIn("≈$", proc.stderr)
            self.assertIn("$0.000020", proc.stderr)

    def test_line_mode_summary_shows_provider_and_estimate_marker(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(
                ["yes", "q", "-l", "--verbose"], input="YES a\nYES b\n", env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("[jev] typesafe ·", proc.stderr)
            self.assertIn("≈$", proc.stderr)


class NativeErrorShapeTests(JevTestCase):
    def test_422_fastapi_list_detail(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "TRIGGER_NATIVE_422_LIST"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("API 错误 (HTTP 422)", proc.stderr)
            self.assertIn("body.questions.q.choice.criteria: Field required", proc.stderr)

    def test_422_dict_detail(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "TRIGGER_NATIVE_422_DICT"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("Invalid criteria shape", proc.stderr)

    def test_401_bad_key_hint(self):
        with MockDecisionsServer(expected_native_key="right-native") as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="wrong-native", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "x"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("API 错误 (HTTP 401)", proc.stderr)
            self.assertIn("Cannot authenticate", proc.stderr)
            self.assertIn("jev auth set", proc.stderr)

    def test_429_then_200_retries_on_native(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_BASE_URL=mock.native_base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "RETRY429:native-a", "--json"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertIn("noul", out["answer"])
            retries = [
                r for r in mock.requests if r["body"] and r["body"].get("state") == "RETRY429:native-a"
            ]
            self.assertEqual(len(retries), 2)


if __name__ == "__main__":
    unittest.main()
