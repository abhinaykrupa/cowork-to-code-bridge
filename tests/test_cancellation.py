"""
Test cancellation behavior for long-running operations.

This tests the three cancellation scenarios:
1. Pre-execution (operation still in queue) → immediate cancellation
2. During-execution (operation running) → graceful shutdown via SIGTERM
3. Post-execution (operation already completed) → idempotent (no-op)
"""
import json
import tempfile
import time
from pathlib import Path

from cowork_to_code_bridge.mcp_operations import MCPServer


def test_cancellation_pre_execution():
    """Test cancelling an operation before it starts executing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        server = MCPServer(bridge_root=bridge_root)

        # Escalate a request (stays in queue if not picked up)
        escalate_result = server._tool_escalate({
            "request": "This will be cancelled before running",
            "wait_seconds": 0  # Return immediately
        })

        operation_id = escalate_result.get("operation_id")
        assert operation_id is not None

        # Verify operation is queued
        status_before = server._tool_get_status({"operation_id": operation_id})
        assert status_before["status"] == "queued"

        # Cancel it
        cancel_result = server._tool_cancel({
            "operation_id": operation_id,
            "reason": "Test: cancelling pre-execution"
        })

        assert cancel_result["status"] == "cancelled"
        assert cancel_result["reason"] == "Test: cancelling pre-execution"

        # Verify request file is deleted
        queue_file = bridge_root / "to_cowork" / f"{operation_id}.json"
        assert not queue_file.exists()

        print("✅ Pre-execution cancellation: PASS")


def test_cancellation_post_execution():
    """Test cancelling an operation that already completed (idempotent)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        server = MCPServer(bridge_root=bridge_root)

        operation_id = "test_completed_op_001"

        # Create a fake result file (simulating completed operation)
        results_dir = bridge_root / "cowork_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        result_file = results_dir / f"{operation_id}.json"
        result_file.write_text(json.dumps({
            "status": "completed",
            "output": "Operation already finished"
        }))

        # Try to cancel it
        cancel_result = server._tool_cancel({
            "operation_id": operation_id,
            "reason": "Test: cancelling post-execution"
        })

        # Should be idempotent (no error, just no-op)
        assert cancel_result["status"] == "completed"
        assert "already completed" in cancel_result["message"].lower()

        # Result file still exists
        assert result_file.exists()

        print("✅ Post-execution cancellation (idempotent): PASS")


def test_cancellation_during_execution():
    """Test cancelling an operation in progress (sets cancellation flag)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        server = MCPServer(bridge_root=bridge_root)

        operation_id = "test_executing_op_001"

        # Create operation state file (simulating in-progress operation)
        ops_dir = bridge_root / "operations"
        ops_dir.mkdir(parents=True, exist_ok=True)
        op_file = ops_dir / f"{operation_id}.json"
        op_state = {
            "operation_id": operation_id,
            "status": "executing",
            "created_at": time.time(),
            "request": "Long-running task",
            "metrics": {
                "tool_calls": 5,
                "tool_call_log": [],
            },
            "execution_details": {
                "started_at": time.time(),
                "pid": 12345
            }
        }
        op_file.write_text(json.dumps(op_state))

        # Cancel it
        cancel_result = server._tool_cancel({
            "operation_id": operation_id,
            "reason": "Test: cancelling during execution"
        })

        assert cancel_result["status"] == "cancelling"
        assert "SIGTERM" in cancel_result["message"]

        # Verify cancellation flag was set
        updated_op_state = json.loads(op_file.read_text())
        assert updated_op_state["cancelled"] is True
        assert updated_op_state["cancel_reason"] == "Test: cancelling during execution"
        assert "cancelled_at" in updated_op_state

        print("✅ During-execution cancellation (SIGTERM signaled): PASS")


def test_cancellation_idempotent():
    """Test that cancelling the same operation twice is safe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        server = MCPServer(bridge_root=bridge_root)

        operation_id = "test_idempotent_cancel_001"

        # Create operation state
        ops_dir = bridge_root / "operations"
        ops_dir.mkdir(parents=True, exist_ok=True)
        op_file = ops_dir / f"{operation_id}.json"
        op_state = {
            "operation_id": operation_id,
            "status": "executing",
            "created_at": time.time(),
            "request": "Task",
        }
        op_file.write_text(json.dumps(op_state))

        # First cancellation
        result1 = server._tool_cancel({
            "operation_id": operation_id,
            "reason": "First cancellation"
        })
        assert result1["status"] == "cancelling"

        # Second cancellation (should be idempotent)
        result2 = server._tool_cancel({
            "operation_id": operation_id,
            "reason": "Second cancellation"
        })
        assert result2["status"] == "cancelling"

        # Both should succeed without errors
        print("✅ Idempotent cancellation: PASS")


def test_cancellation_unknown_operation():
    """Test cancelling a non-existent operation (safe no-op)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        server = MCPServer(bridge_root=bridge_root)

        cancel_result = server._tool_cancel({
            "operation_id": "nonexistent_operation",
            "reason": "Test: cancelling unknown op"
        })

        # Should return unknown status, not error
        assert cancel_result["status"] == "unknown"
        assert "nothing to cancel" in cancel_result["message"].lower()

        print("✅ Unknown operation cancellation (safe): PASS")


def test_loop_detection_in_metrics():
    """Test that loop detection correctly identifies repeated tool calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge_root = Path(tmpdir)
        server = MCPServer(bridge_root=bridge_root)

        # Create operation with repeated tool calls
        operation_id = "test_loop_detection_001"
        ops_dir = bridge_root / "operations"
        ops_dir.mkdir(parents=True, exist_ok=True)
        op_file = ops_dir / f"{operation_id}.json"

        # Simulate 3 identical tool calls (triggers loop detection)
        op_state = {
            "operation_id": operation_id,
            "status": "executing",
            "created_at": time.time(),
            "request": "Task with loop",
            "metrics": {
                "tool_calls": 3,
                "tool_call_log": [
                    {"tool": "search_docs", "args": {"query": "foo"}, "ts": 1.0},
                    {"tool": "search_docs", "args": {"query": "foo"}, "ts": 2.0},
                    {"tool": "search_docs", "args": {"query": "foo"}, "ts": 3.0},
                ],
                "api_spend_estimate": 0.02,
                "memory_mb": 128,
                "cpu_percent": 15,
            }
        }
        op_file.write_text(json.dumps(op_state))

        # Get status with metrics extraction
        status = server._tool_get_status({"operation_id": operation_id})

        assert "metrics" in status
        assert status["metrics"]["tool_calls"] == 3
        assert status["metrics"]["repeated_calls"] is not None
        assert "search_docs" in status["metrics"]["repeated_calls"]
        assert status["metrics"]["repeated_calls"]["search_docs"] == 3

        print("✅ Loop detection in metrics: PASS")


if __name__ == "__main__":
    print("\nRunning cancellation tests...\n")
    test_cancellation_pre_execution()
    test_cancellation_post_execution()
    test_cancellation_during_execution()
    test_cancellation_idempotent()
    test_cancellation_unknown_operation()
    test_loop_detection_in_metrics()
    print("\n✅ All cancellation tests PASSED!\n")
