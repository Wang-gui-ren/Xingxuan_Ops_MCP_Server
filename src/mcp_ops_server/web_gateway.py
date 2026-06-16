from __future__ import annotations

import argparse
import os

from mcp_ops_server.branding import PRODUCT_NAME, get_prefixed_env
from mcp_ops_server.config import WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV, default_web_gateway_options_config_path
from mcp_ops_server.web.gateway import DEFAULT_GATEWAY_HOST, DEFAULT_GATEWAY_PORT, serve_gateway


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Run the {PRODUCT_NAME} hosted B/S approval/config gateway.")
    parser.add_argument(
        "--host",
        default=get_prefixed_env("TMP_MCP_GATEWAY_HOST", DEFAULT_GATEWAY_HOST),
        help=f"Bind host, default: {DEFAULT_GATEWAY_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(get_prefixed_env("TMP_MCP_GATEWAY_PORT", DEFAULT_GATEWAY_PORT)),
        help=f"Bind port, default: {DEFAULT_GATEWAY_PORT}.",
    )
    parser.add_argument(
        "--options-file",
        default=get_prefixed_env(WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV) or str(default_web_gateway_options_config_path()),
        help="Gateway options JSON file, default: xingxuan-mcp/config/web_gateway.json.",
    )
    return parser


def run(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    serve_gateway(host=args.host, port=args.port, options_file=args.options_file)


if __name__ == "__main__":
    run()
