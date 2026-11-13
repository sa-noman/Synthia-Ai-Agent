"""Media squad tools unit & integration test."""
import asyncio
import os
import sys
from pathlib import Path

# Add root to pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent))

from synthia.core.tools import load_skills, registry
from synthia.skills.media_skill import generate_image, media_info, _get_workspace_dir


async def main():
    print("=== Testing Media Tools ===")
    load_skills()
    assert "media" in registry.by_category(), "Category 'media' not found in registry"
    tools = registry.by_category()["media"]
    print("Registered media tools:", tools)
    assert "generate_image" in tools
    assert "capture_screen" in tools
    assert "analyze_image" in tools
    assert "media_info" in tools

    # Test directory creation
    img_dir = _get_workspace_dir("images")
    assert img_dir.exists(), f"Image dir {img_dir} was not created"

    # Test generate_image
    print("Testing generate_image with short prompt...")
    res = await generate_image(prompt="A minimalist glowing cyan circuit board icon", filename="test_icon.png", width=512, height=512)
    print("Generate image result:\n", res)
    assert "✅" in res or "ERROR" not in res, "generate_image returned an error"
    
    test_file = img_dir / "test_icon.png"
    assert test_file.exists(), f"File {test_file} was not written"
    assert test_file.stat().st_size > 500, "Generated file too small"
    print(f"Verified image created at {test_file} ({test_file.stat().st_size} bytes)")

    # Test media_info
    info = media_info("workspace/images/test_icon.png")
    print("Media info result:\n", info)
    assert "রেজুলেশন" in info or "512" in info or "সাইজ" in info

    print("=== ALL MEDIA TESTS PASSED! ===")


if __name__ == "__main__":
    asyncio.run(main())
