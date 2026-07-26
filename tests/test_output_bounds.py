"""Bounded task output — memory + disk DoS guards.

Task stdout/stderr used to be collected in an unbounded list and clipped once at
the end (`"".join(buf)[-65536:]`). That bounded the result file but not the
daemon's RAM: a script emitting gigabytes filled memory before any clip ran, and
truncation was silent, so a caller could not tell 64 KiB of output from the tail
of 5 GB.

These tests lock in both halves of the fix:
  * the in-memory tail is bounded WHILE streaming, not at the end
  * truncation is reported explicitly (`*_truncated`, `*_total_bytes`)
  * the live progress log is capped so it can't fill the disk
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
# 1. _BoundedTail keeps the tail and bounds resident size
# ---------------------------------------------------------------------------

def test_bounded_tail_keeps_last_n_chars():
    tail = daemon._BoundedTail(10)
    for ch in "abcdefghijklmnop":
        tail.append(ch)
    assert tail.value() == "ghijklmnop"
    assert tail.truncated is True
    assert tail.total == 16


def test_bounded_tail_untruncated_when_under_limit():
    tail = daemon._BoundedTail(100)
    tail.append("hello ")
    tail.append("world")
    assert tail.value() == "hello world"
    assert tail.truncated is False
    assert tail.total == 11


def test_bounded_tail_resident_size_stays_bounded():
    """The whole point: memory must not grow with total output volume.

    Append far more than the limit and assert the retained buffer stays small.
    Without the eviction loop this holds ~10 MB instead of ~2x the limit.
    """
    limit = 1024
    tail = daemon._BoundedTail(limit)
    chunk = "x" * 1024
    for _ in range(10_000):          # 10 MB streamed
        tail.append(chunk)
    retained = sum(len(c) for c in tail._chunks)
    assert retained <= 2 * limit, f"retained {retained} bytes, expected <= {2 * limit}"
    assert len(tail.value()) == limit
    assert tail.truncated is True
    assert tail.total == 10_000 * 1024


def test_bounded_tail_exact_boundary_not_flagged():
    """Exactly at the limit is complete output, not truncated."""
    tail = daemon._BoundedTail(5)
    tail.append("abcde")
    assert tail.value() == "abcde"
    assert tail.truncated is False


def test_bounded_tail_handles_chunk_larger_than_limit():
    tail = daemon._BoundedTail(4)
    tail.append("abcdefghij")
    assert tail.value() == "ghij"
    assert tail.truncated is True


# ---------------------------------------------------------------------------
# 2. _output_fields reports truncation explicitly, and only when it happened
# ---------------------------------------------------------------------------

def test_output_fields_omits_flags_when_not_truncated():
    out, err = daemon._BoundedTail(100), daemon._BoundedTail(100)
    out.append("fine")
    fields = daemon._output_fields(out, err)
    assert fields == {"stdout": "fine", "stderr": ""}
    # Old clients must not suddenly see new keys on a normal result.
    assert "stdout_truncated" not in fields
    assert "stderr_truncated" not in fields


def test_output_fields_flags_truncation_with_total():
    out, err = daemon._BoundedTail(4), daemon._BoundedTail(100)
    out.append("abcdefghij")
    fields = daemon._output_fields(out, err)
    assert fields["stdout"] == "ghij"
    assert fields["stdout_truncated"] is True
    assert fields["stdout_total_bytes"] == 10
    assert "stderr_truncated" not in fields


def test_output_fields_flags_stderr_independently():
    out, err = daemon._BoundedTail(100), daemon._BoundedTail(3)
    err.append("boom!!")
    fields = daemon._output_fields(out, err)
    assert fields["stderr_truncated"] is True
    assert fields["stderr_total_bytes"] == 6
    assert "stdout_truncated" not in fields


# ---------------------------------------------------------------------------
# 3. End-to-end through _run_streaming: a loud child is capped in RAM and on disk
# ---------------------------------------------------------------------------

def _run(tmp_path, script_body: str, **kw):
    script = tmp_path / "loud.py"
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


def test_run_streaming_caps_stdout_and_flags_it(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 2048)
    body = (
        "import sys\n"
        "for i in range(2000):\n"
        "    sys.stdout.write('line %d ' % i + 'y' * 100 + '\\n')\n"
    )
    result, _ = _run(tmp_path, body)
    assert result["exit_code"] == 0
    assert len(result["stdout"]) <= 2048
    assert result["stdout_truncated"] is True
    assert result["stdout_total_bytes"] > 2048
    # The TAIL is what we keep — the last line must be present, the first gone.
    assert "line 1999" in result["stdout"]
    assert "line 0 " not in result["stdout"]


def test_run_streaming_leaves_small_output_unflagged(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 64 * 1024)
    result, _ = _run(tmp_path, "print('quiet')\n")
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "quiet"
    assert "stdout_truncated" not in result
    assert "stdout_total_bytes" not in result


def test_run_streaming_caps_progress_log_on_disk(tmp_path, monkeypatch):
    """The live progress log must not grow without bound either."""
    monkeypatch.setattr(daemon, "MAX_PROGRESS_BYTES", 8192)
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 1024)
    body = (
        "import sys\n"
        "for i in range(5000):\n"
        "    sys.stdout.write('z' * 200 + '\\n')\n"
    )
    result, progress = _run(tmp_path, body)
    assert result["exit_code"] == 0
    size = progress.stat().st_size
    # Cap + the final notice line + one in-flight line of slack.
    assert size < 8192 + 1024, f"progress log grew to {size} bytes despite cap"
    assert "capped at" in progress.read_text()


def test_run_streaming_result_is_json_serialisable(tmp_path, monkeypatch):
    """write_result() json.dumps() the payload — truncation flags must survive."""
    monkeypatch.setattr(daemon, "MAX_OUTPUT_BYTES", 512)
    body = "import sys\nsys.stdout.write('q' * 5000)\n"
    result, _ = _run(tmp_path, body)
    round_tripped = json.loads(json.dumps(result))
    assert round_tripped["stdout_truncated"] is True
    assert round_tripped["stdout_total_bytes"] == 5000


# ---------------------------------------------------------------------------
# 4. Negative control — a checker that can't fail is worthless.
#    Assert the OLD unbounded approach would actually have been caught by the
#    resident-size test above, so that test is known to have teeth.
# ---------------------------------------------------------------------------

def test_negative_control_unbounded_buffer_would_fail():
    """Reproduce the pre-fix behaviour and show it violates the bound."""
    limit = 1024
    unbounded: list[str] = []          # the old `out_buf: list[str] = []`
    chunk = "x" * 1024
    for _ in range(2_000):
        unbounded.append(chunk)
    retained = sum(len(c) for c in unbounded)
    assert retained > 2 * limit, (
        "negative control is broken: the old unbounded buffer should exceed the "
        "bound that test_bounded_tail_resident_size_stays_bounded enforces"
    )


# ---------------------------------------------------------------------------
# 5. Both daemon copies must carry the guard (they drift — see CONTRIBUTING)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "cowork_to_code_bridge/daemon.py",
    "daemon/daemon.py",
])
def test_both_daemon_copies_bound_output(rel):
    path = REPO / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    src = path.read_text()
    assert "_BoundedTail" in src, (
        f"{rel} must bound streamed output in memory (_BoundedTail), not clip "
        "once at the end — an unbounded buffer is a RAM DoS"
    )
    # Look for the old clip in CODE only: both files legitimately mention it in
    # prose explaining what was replaced, and a naive substring check matches
    # that explanation instead of a real regression.
    code_lines = [
        ln for ln in src.splitlines()
        if "[-65536:]" in ln and not ln.lstrip().startswith("#")
        and "`" not in ln  # docstring prose quotes the old expression in backticks
    ]
    assert not code_lines, (
        f"{rel} still uses the old silent end-of-run clip; truncation must be "
        f"enforced while streaming and reported via *_truncated. Offending: {code_lines}"
    )
    assert "stdout_truncated" in src, (
        f"{rel} must report truncation explicitly so callers can distinguish a "
        "small output from the tail of a huge one"
    )
