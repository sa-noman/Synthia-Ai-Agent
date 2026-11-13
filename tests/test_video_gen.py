import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import subprocess
from synthia.config import hidden_subprocess_kwargs
from synthia.skills.media_skill import create_short_video

async def test():
    print("Testing create_short_video...")
    res = await create_short_video(
        topic="ভবিষ্যতের এআই রোবট",
        style="cartoon",
        duration_sec=15,
        voice="female",
        format="portrait"
    )
    print("Tool Response:\n", res[:300], "...")
    assert "সফলভাবে তৈরি করা হয়েছে" in res, "Expected success response"

    # Find the latest reel in workspace/videos
    videos = sorted(Path("workspace/videos").glob("reel_*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    assert len(videos) > 0, "No reel video found"
    latest_vid = videos[0]
    print(f"Latest video: {latest_vid} ({latest_vid.stat().st_size / 1024:.1f} KB)")
    assert latest_vid.stat().st_size > 50000, "Video file too small"

    # Verify with ffprobe
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_name,width,height",
        "-of", "json",
        str(latest_vid)
    ]
    p = subprocess.run(probe_cmd, capture_output=True, text=True, **hidden_subprocess_kwargs())
    print("ffprobe stdout:\n", p.stdout)
    assert "h264" in p.stdout, "Video stream missing h264 codec"
    assert "aac" in p.stdout, "Audio stream missing aac codec"
    print("ALL ASSERTIONS PASSED! Video generated successfully!")

if __name__ == "__main__":
    asyncio.run(test())
