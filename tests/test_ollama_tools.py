import asyncio
from synthia.core.llm.router import router
from synthia.core.tools import registry, load_skills
load_skills()

async def main():
    router.set_mode('manual', 'local-qwen')
    cfg = router._cfg('local-qwen')
    prov = router._provider(cfg)
    messages = [
        {
            'role': 'system',
            'content': (
                'You are Synthia. To take action, you MUST use tools. Either invoke native function calls or output:\n'
                'Action: <tool_name>\n'
                'Action Input: {"param": "value"}\n'
            )
        },
        {'role': 'user', 'content': 'List files in workspace using list_directory'}
    ]
    res = await prov.chat(messages, registry.schemas())
    print('res:', res)

if __name__ == '__main__':
    asyncio.run(main())
