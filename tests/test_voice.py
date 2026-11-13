import asyncio
from synthia.voice.manager import voice
from synthia.voice.mic import has_microphone
from synthia.voice.tts import synthesize, clean_for_speech


def test_voice_basics():
    mic_found = has_microphone()
    print("Microphone detected on PC:", mic_found)

    cleaned = clean_for_speech("Here is code: ```print(1)``` and link https://google.com")
    print("Cleaned for speech:", cleaned)
    assert "https://google.com" not in cleaned

    st = voice.state()
    assert "mic_on" in st
    assert "ptt_active" in st
    assert "persona" in st
    print("Voice state:", st)


async def test_voice_synthesis_and_ptt():
    # Test TTS synthesis payload
    payload = await synthesize("Hello, testing voice synthesis.", "female")
    print("TTS synthesis payload mode:", payload.get("mode"))
    assert payload.get("mode") in ("url", "b64", "mp3", "sapi", "browser", "none")

    # Test PTT lifecycle
    await voice.start_ptt()
    assert voice.ptt_active is True
    print("PTT started successfully. Current state:", voice.state())

    await voice.stop_ptt()
    print("PTT stopped successfully.")
    assert voice._stop_record.is_set()


if __name__ == "__main__":
    test_voice_basics()
    asyncio.run(test_voice_synthesis_and_ptt())
    print("\nALL VOICE TESTS PASSED SUCCESSFULLY!")
