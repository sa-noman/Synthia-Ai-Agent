import asyncio
from pathlib import Path
from synthia.core.loop_guard import LoopGuard
from synthia.skills.code_skill import evaluate_math, execute_python
from synthia.skills.patch_skill import edit_file, apply_patch
from synthia.skills.files import organize_folder


def test_loop_guard():
    lg = LoopGuard()
    v1 = lg.check_call("read_file", {"path": "test.txt"})
    assert not v1.blocked and not v1.warned
    v2 = lg.check_call("read_file", {"path": "test.txt"})
    assert not v2.blocked
    v3 = lg.check_call("read_file", {"path": "test.txt"})
    assert v3.warned or v3.blocked
    v4 = lg.check_call("read_file", {"path": "test.txt"})
    assert v4.blocked
    print("LoopGuard identical call test: PASSED")

    # Test ping-pong
    lg.reset()
    lg.check_call("toolA", {})
    lg.check_call("toolB", {})
    lg.check_call("toolA", {})
    v_pong = lg.check_call("toolB", {})
    assert v_pong.warned or v_pong.blocked
    print("LoopGuard ping-pong test: PASSED")


def test_evaluate_math():
    res = evaluate_math("sqrt(256) + 10")
    assert "26.0" in res or "26" in res
    print("Evaluate math test: PASSED ->", res)


async def test_async_features():
    code_res = await execute_python('import math\nprint(f"Sin: {math.sin(math.pi/2)}")')
    assert "Sin: 1.0" in code_res
    print("Execute safe python test: PASSED ->", code_res.strip())

    ws = Path("./workspace")
    ws.mkdir(parents=True, exist_ok=True)
    test_f = ws / "test_edit.txt"
    test_f.write_text("Line 1\nHello World\nLine 3", encoding="utf-8")

    edit_res = await edit_file("workspace/test_edit.txt", "Hello World", "Hello Synthia")
    assert "OK" in edit_res
    assert "Hello Synthia" in test_f.read_text(encoding="utf-8")
    print("Edit file test: PASSED ->", edit_res)

    # Test apply patch
    patch_text = "@@ -1,3 +1,3 @@\n Line 1\n-Hello Synthia\n+Hello OpenJarvis\n Line 3"
    patch_res = await apply_patch("workspace/test_edit.txt", patch_text)
    assert "OK" in patch_res
    assert "Hello OpenJarvis" in test_f.read_text(encoding="utf-8")
    print("Apply patch test: PASSED ->", patch_res)
    test_f.unlink(missing_ok=True)

    org_res = await organize_folder("workspace", dry_run=True)
    print("Organize folder dry-run test: PASSED ->", org_res)


if __name__ == "__main__":
    test_loop_guard()
    test_evaluate_math()
    asyncio.run(test_async_features())
    print("\nALL FEATURE 1 TESTS PASSED SUCCESSFULLY!")
