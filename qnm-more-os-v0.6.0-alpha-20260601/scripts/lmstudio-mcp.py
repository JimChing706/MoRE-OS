#!/usr/bin/env python3
"""
LM Studio MCP 工具 - 让 Claude Code 通过工具调用本地模型
"""

import sys
import json
import urllib.request
import urllib.error

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"

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
    except Exception as e:
        return f"错误: {str(e)}"

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break

        try:
            request_data = json.loads(line)

            if request_data.get('method') == 'tools/list':
                response = {
                    "jsonrpc": "2.0",
                    "id": request_data.get('id'),
                    "result": {
                        "tools": [
                            {
                                "name": "lmstudio_chat",
                                "description": "使用本地 LM Studio 模型进行对话",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "message": {
                                            "type": "string",
                                            "description": "要发送的消息"
                                        },
                                        "model": {
                                            "type": "string",
                                            "description": "模型名称 (默认: qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled)"
                                        }
                                    },
                                    "required": ["message"]
                                }
                            }
                        ]
                    }
                }
                print(json.dumps(response), flush=True)

            elif request_data.get('method') == 'tools/call':
                tool_name = request_data['params']['name']
                args = request_data['params'].get('arguments', {})

                if tool_name == 'lmstudio_chat':
                    model = args.get('model', 'qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled')
                    message = args.get('message', '')

                    result = chat(model, message)

                    response = {
                        "jsonrpc": "2.0",
                        "id": request_data.get('id'),
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result
                                }
                            ]
                        }
                    }
                    print(json.dumps(response), flush=True)

        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32600,
                    "message": str(e)
                }
            }
            print(json.dumps(error_response), flush=True)

if __name__ == "__main__":
    main()