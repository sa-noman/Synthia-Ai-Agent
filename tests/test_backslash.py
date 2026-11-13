import json
import ast
import re

raw = '{"path": "D:\\Personal\\Zarbis Ai\\workspace"}'
try:
    v = json.loads(raw)
    print("json.loads success:", v)
except Exception as e:
    print("json.loads failed:", e)

# Unescaped windows path:
raw_unescaped = '{"path": "D:\Personal\Zarbis Ai\workspace"}'
try:
    v = json.loads(raw_unescaped)
    print("json.loads unescaped:", v)
except Exception as e:
    print("json.loads unescaped failed:", e)
    # Fix unescaped backslashes:
    fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', raw_unescaped)
    print("fixed json:", json.loads(fixed))
