"""Master Verification Test Suite for Synthia + OpenJarvis Integration.
Runs comprehensive tests across all 4 integrated capability areas.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from synthia.channels.manager import channel_manager
from synthia.core.agent import agent
from synthia.core.history import task_history
from synthia.core.llm.router import router
from synthia.core.loop_guard import LoopGuard
from synthia.core.monitoring import get_diagnostics, get_gpu_metrics, get_ollama_info, get_system_telemetry
from synthia.core.safety import safety
from synthia.core.tools import load_skills, registry
from synthia.server import ACCESS_TOKEN, app
from synthia.skills.code_skill import evaluate_math, execute_python
from synthia.skills.files import organize_folder
from synthia.skills.patch_skill import apply_patch, edit_file
from synthia.skills.remote_skill import remote_status
from synthia.voice.manager import voice
from synthia.voice.mic import has_microphone
from synthia.voice.tts import synthesize


def test_ast_all_python_files():
    root = Path(".")
    py_files = list(root.glob("synthia/**/*.py"))
    assert len(py_files) >= 20, "Expected at least 20 Python files in synthia package"
    for pf in py_files:
        content = pf.read_text(encoding="utf-8")
        ast.parse(content, filename=str(pf))
    print(f"1. Python AST Audit: PASSED ({len(py_files)} files checked, 0 errors)")


def test_tool_registry():
    load_skills()
    cats = registry.by_category()
    print("2. Tool Registry Check:")
    print(f"   Total tools: {len(registry.tools)}")
    print(f"   Categories: {list(cats.keys())}")
    assert len(registry.tools) >= 29
    assert "remote" in cats
    assert "system" in cats
    assert "files" in cats


def test_loop_guard_and_tools():
    # Loop guard
    lg = LoopGuard()
    lg.check_call("tool1", {"a": 1})
    lg.check_call("tool1", {"a": 1})
    v = lg.check_call("tool1", {"a": 1})
    assert v.warned or v.blocked

    # Math
    math_res = evaluate_math("2**10 + sqrt(100)")
    assert "1034" in math_res
    print("3. LoopGuard & Math: PASSED")


async def test_file_and_code_skills():
    # Safe python execution
    py_out = await execute_python("print('Hello from test')")
    assert "Hello from test" in py_out

    # File editing
    ws = Path("./workspace")
    ws.mkdir(parents=True, exist_ok=True)
    f = ws / "master_test_file.txt"
    f.write_text("Alpha\nBeta\nGamma", encoding="utf-8")

    e_res = await edit_file("workspace/master_test_file.txt", "Beta", "Beta-Updated")
    assert "OK" in e_res
    assert "Beta-Updated" in f.read_text(encoding="utf-8")

    # Patch
    patch = "@@ -1,3 +1,3 @@\n Alpha\n-Beta-Updated\n+Beta-Final\n Gamma"
    p_res = await apply_patch("workspace/master_test_file.txt", patch)
    assert "OK" in p_res
    assert "Beta-Final" in f.read_text(encoding="utf-8")
    f.unlink(missing_ok=True)

    # Dry-run organize
    org_res = await organize_folder("workspace", dry_run=True)
    assert "Plan for" in org_res or "No loose files" in org_res
    print("4. Code & Patch & Organize Tools: PASSED")


async def test_ollama_agent_react():
    agent.reset("master_test")
    router.set_mode("manual", "local-qwen")
    prompt = "Create a file in workspace named test_react.txt with text 'Synthia Verified', then read it."
    reply = await agent.run(prompt, session="master_test", source="test")
    assert reply, "Expected non-empty reply"

    rf = Path("./workspace/test_react.txt")
    assert rf.exists(), "test_react.txt was not created"
    assert "Synthia Verified" in rf.read_text(encoding="utf-8")
    rf.unlink(missing_ok=True)
    print("5. Local Ollama Multi-Step ReAct Execution: PASSED")


async def test_voice_stack():
    has_mic = has_microphone()
    assert isinstance(has_mic, bool)

    tts = await synthesize("Voice system check.", "female")
    assert tts.get("mode") in ("mp3", "url", "b64", "sapi", "browser")

    # PTT check
    await voice.start_ptt()
    assert voice.ptt_active is True
    await voice.stop_ptt()
    assert voice.ptt_active is False
    print("6. Voice Stack & Push-to-Talk: PASSED")


async def test_monitoring_and_history():
    tele = get_system_telemetry()
    assert "cpu_pct" in tele and "ram" in tele

    gpu = get_gpu_metrics()
    print(f"   GPU status: {gpu['name'] if gpu else 'None'} ({gpu['temp_c'] if gpu else 'N/A'}°C)")

    ollama = await get_ollama_info()
    assert ollama["online"] is True

    diag = await get_diagnostics()
    assert "system" in diag and "ollama" in diag

    hist = task_history.list_history(5)
    assert len(hist) > 0, "Expected task history to contain executed tasks"
    print("7. Monitoring, GPU & Task History: PASSED")


async def test_channels_security():
    st = channel_manager.state()
    assert "telegram" in st and "discord" in st

    # Security check on Telegram unauthorized user
    tg = channel_manager.telegram
    tg.allowed_users = {555}
    blocked = []
    async def mock_send(cid, txt, reply_markup=None):
        blocked.append((cid, txt))
        return True
    tg.send_message = mock_send

    import httpx
    async with httpx.AsyncClient() as c:
        await tg._handle_update(c, "https://api.telegram.org/botfake", {
            "update_id": 10,
            "message": {"chat": {"id": 999}, "from": {"id": 999}, "text": "secret"},
        })
    assert len(blocked) == 1
    assert "অননুমোদিত" in blocked[0][1]

    # Stop toggle test
    t_res = await channel_manager.toggle_channel("telegram", False)
    assert t_res["ok"] is True
    print("8. Telegram & Discord Channels Security & Control: PASSED")


def test_fastapi_endpoints():
    client = TestClient(app)

    # 1. Root UI index
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "SYNTHIA" in r_index.text

    # 2. Bootstrap localhost token
    r_boot = client.get("/api/bootstrap")
    assert r_boot.status_code == 200
    token = r_boot.json().get("token")
    assert token == ACCESS_TOKEN

    # 3. State endpoint
    r_state = client.get(f"/api/state?token={token}")
    assert r_state.status_code == 200
    st_json = r_state.json()
    assert "version" in st_json
    assert "channels" in st_json
    assert "task_history" in st_json

    # 4. Agent history endpoint
    r_hist = client.get(f"/api/agent/history?token={token}")
    assert r_hist.status_code == 200
    assert isinstance(r_hist.json(), list)

    # 5. Permissions endpoint
    r_perm = client.get(f"/api/agent/permissions?token={token}")
    assert r_perm.status_code == 200
    assert "tools" in r_perm.json()

    # 6. Ollama info endpoint
    r_ol = client.get(f"/api/system/ollama?token={token}")
    assert r_ol.status_code == 200
    assert r_ol.json()["online"] is True

    # 7. Diagnostics endpoint
    r_diag = client.get(f"/api/system/diagnostics?token={token}")
    assert r_diag.status_code == 200
    assert "system" in r_diag.json()

    # 8. Channel status endpoint
    r_ch = client.get(f"/api/channels/status?token={token}")
    assert r_ch.status_code == 200
    assert "telegram" in r_ch.json()

    # 9. PTT endpoints
    r_ptt1 = client.post(f"/api/voice/ptt_start?token={token}")
    assert r_ptt1.status_code == 200
    r_ptt2 = client.post(f"/api/voice/ptt_stop?token={token}")
    assert r_ptt2.status_code == 200

    print("9. FastAPI Endpoints & UI Verification: PASSED")


if __name__ == "__main__":
    print("=" * 60)
    print("  RUNNING SYNTHIA MASTER INTEGRATION TEST SUITE")
    print("=" * 60)
    test_ast_all_python_files()
    test_tool_registry()
    test_loop_guard_and_tools()
    asyncio.run(test_file_and_code_skills())
    asyncio.run(test_ollama_agent_react())
    asyncio.run(test_voice_stack())
    asyncio.run(test_monitoring_and_history())
    asyncio.run(test_channels_security())
    test_fastapi_endpoints()
    print("=" * 60)
    print("  ALL 9 MASTER INTEGRATION SUITES PASSED WITH ZERO ERRORS!")
    print("=" * 60)
