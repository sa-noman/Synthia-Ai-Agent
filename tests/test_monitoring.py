import asyncio
from synthia.core.history import task_history
from synthia.core.monitoring import errors, get_diagnostics, get_gpu_metrics, get_ollama_info, get_system_telemetry


def test_system_telemetry():
    tele = get_system_telemetry()
    assert "cpu_pct" in tele
    assert "ram" in tele
    assert "disks" in tele
    print("CPU load:", tele["cpu_pct"], "%")
    print("RAM used:", tele["ram"]["used_gb"], "GB /", tele["ram"]["total_gb"], "GB")

    gpu = get_gpu_metrics()
    print("GPU metrics detected:", gpu)
    if gpu:
        assert "RTX 3060 Ti" in gpu["name"] or "NVIDIA" in gpu["name"]
        print(f"GPU: {gpu['name']} | Util: {gpu['util_pct']}% | VRAM: {gpu['vram_used_mb']}/{gpu['vram_total_mb']} MB | Temp: {gpu['temp_c']}°C")


def test_task_history():
    tid = "test_task_123"
    task_history.start_task(tid, "Test prompt", source="test", session="test", model="local-qwen")
    task_history.log_tool_start(tid, "step_1", "list_directory", {"path": "workspace"})
    task_history.log_tool_end(tid, "step_1", "list_directory", True, "workspace/notes.txt", 42)
    task_history.finish_task(tid, "Done test", status="completed")

    fetched = task_history.get_task(tid)
    assert fetched is not None
    assert fetched["status"] == "completed"
    assert len(fetched["tool_calls"]) == 1
    assert fetched["tool_calls"][0]["tool"] == "list_directory"
    assert fetched["duration_ms"] >= 0
    print("Task history recorded and retrieved successfully:", fetched["task_id"])


def test_errors():
    errors.log("TestError", "This is a test warning", component="test", level="warn")
    err_list = errors.list_errors(5)
    assert any(e["title"] == "TestError" for e in err_list)
    print("Error store logged and retrieved:", len(err_list), "entries")


async def test_async_monitoring():
    ollama_data = await get_ollama_info()
    print("Ollama online:", ollama_data["online"])
    print("Ollama models installed:", [m["name"] for m in ollama_data["models"]])
    print("Ollama models running in VRAM:", [m["name"] for m in ollama_data["running"]])
    assert ollama_data["online"] is True
    assert any("qwen" in m["name"] or "gemma" in m["name"] for m in ollama_data["models"])

    diag = await get_diagnostics()
    assert "system" in diag
    assert "ollama" in diag
    assert "recent_errors" in diag
    print("Consolidated diagnostics check: PASSED")


if __name__ == "__main__":
    test_system_telemetry()
    test_task_history()
    test_errors()
    asyncio.run(test_async_monitoring())
    print("\nALL MONITORING & AGENT MANAGEMENT TESTS PASSED SUCCESSFULLY!")
