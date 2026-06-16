from __future__ import annotations

from mcp_ops_server.server import create_server


def run() -> None:
    server = create_server()
    server.run()


if __name__ == "__main__":
    run()
