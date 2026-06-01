#!/usr/bin/env python3
"""Standalone runner for Minesweeper Web Game Server

Run this script directly to start the minesweeper web server
without loading the full MoRE OS plugin system.

Access the game at: http://localhost:8081
"""

import sys
import os

# Add parent directory to path for imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, PARENT_DIR)
sys.path.insert(0, os.path.join(PARENT_DIR, 'more_core'))

import asyncio
import uvicorn

from gui_server import create_minesweeper_app


def run_server(host="0.0.0.0", port=8081):
    """Run the FastAPI web server"""
    app = create_minesweeper_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    return server


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
    
    print(f"Starting Minesweeper Web Server on http://{host}:{port}")
    print(f"Open http://{host}:{port} in your browser to play")
    print("Press Ctrl+C to stop the server")
    
    server = run_server(host, port)
    asyncio.run(server.serve())
