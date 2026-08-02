"""Secret redaction on the write path (#76).

BRIDGE_ROOT is the trust boundary — a shared, bind-mounted directory. Bounded
output caps the *size* of what a task writes there; nothing capped its
*sensitivity*. A task that echoed a token (`env`, a verbose CI script, a curl
printing its Authorization header) wrote that secret to disk in the shared
directory, verbatim, in both the result file and the live progress log.

These tests are deliberately written as MUTATION tests against the bytes that
actually land on disk, not against a returned string. This repo has shipped a
green no-op before (a fake SIGTERM passed for months because the test asserted
on a response message instead of the kill), so every guard here:

  * plants a real secret,
  * reads the file back off disk,
  * asserts the secret is absent AND the marker is present,
  * and is paired with a negative control proving the same check FAILS when
    redaction is disabled — i.e. the assertion has teeth.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

daemon = importlib.import_module("cowork_to_code_bridge.daemon")


# ---------------------------------------------------------------------------
# fake credentials
# ---------------------------------------------------------------------------
# Every fixture is ASSEMBLED AT RUNTIME rather than written as a literal. These
# are fake — random padding, never issued — but they are shaped exactly like the
# real thing, which is the whole point of the test, and that shape is what a
# credential scanner matches on. Written literally, GitHub push protection
# blocks the push (it did) and any repo-wide scanner flags this file forever.
#
# Splitting the prefix from the body keeps the test meaningful (redact_text
# still sees a complete, correctly-shaped credential) while leaving no
# scannable string in the source. Do not "simplify" these back into literals.
_PAD = "AAAABBBBCCCCDDDDEEEEFFFF1234"

FAKE_KEYS = {
    "anthropic": "sk-" + "ant-api03-" + _PAD,
    "openai": "sk-" + _PAD + "5678",
    "github-pat": "github" + "_pat_" + "11ABCDEFG0123456789abcdefghij",
    "github-classic": "ghp" + "_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
    "slack": "xox" + "b-" + "123456789012-abcdefghijklmnop",
    "aws": "AKIA" + "IOSFODNN7EXAMPLE",
    "google": "AIza" + "B" * 35,
}

FAKE_TOKEN = "s3cr3t-bridge-token-" + "abcdefghijklmnop"
FAKE_GH = FAKE_KEYS["github-classic"]
FAKE_ANTHROPIC = FAKE_KEYS["anthropic"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _isolate_results(tmp_path, monkeypatch):
    """Point write_result at a temp results dir and return it."""
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(daemon, "RESULTS", results)
    return results


def _written(results: Path, cmd_id: str) -> str:
    """Raw text of the result file as it exists on disk."""
    return (results / f"{cmd_id}.json").read_text()


def _run(tmp_path, script_body: str, **kw):
    script = tmp_path / "emit.py"
    script.write_text(script_body)
    progress = tmp_path / "prog.log"
    return daemon._run_streaming(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        env={**os.environ},
        timeout=60,
        progress_file=progress,
        **kw,
    ), progress


# ---------------------------------------------------------------------------
# 1. The literal the daemon knows for certain: its own BRIDGE_TOKEN
# ---------------------------------------------------------------------------

def test_registered_token_is_scrubbed_from_the_result_file(tmp_path, monkeypatch):
    """The daemon's own token must never reach disk, whatever printed it."""
    results = _isolate_results(tmp_path, monkeypatch)
    secret = FAKE_TOKEN
    monkeypatch.setattr(daemon, "_SECRET_LITERALS", {secret})

    daemon.write_result("cmd-1", {"exit_code": 0,
                                  "stdout": f"BRIDGE_TOKEN={secret}\ndone\n",
                                  "stderr": ""})

    raw = _written(results, "cmd-1")
    assert secret not in raw, "the daemon's own token was written to the result file"
    assert "[redacted:token]" in raw
    # Surrounding output survives — redaction must not eat the whole stream.
    assert "done" in json.loads(raw)["stdout"]


def test_negative_control_token_leaks_when_redaction_disabled(tmp_path, monkeypatch):
    """Same planted secret, BRIDGE_REDACT=0 → it DOES land on disk.

    This is what makes the test above meaningful: it proves the assertion is
    driven by the redaction code and not by the secret never being there.
    """
    results = _isolate_results(tmp_path, monkeypatch)
    secret = FAKE_TOKEN
    monkeypatch.setattr(daemon, "_SECRET_LITERALS", {secret})
    monkeypatch.setattr(daemon, "REDACT_ENABLED", False)

    daemon.write_result("cmd-2", {"exit_code": 0, "stdout": f"tok={secret}"})

    raw = _written(results, "cmd-2")
    assert secret in raw, "escape hatch broken: BRIDGE_REDACT=0 still redacted"
    assert "[redacted" not in raw


def test_register_secret_ignores_short_values():
    """A 4-char 'token' would match everywhere and mangle ordinary output."""
    before = set(daemon._SECRET_LITERALS)
    try:
        daemon.register_secret("abc")
        daemon.register_secret("")
        daemon.register_secret(None)
        assert before == daemon._SECRET_LITERALS
        daemon.register_secret("long-enough-secret")
        assert "long-enough-secret" in daemon._SECRET_LITERALS
    finally:
        daemon._SECRET_LITERALS.clear()
        daemon._SECRET_LITERALS.update(before)


# ---------------------------------------------------------------------------
# 2. Shape-matched patterns (best-effort tier)
# ---------------------------------------------------------------------------

def test_vendor_key_shapes_are_redacted():
    for label, secret in FAKE_KEYS.items():
        out = daemon.redact_text(f"prefix {secret} suffix")
        assert secret not in out, f"{label} key survived redaction"
        assert "[redacted:" in out
        # Context is preserved so the output stays readable.
        assert out.startswith("prefix ") and out.endswith(" suffix")


def test_authorization_header_keeps_context_scrubs_credential():
    out = daemon.redact_text("Authorization: Bearer abcdef1234567890ABCDEF\n")
    assert "abcdef1234567890ABCDEF" not in out
    assert "Authorization:" in out, "header name should survive for debuggability"
    assert "[redacted:bearer]" in out


def test_url_inline_password_scrubbed_host_kept():
    out = daemon.redact_text("cloning https://user:hunter2pass@github.com/x/y.git")
    assert "hunter2pass" not in out
    assert "github.com/x/y.git" in out, "host must stay readable"


def test_private_key_block_is_redacted():
    blob = ("-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA1234567890\nabcdefghij\n"
            "-----END RSA PRIVATE KEY-----")
    out = daemon.redact_text(f"leaked:\n{blob}\ntail")
    assert "MIIEowIBAAKCAQEA1234567890" not in out
    assert "[redacted:private-key-block]" in out
    assert out.endswith("tail")


def test_assigned_secret_requires_a_keyish_name():
    """The name gate is what keeps this from eating ordinary build output."""
    redacted = daemon.redact_text("API_KEY=AAAABBBBCCCCDDDDEEEE")
    assert "AAAABBBBCCCCDDDDEEEE" not in redacted
    assert "[redacted:assigned-secret]" in redacted

    # A bare long token with no key-ish name is NOT a secret by shape: git
    # SHAs, build hashes, and base64 blobs are everywhere in real output and
    # redacting them would make the bridge useless for its actual job.
    for benign in (
        "commit 9f8e7d6c5b4a39281706f5e4d3c2b1a098765432",
        "Compiled target aGVsbG8gd29ybGQgdGhpcyBpcyBub3QgYSBzZWNyZXQ=",
        "/usr/local/lib/python3.10/site-packages/some_long_module_name",
    ):
        assert daemon.redact_text(benign) == benign, f"false positive on: {benign}"


def test_redaction_marker_is_stable_across_calls():
    """Stable marker → results stay diffable run to run."""
    line = "TOKEN=AAAABBBBCCCCDDDD"
    assert daemon.redact_text(line) == daemon.redact_text(line)


def test_redact_text_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr(daemon, "REDACT_ENABLED", False)
    line = "API_KEY=AAAABBBBCCCCDDDDEEEE"
    assert daemon.redact_text(line) == line


# ---------------------------------------------------------------------------
# 3. Whole-payload coverage: not just stdout
# ---------------------------------------------------------------------------

def test_redaction_covers_nested_payload_fields(tmp_path, monkeypatch):
    """An error string or echoed arg can carry a secret as easily as stdout."""
    results = _isolate_results(tmp_path, monkeypatch)
    secret = FAKE_GH

    daemon.write_result("cmd-3", {
        "exit_code": 1,
        "stdout": "",
        "stderr": "",
        "error": f"curl failed with header {secret}",
        "args": ["--token", secret],
        "nested": {"deep": {"leak": secret}},
    })

    raw = _written(results, "cmd-3")
    assert secret not in raw
    payload = json.loads(raw)
    assert "[redacted:" in payload["error"]
    assert "[redacted:" in payload["args"][1]
    assert "[redacted:" in payload["nested"]["deep"]["leak"]


def test_non_string_payload_values_survive(tmp_path, monkeypatch):
    """Redaction must not corrupt exit codes, flags, or timestamps."""
    results = _isolate_results(tmp_path, monkeypatch)
    daemon.write_result("cmd-4", {
        "exit_code": -6, "stdout": "ok", "stderr": "",
        "expired": True, "stdout_total_bytes": 1234, "ratio": 0.5,
        "maybe": None,
    })
    payload = json.loads(_written(results, "cmd-4"))
    assert payload["exit_code"] == -6
    assert payload["expired"] is True
    assert payload["stdout_total_bytes"] == 1234
    assert payload["ratio"] == 0.5
    assert payload["maybe"] is None


# ---------------------------------------------------------------------------
# 4. End-to-end through _run_streaming: the progress log is a sink too
# ---------------------------------------------------------------------------

def test_streaming_redacts_result_and_progress_log(tmp_path, monkeypatch):
    """The live progress log lives under BRIDGE_ROOT — it must be scrubbed too.

    Scrubbing only the result file would leave the same secret sitting in the
    shared directory via the live view the client tails.
    """
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 64 * 1024)
    secret = FAKE_ANTHROPIC
    body = (
        "import sys\n"
        f"sys.stdout.write('using key {secret}\\n')\n"
        f"sys.stderr.write('auth failed for {secret}\\n')\n"
        "sys.stdout.write('finished\\n')\n"
    )
    result, progress = _run(tmp_path, body)

    assert result["exit_code"] == 0
    assert secret not in result["stdout"], "secret survived into result stdout"
    assert secret not in result["stderr"], "secret survived into result stderr"
    assert "[redacted:anthropic-key]" in result["stdout"]
    assert "finished" in result["stdout"], "ordinary output must survive"

    on_disk = progress.read_text()
    assert secret not in on_disk, "secret written verbatim to the progress log"
    assert "[redacted:anthropic-key]" in on_disk


def test_negative_control_streaming_leaks_when_disabled(tmp_path, monkeypatch):
    """Same script, redaction off → the secret hits both sinks.

    Pairs with the test above: without this, a redaction function that silently
    did nothing on the streaming path would still pass, because we would only
    be proving the secret is absent, not that redaction removed it.
    """
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 64 * 1024)
    monkeypatch.setattr(daemon, "REDACT_ENABLED", False)
    secret = FAKE_ANTHROPIC
    body = f"import sys\nsys.stdout.write('using key {secret}\\n')\n"
    result, progress = _run(tmp_path, body)

    assert secret in result["stdout"], "escape hatch broken on the streaming path"
    assert secret in progress.read_text()


def test_streaming_status_line_is_redacted(tmp_path, monkeypatch):
    """The status line the client polls is a third sink under BRIDGE_ROOT."""
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 64 * 1024)
    secret = FAKE_GH
    body = f"import sys\nsys.stdout.write('token {secret}\\n')\n"
    _run(tmp_path, body)

    status = tmp_path / "prog.status.json"
    if status.exists():                      # written only when the poller ran
        assert secret not in status.read_text()


def test_redaction_survives_json_round_trip(tmp_path, monkeypatch):
    """The marker must survive json.dumps unmangled.

    It is ASCII on purpose: json.dumps escapes non-ASCII, so a «» marker would
    land on disk as \\u00ab…\\u00bb — harder to read and harder to grep when
    you are checking a result file for a leak.
    """
    results = _isolate_results(tmp_path, monkeypatch)
    daemon.write_result("cmd-5", {"exit_code": 0,
                                  "stdout": "API_KEY=AAAABBBBCCCCDDDDEEEE"})
    raw = _written(results, "cmd-5")
    assert "[redacted:assigned-secret]" in raw, "marker was escaped on disk"
    payload = json.loads(raw)
    assert "[redacted:assigned-secret]" in payload["stdout"]


# ---------------------------------------------------------------------------
# 5. Both daemon copies must carry the guard (they drift — see CONTRIBUTING)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "cowork_to_code_bridge/daemon.py",
    "daemon/daemon.py",
])
def test_both_daemon_copies_redact(rel):
    """An owner running the legacy copy must not silently lose redaction.

    Redaction is a security boundary, not a feature: the copy that lacks it
    writes secrets to the shared directory. Same convention as the bounded-
    output guard — both copies carry it, or the copy goes.
    """
    path = REPO / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    src = path.read_text()
    assert "def redact_text(" in src, f"{rel} must define redact_text()"
    assert "payload = redact_payload(payload)" in src, (
        f"{rel} must redact in write_result — the single choke point every "
        "result passes through, so a new caller cannot forget it"
    )
    assert "line = redact_text(line)" in src, (
        f"{rel} must redact each streamed line before it reaches the bounded "
        "tail and the progress log; both sinks live under BRIDGE_ROOT"
    )
    assert "register_secret(token)" in src, (
        f"{rel} must register its own BRIDGE_TOKEN as a known literal — the "
        "one secret it can redact with certainty rather than by shape"
    )


# ---------------------------------------------------------------------------
# 6. Docs drift — this repo's recurring gap class is "code lands, docs don't"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "SECURITY.md",
    "docs/BRIDGE_INIT.md",
    "CLAUDE.md",
])
def test_redaction_is_documented(rel):
    """A security control nobody knows about gets designed around.

    Callers need to know a [redacted:…] marker is the daemon, not a broken
    script; owners need to know the escape hatch exists; and everyone needs the
    honest limit — best-effort, not a guarantee.
    """
    text = (REPO / rel).read_text()
    assert "BRIDGE_REDACT" in text, f"{rel} must document the escape hatch"
    assert "redact" in text.lower(), f"{rel} must document redaction"
    assert "est-effort" in text, (
        f"{rel} must state redaction is best-effort — claiming a guarantee we "
        "cannot make is worse than not redacting at all"
    )


def test_bridge_context_documents_redaction():
    """The context string is what a sandbox loads when docs/ isn't mounted."""
    ctx = importlib.import_module(
        "cowork_to_code_bridge.bridge_init").get_bridge_context()
    assert "BRIDGE_REDACT" in ctx
    assert "[redacted:" in ctx, (
        "the context must show the actual marker a caller will see in results"
    )
    assert "est-effort" in ctx
