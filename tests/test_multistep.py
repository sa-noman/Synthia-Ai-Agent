import asyncio
from pathlib import Path
from synthia.core.llm.router import router
from synthia.core.agent import agent
from synthia.core.tools import load_skills

load_skills()

async def main():
    agent.reset('multi_step')
    router.set_mode('manual', 'local-qwen')
    cmd = 'Create a file in workspace named greeting.txt with text "Hello Synthia", then read it back.'
    reply = await agent.run(cmd, session='multi_step', source='test')
    print('FINAL REPLY:\n', reply)
    print('\nHISTORY STEPS:')
    for m in agent.histories.get('multi_step', []):
        r = m.get('role')
        if r == 'tool':
            print('TOOL [', m.get('name'), ']:', m.get('content')[:120])
        elif r == 'assistant':
            print('ASSISTANT:', (m.get('content') or m.get('tool_calls')))

    test_file = Path('./workspace/greeting.txt')
    assert test_file.exists(), "greeting.txt was not created!"
    print("\nVerified greeting.txt exists on disk with content:", test_file.read_text(encoding="utf-8"))
    test_file.unlink(missing_ok=True)
    print("ALL MULTI-STEP VERIFICATIONS PASSED!")

if __name__ == '__main__':
    asyncio.run(main())
