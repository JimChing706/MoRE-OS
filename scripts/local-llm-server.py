#!/usr/bin/env python3
"""
本地 LLM API 服务器 - 模拟 Anthropic API
将请求转发到 LM Studio，解决无法访问 Anthropic 的问题
"""

from flask import Flask, request, jsonify
import requests
import sys
import os

app = Flask(__name__)

LM_STUDIO_URL = "http://localhost:1234/v1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

@app.route('/v1/models', methods=['GET', 'POST'])
def models():
    try:
        resp = requests.get(f"{LM_STUDIO_URL}/models", timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/v1/messages', methods=['POST'])
def messages():
    try:
        data = request.json
        model = data.get('model', 'qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled')

        messages = data.get('messages', [])
        if messages:
            last_message = messages[-1].get('content', '')
        else:
            last_message = ''

        lm_data = {
            "model": model,
            "messages": [{"role": "user", "content": last_message}],
            "temperature": data.get('temperature', 0.7),
            "max_tokens": data.get('max_tokens', 4096)
        }

        resp = requests.post(
            f"{LM_STUDIO_URL}/chat/completions",
            json=lm_data,
            timeout=300
        )

        result = resp.json()

        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message'].get('content', '')

            return jsonify({
                "id": f"msg_{os.urandom(8).hex()}",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": content
                    }
                ],
                "model": model,
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": result.get('usage', {}).get('prompt_tokens', 0),
                    "output_tokens": result.get('usage', {}).get('completion_tokens', 0)
                }
            }), 200
        else:
            return jsonify({"error": "No response from model"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    try:
        data = request.json
        resp = requests.post(
            f"{LM_STUDIO_URL}/chat/completions",
            json=data,
            timeout=300
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "proxy": "local-llm"})

if __name__ == '__main__':
    print(f"启动本地 LLM API 服务器: http://localhost:{PORT}")
    print(f"转发到: {LM_STUDIO_URL}")
    print("")
    print("配置 Claude Code:")
    print(f"  export ANTHROPIC_API_BASE=http://localhost:{PORT}")
    print(f"  export ANTHROPIC_API_KEY=sk-ant-api03-local-proxy-key")
    print("")

    app.run(host='localhost', port=PORT, debug=False)