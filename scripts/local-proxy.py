#!/usr/bin/env python3
"""
本地 API 代理 - 将 Claude Code 请求转发到 LM Studio
解决无法直接访问 Anthropic API 的问题
"""

import http.server
import urllib.request
import urllib.error
import json
import sys
import os

LM_STUDIO_URL = "http://localhost:1234/v1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        try:
            req = urllib.request.Request(
                f"{LM_STUDIO_URL}{self.path}",
                data=body,
                headers={k: v for k, v in self.headers.items() if k.lower() not in ['host', 'connection']}
            )

            with urllib.request.urlopen(req, timeout=300) as response:
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(response.read())

        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        if self.path == '/v1/models':
            try:
                req = urllib.request.Request(f"{LM_STUDIO_URL}{self.path}")
                with urllib.request.urlopen(req) as response:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(response.read())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[代理] {args[0]}")

if __name__ == '__main__':
    print(f"启动本地代理: http://localhost:{PORT} -> {LM_STUDIO_URL}")
    print("Claude Code 可以通过设置 ANTHROPIC_API_BASE=http://localhost:8000 来使用")
    server = http.server.HTTPServer(('localhost', PORT), ProxyHandler)
    server.serve_forever()