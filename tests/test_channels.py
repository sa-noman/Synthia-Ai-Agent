import asyncio
from synthia.channels.manager import channel_manager
from synthia.channels.telegram_channel import TelegramChannel
from synthia.channels.discord_channel import DiscordChannel
from synthia.core.safety import safety
from synthia.skills.remote_skill import remote_status, send_remote_notification


def test_channel_manager_basics():
    st = channel_manager.state()
    assert "telegram" in st
    assert "discord" in st
    print("Channel Manager initial state:", st)

    # Test remote skill tool
    skill_st = remote_status()
    assert "telegram" in skill_st
    assert "discord" in skill_st
    print("remote_status tool output:", skill_st)


async def test_telegram_security_and_approvals():
    tg = TelegramChannel()
    tg.bot_token = "mock_test_token"
    tg.allowed_users = {111222333}

    # 1. Test unauthorized user rejection
    unauthorized_update = {
        "update_id": 1,
        "message": {
            "chat": {"id": 999999},
            "from": {"id": 999999, "username": "attacker"},
            "text": "run_command: whoami",
        },
    }
    # Mock send_message to track calls
    sent_msgs = []
    async def mock_send(chat_id, text, reply_markup=None):
        sent_msgs.append((chat_id, text))
        return True
    tg.send_message = mock_send

    import httpx
    async with httpx.AsyncClient() as c:
        await tg._handle_update(c, "https://api.telegram.org/botmock", unauthorized_update)

    assert len(sent_msgs) == 1
    assert sent_msgs[0][0] == 999999
    assert "অননুমোদিত" in sent_msgs[0][1] or "Unauthorized" in sent_msgs[0][1]
    print("Telegram unauthorized rejection: PASSED ->", sent_msgs[0][1])

    # 2. Test interactive approval resolution
    # Create a pending safety request
    loop = asyncio.get_running_loop()
    req_fut = loop.create_future()
    from synthia.core.safety import ConfirmRequest
    req = ConfirmRequest(id="req_test_01", tool="delete_paths", title="Test Delete", details={}, future=req_fut)
    safety._pending["req_test_01"] = req

    # Simulate callback query approve from authorized user
    approve_cb = {
        "update_id": 2,
        "callback_query": {
            "id": "cb_01",
            "from": {"id": 111222333},
            "data": "approve:req_test_01",
        },
    }

    # Mock answerCallbackQuery
    async def mock_post(url, json=None):
        class MockResp:
            status_code = 200
            def json(self): return {"ok": True}
        return MockResp()
    c.post = mock_post

    await tg._handle_update(c, "https://api.telegram.org/botmock", approve_cb)
    assert req_fut.done() is True
    assert req_fut.result() is True
    print("Telegram interactive safety approval: PASSED")


async def test_discord_security():
    dc = DiscordChannel()
    dc.bot_token = "mock_discord_token"
    dc.allowed_users = {"444555666"}

    sent_msgs = []
    async def mock_send(channel_id, text):
        sent_msgs.append((channel_id, text))
        return True
    dc.send_message = mock_send

    # Message from unauthorized user
    msg_unauthorized = {
        "author": {"id": "888999", "bot": False, "username": "stranger"},
        "channel_id": "chan_01",
        "content": "Hello",
    }
    await dc._handle_message(msg_unauthorized)
    assert len(sent_msgs) == 1
    assert "Unauthorized" in sent_msgs[0][1]
    print("Discord unauthorized rejection: PASSED ->", sent_msgs[0][1])


async def test_channel_toggles():
    res = await channel_manager.toggle_channel("telegram", False)
    assert res["ok"] is True
    assert res["state"]["status"] in ("disconnected", "unconfigured")
    print("Channel toggle stop: PASSED")


if __name__ == "__main__":
    test_channel_manager_basics()
    asyncio.run(test_telegram_security_and_approvals())
    asyncio.run(test_discord_security())
    asyncio.run(test_channel_toggles())
    print("\nALL TELEGRAM & DISCORD INTEGRATION TESTS PASSED SUCCESSFULLY!")
