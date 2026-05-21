#!/usr/bin/env python3
"""
LM Studio 聊天工具 - 直接调用本地模型
用法: python lmstudio-chat.py "问题"
"""

import sys
import json
import urllib.request
import urllib.error

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
DEFAULT_MODEL = "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"

def chat(model, message):
    data = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    req = urllib.request.Request(
        LM_STUDIO_URL,
        data=json.dumps(data).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer dummy-key'
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        return f"错误: {e.code} - {e.reason}"
    except Exception as e:
        return f"错误: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python lmstudio-chat.py <消息> [模型]")
        sys.exit(1)

    message = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL

    result = chat(model, message)
    print(result)