# Local mock of both provider backends, for offline jev tests:
#   - OpenRouter-shaped: POST /api/alpha/decisions, GET /api/v1/key
#   - TypeSafe native-shaped: POST /v1/systemone, GET /v1/models
# Both run on the same server instance/port so a single mock can exercise
# provider-switching behavior; each has its own expected bearer token.
#
# Not a test module itself (no Test* classes) -- imported by tests/test_*.py.
# Validates request shape the way the real API is documented to (model/state/
# questions present and typed, per-type criteria rules), then returns a
# deterministic canned answer so tests can assert exact output.
#
# GET /api/v1/key (used by `jev auth check` for openrouter): `Bearer
# <expected_key>` -> 200 with a canned key-info body (including a fake
# `label` and `creator_user_id` so tests can confirm the CLI never prints
# either); any other bearer -> 401.
#
# GET /v1/models (used by `jev auth check` for typesafe): `Bearer
# <expected_native_key>` -> 200 with {"data": [...model names...]}; missing
# Authorization -> 403; wrong bearer -> 401 -- both with the exact `detail`
# bodies TypeSafe's live API returns (see docstrings below).
#
# Canned-answer convention, read from the `state` when it is a plain string:
#   noul question   -- "YES" in text -> 0.9, "NO" in text -> 0.1, else 0.5
#   choice question -- "CHOICE=<name>" selects that option (else the first)
#   score question  -- "SCORE=<index>" selects that 0-based level (else the middle)
# Special exact/prefix triggers (again matched against a string `state`) return
# specific error shapes or timing behavior instead of a canned answer:
#   "TRIGGER_ZOD_ERROR"          -- 400, error.message is a JSON-encoded Zod issue array
#   "TRIGGER_HTTP400_STR"        -- 400, error.message == 'HTTP 400: {"detail": "..."}'
#   "TRIGGER_HTTP400_OBJ"        -- 400, same shape, detail is an object with "message"
#   "TRIGGER_PLAIN_ERROR"        -- 400, error.message is a plain string
#   "TRIGGER_NATIVE_422_LIST"    -- native only: 422, missing-field issue list (verified live shape)
#   "TRIGGER_NATIVE_422_DICT"    -- native only: 422, detail is an object with "message"
#   "TRIGGER_NATIVE_UNKNOWN_TYPE"  -- native only: 400, unknown question type (verified live shape)
#   "TRIGGER_NATIVE_UNKNOWN_MODEL" -- native only: 400, unknown model, echoes the request's model
#   "TRIGGER_NATIVE_TOO_MANY_LEVELS" -- native only: 400, detail is a plain string (verified live shape)
#   "RETRY429:<anything>"        -- 429 + Retry-After: 0 on the first call for that
#                                   exact state, 200 with a canned answer after
#   "SLOW:<ms>:<anything>"       -- sleeps ms milliseconds before a canned answer
# A wrong bearer token always short-circuits to 401 (or 403 if missing
# entirely, native only), before any of the above.
#
# One verified behavior difference between backends: the native route accepts
# a one-sided `noul` criteria object (200); the OpenRouter route keeps
# rejecting it (400) like before -- jev's own client-side validation already
# requires both sides for every typed verb and spec, so this only matters to
# `jev raw`, which sends a body verbatim.
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_KEY_INFO = {
    # Deliberately includes label / creator_user_id: `jev auth check` must
    # never print either, and tests assert that directly against this data.
    "label": "sk-or-v1-abc...xyz",
    "usage": 2.25,
    "usage_daily": 0.1,
    "limit": None,
    "limit_remaining": None,
    "is_free_tier": False,
    "creator_user_id": "user_fake00000000000000000",
}

# GET /v1/models returned exactly these two, live, against a real account.
DEFAULT_NATIVE_MODELS = ["jev-latest", "jev-preview"]


def _native_missing_auth_body():
    # Exact shape observed live: no Authorization header -> HTTP 403.
    return {"detail": {
        "error_type": "authentication_error",
        "message": "Must supply an API key! Check your request and try again.",
    }}


def _native_bad_key_body():
    # Exact shape observed live: wrong bearer -> HTTP 401 (same for GET /v1/models).
    return {"detail": {
        "error_type": "authentication_error",
        "message": "Cannot authenticate with the server. Please check your API key and try again.",
    }}


def _native_422_list_body():
    # Exact shape observed live for a missing required field.
    return {"detail": [
        {"type": "missing", "loc": ["body", "questions", "q", "choice", "criteria"],
         "msg": "Field required", "input": {}}
    ]}


def _native_422_dict_body():
    return {"detail": {"message": "Invalid criteria shape"}}


def _native_unknown_question_type_body():
    # Exact shape observed live for an unrecognized question "type".
    return {"detail": {"error_type": "api_usage_error", "message": "Invalid request."}}


def _native_unknown_model_body(model_name):
    # Exact shape observed live for a model name the account can't use.
    return {"detail": {"error_type": "api_usage_error", "message": f"Unknown model: {model_name}"}}


def _native_too_many_score_levels_body():
    # Exact shape observed live: a plain string, not an object, at 400.
    return {"detail": "Too many score levels. Must have at most 10 levels."}


class MockDecisionsServer:
    def __init__(self, expected_key="test", path="/api/alpha/decisions",
                 key_path="/api/v1/key", key_info=None,
                 expected_native_key="ts-test",
                 native_decisions_path="/v1/systemone",
                 native_models_path="/v1/models",
                 native_models=None):
        self.expected_key = expected_key
        self.path = path
        self.key_path = key_path
        self.key_info = dict(DEFAULT_KEY_INFO if key_info is None else key_info)
        self.expected_native_key = expected_native_key
        self.native_decisions_path = native_decisions_path
        self.native_models_path = native_models_path
        self.native_models = list(DEFAULT_NATIVE_MODELS if native_models is None else native_models)
        self._lock = threading.Lock()
        self._requests = []
        self._retry_seen = set()
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    @property
    def port(self):
        return self._httpd.server_address[1]

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}{self.path}"

    @property
    def key_url(self):
        return f"http://127.0.0.1:{self.port}{self.key_path}"

    @property
    def native_base_url(self):
        return f"http://127.0.0.1:{self.port}{self.native_decisions_path}"

    @property
    def native_key_url(self):
        return f"http://127.0.0.1:{self.port}{self.native_models_path}"

    def log(self, entry):
        with self._lock:
            self._requests.append(entry)

    @property
    def requests(self):
        with self._lock:
            return list(self._requests)

    @property
    def request_count(self):
        with self._lock:
            return len(self._requests)

    def retry_seen_before(self, key):
        with self._lock:
            seen = key in self._retry_seen
            self._retry_seen.add(key)
            return seen


def _zod_error_body(issues):
    arr = [{"path": p, "message": m} for p, m in issues]
    return {"error": {"message": json.dumps(arr)}}


def _http400_detail_body(detail):
    inner = json.dumps({"detail": detail})
    return {"error": {"message": f"HTTP 400: {inner}"}}


def _plain_error_body(message):
    return {"error": {"message": message}}


def _validate_questions(questions):
    """Mirrors the shape the real API is documented to require. Returns an
    error (status, body_dict) tuple, or None if the request is well-formed."""
    if not isinstance(questions, dict) or not questions:
        return 400, _zod_error_body([(["questions"], "Required")])
    for name, q in questions.items():
        if not isinstance(q, dict):
            return 400, _zod_error_body([(["questions", name], "Expected object")])
        qtype = q.get("type")
        if qtype not in ("noul", "choice", "score"):
            return 400, _zod_error_body([(["questions", name, "type"], "Invalid enum value")])
        if not q.get("instructions"):
            return 400, _zod_error_body([(["questions", name, "instructions"], "Required")])
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or len(criteria) < 2:
                return 400, _zod_error_body([(["questions", name, "criteria"], "Expected >= 2 keys")])
        elif qtype == "score":
            if not isinstance(criteria, list) or not (2 <= len(criteria) <= 10):
                return 400, _zod_error_body([(["questions", name, "criteria"], "Expected 2-10 items")])
        elif qtype == "noul":
            if criteria is not None:
                if not isinstance(criteria, dict) or "true" not in criteria or "false" not in criteria:
                    return 400, _zod_error_body(
                        [(["questions", name, "criteria", "false"], "Required")]
                    )
    return None


def _validate_questions_native(questions):
    """Same request-shape checks as _validate_questions, but in the native
    error shapes, and -- verified live -- accepting a one-sided `noul`
    criteria object where OpenRouter rejects it. jev's own client-side
    validation already requires both sides for every typed verb and spec, so
    this only matters to `jev raw`."""
    if not isinstance(questions, dict) or not questions:
        return 422, _native_422_list_body()
    for name, q in questions.items():
        if not isinstance(q, dict):
            return 422, _native_422_list_body()
        qtype = q.get("type")
        if qtype not in ("noul", "choice", "score"):
            return 400, _native_unknown_question_type_body()
        if not q.get("instructions"):
            return 422, _native_422_list_body()
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or len(criteria) < 2:
                return 422, _native_422_list_body()
        elif qtype == "score":
            if not isinstance(criteria, list):
                return 422, _native_422_list_body()
            if len(criteria) > 10:
                return 400, _native_too_many_score_levels_body()
            if len(criteria) < 2:
                return 422, _native_422_list_body()
        # noul: no shape restriction on criteria here -- one-sided is accepted live.
    return None


def _canned_answer(qobj, state):
    text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
    qtype = qobj["type"]
    if qtype == "noul":
        if "YES" in text:
            p = 0.9
        elif "NO" in text:
            p = 0.1
        else:
            p = 0.5
        return {"type": "noul", "noul": p, "confidence": 0.8}
    if qtype == "choice":
        keys = list(qobj["criteria"].keys())
        chosen = keys[0]
        m = re.search(r"CHOICE=([A-Za-z0-9_]+)", text)
        if m and m.group(1) in keys:
            chosen = m.group(1)
        others = [k for k in keys if k != chosen]
        probs = {}
        if others:
            share = round(0.2 / len(others), 4)
            for k in others:
                probs[k] = share
        probs[chosen] = round(1 - sum(probs.values()), 4)
        return {"type": "choice", "choice": chosen, "probabilities": probs, "confidence": probs[chosen]}
    # score
    labels = qobj["criteria"]
    n = len(labels)
    idx = n // 2
    m = re.search(r"SCORE=(\d+)", text)
    if m and 0 <= int(m.group(1)) < n:
        idx = int(m.group(1))
    legend = {str(i): labels[i] for i in range(n)}
    others = [i for i in range(n) if i != idx]
    probs = {str(i): 0.0 for i in range(n)}
    probs[str(idx)] = 0.7
    if others:
        share = round(0.3 / len(others), 4)
        for i in others:
            probs[str(i)] = share
    return {"type": "score", "score": float(idx), "legend": legend, "probabilities": probs, "confidence": 0.7}


def _make_handler(server):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
            pass  # keep test output clean; inspect server.requests instead

        def _send_json(self, status, body_dict, extra_headers=None):
            payload = json.dumps(body_dict).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802 - stdlib method name
            auth = self.headers.get("Authorization", "")
            server.log({
                "path": self.path,
                "method": "GET",
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": None,
            })

            if self.path == server.native_models_path:
                if not auth:
                    self._send_json(403, _native_missing_auth_body())
                    return
                if auth != f"Bearer {server.expected_native_key}":
                    self._send_json(401, _native_bad_key_body())
                    return
                self._send_json(200, {"data": list(server.native_models)})
                return

            if self.path != server.key_path:
                self._send_json(404, _plain_error_body("Not found"))
                return
            if auth != f"Bearer {server.expected_key}":
                self._send_json(401, _plain_error_body("User not found."))
                return
            self._send_json(200, {"data": server.key_info})

        def _do_post_native(self, body, auth):
            if not auth:
                self._send_json(403, _native_missing_auth_body())
                return
            if auth != f"Bearer {server.expected_native_key}":
                self._send_json(401, _native_bad_key_body())
                return
            if not isinstance(body, dict) or not body.get("model") or \
                    "state" not in body or body["state"] in (None, ""):
                self._send_json(422, _native_422_dict_body())
                return

            state = body["state"]
            if isinstance(state, str):
                if state == "TRIGGER_NATIVE_422_LIST":
                    self._send_json(422, _native_422_list_body())
                    return
                if state == "TRIGGER_NATIVE_422_DICT":
                    self._send_json(422, _native_422_dict_body())
                    return
                if state == "TRIGGER_NATIVE_UNKNOWN_TYPE":
                    self._send_json(400, _native_unknown_question_type_body())
                    return
                if state == "TRIGGER_NATIVE_UNKNOWN_MODEL":
                    self._send_json(400, _native_unknown_model_body(body.get("model", "")))
                    return
                if state == "TRIGGER_NATIVE_TOO_MANY_LEVELS":
                    self._send_json(400, _native_too_many_score_levels_body())
                    return
                if state.startswith("RETRY429:"):
                    if not server.retry_seen_before("native:" + state):
                        self._send_json(429, _plain_error_body("Rate limited"),
                                         extra_headers={"Retry-After": "0"})
                        return
                if state.startswith("SLOW:"):
                    try:
                        ms = int(state.split(":", 2)[1])
                    except (IndexError, ValueError):
                        ms = 0
                    time.sleep(ms / 1000.0)

            err = _validate_questions_native(body.get("questions"))
            if err is not None:
                status, err_body = err
                self._send_json(status, err_body)
                return

            answers = {
                name: _canned_answer(q, state)
                for name, q in body["questions"].items()
            }
            # Native response: no id, no usage.cost, no provider field.
            self._send_json(200, {
                "model": body["model"],
                "answers": answers,
                "usage": {"input_tokens": 50, "output_tokens": 5},
            })

        def do_POST(self):  # noqa: N802 - stdlib method name
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            auth = self.headers.get("Authorization", "")

            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                body = None

            server.log({
                "path": self.path,
                "method": "POST",
                # Lowercased: HTTP header names are case-insensitive, and
                # urllib's own str.capitalize() re-casing of the request
                # headers means the wire casing isn't reliably "X-Title" etc.
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            })

            if self.path == server.native_decisions_path:
                self._do_post_native(body, auth)
                return

            if auth != f"Bearer {server.expected_key}":
                self._send_json(401, _plain_error_body("No auth credentials found"))
                return

            if not isinstance(body, dict):
                self._send_json(400, _plain_error_body("Invalid JSON body"))
                return
            if not body.get("model"):
                self._send_json(400, _zod_error_body([(["model"], "Required")]))
                return
            if "state" not in body or body["state"] in (None, ""):
                self._send_json(400, _zod_error_body([(["state"], "Required")]))
                return

            state = body["state"]

            if isinstance(state, str):
                if state == "TRIGGER_ZOD_ERROR":
                    self._send_json(400, _zod_error_body(
                        [(["questions", "answer", "criteria"], "Required")]))
                    return
                if state == "TRIGGER_HTTP400_STR":
                    self._send_json(400, _http400_detail_body("Invalid request payload"))
                    return
                if state == "TRIGGER_HTTP400_OBJ":
                    self._send_json(400, _http400_detail_body({"message": "Bad criteria shape"}))
                    return
                if state == "TRIGGER_PLAIN_ERROR":
                    self._send_json(400, _plain_error_body("Something went wrong"))
                    return
                if state.startswith("RETRY429:"):
                    if not server.retry_seen_before(state):
                        self._send_json(429, _plain_error_body("Rate limited"),
                                         extra_headers={"Retry-After": "0"})
                        return
                if state.startswith("SLOW:"):
                    try:
                        ms = int(state.split(":", 2)[1])
                    except (IndexError, ValueError):
                        ms = 0
                    time.sleep(ms / 1000.0)

            err = _validate_questions(body.get("questions"))
            if err is not None:
                status, err_body = err
                self._send_json(status, err_body)
                return

            answers = {
                name: _canned_answer(q, state)
                for name, q in body["questions"].items()
            }
            self._send_json(200, {
                "id": "mock-decision-0",
                "model": body["model"],
                "answers": answers,
                "usage": {"input_tokens": 50, "output_tokens": 5, "cost": 0.00002},
            })

    return Handler
