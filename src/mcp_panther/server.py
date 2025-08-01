import logging
import os
import signal
import sys
from importlib.metadata import version

import click
from fastmcp import FastMCP

# Server name
MCP_SERVER_NAME = "mcp-panther"

# Get log level from environment variable, default to WARNING if not set
log_level_name = os.environ.get("LOG_LEVEL", "WARNING")

# Convert string log level to logging constant
log_level = getattr(logging, log_level_name.upper(), logging.DEBUG)


# Configure logging
def configure_logging(log_file: str | None = None, *, force: bool = False) -> None:
    """Configure logging to stderr or the specified file.

    This also reconfigures the ``FastMCP`` logger so that all FastMCP output
    uses the same handler as the rest of the application.
    """

    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(os.path.expanduser(log_file))
    else:
        handler = logging.StreamHandler(sys.stderr)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[handler],
        force=force,
    )

    # Ensure FastMCP logs propagate to the root logger
    fastmcp_logger = logging.getLogger("FastMCP")
    for hdlr in list(fastmcp_logger.handlers):
        fastmcp_logger.removeHandler(hdlr)
    fastmcp_logger.propagate = True
    fastmcp_logger.setLevel(log_level)


configure_logging(os.environ.get("MCP_LOG_FILE"))
logger = logging.getLogger(MCP_SERVER_NAME)

# Support multiple import paths to accommodate different execution contexts:
# 1. When running as a binary, uvx expects relative imports
# 2. When running with MCP inspector: `uv run mcp dev src/mcp_panther/server.py`
# 3. When installing: `uv run mcp install src/mcp_panther/server.py`
try:
    from panther_mcp_core.prompts.registry import register_all_prompts
    from panther_mcp_core.resources.registry import register_all_resources
    from panther_mcp_core.tools.registry import register_all_tools
except ImportError:
    from .panther_mcp_core.prompts.registry import register_all_prompts
    from .panther_mcp_core.resources.registry import register_all_resources
    from .panther_mcp_core.tools.registry import register_all_tools

# Server dependencies
deps = [
    "gql[aiohttp]",
    "aiohttp",
]

# Create the MCP server
mcp = FastMCP(MCP_SERVER_NAME, dependencies=deps)

# Register all tools with MCP using the registry
register_all_tools(mcp)
# Register all prompts with MCP using the registry
register_all_prompts(mcp)
# Register all resources with MCP using the registry
register_all_resources(mcp)


def handle_signals():
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    # SIGHUP is not available on Windows
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, signal_handler)


@click.command()
@click.version_option(version("mcp-panther"), "--version", "-v")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default=os.environ.get("MCP_TRANSPORT", default="stdio"),
    help="Transport type (stdio or streamable-http)",
)
@click.option(
    "--port",
    default=int(os.environ.get("MCP_PORT", default="3000")),
    help="Port to use for streamable HTTP transport",
)
@click.option(
    "--host",
    default=os.environ.get("MCP_HOST", default="127.0.0.1"),
    help="Host to bind to for streamable HTTP transport",
)
@click.option(
    "--log-file",
    type=click.Path(),
    default=os.environ.get("MCP_LOG_FILE"),
    help="Write logs to this file instead of stderr",
)
def main(transport: str, port: int, host: str, log_file: str | None):
    """Run the Panther MCP server with the specified transport"""
    # Set up signal handling
    handle_signals()

    # Reconfigure logging if a log file is provided
    if log_file:
        configure_logging(log_file, force=True)

    major = sys.version_info.major
    minor = sys.version_info.minor
    micro = sys.version_info.micro

    logger.info(f"Python {major}.{minor}.{micro}")

    if transport == "streamable-http":
        logger.info(
            f"Starting Panther MCP Server with streamable HTTP transport on {host}:{port}"
        )

        try:
            mcp.run(transport="streamable-http", host=host, port=port)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, forcing immediate exit")
            sys.exit(0)
    else:
        logger.info("Starting Panther MCP Server with stdio transport")
        # Let FastMCP handle all the asyncio details internally
        mcp.run()
