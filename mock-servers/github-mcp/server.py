"""Mock MCP Server: GitHub — simulates GitHub tools for semantic discovery testing.

Serves MCP over streamable HTTP transport at /mcp (MCP 2025-03-26 spec).
Gateway crawls tools/list via POST /mcp during server registration.
"""
import asyncio
import contextlib
import uvicorn
from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

mcp = FastMCP("github-mcp")


@mcp.tool()
def create_issue(repo: str, title: str, body: str, labels: list[str] = None) -> dict:
    """
    Creates a new issue in a GitHub repository.
    Use this tool to report bugs, request features, or track tasks in GitHub.
    """
    return {"status": "created", "issue_number": 42,
            "url": f"https://github.com/{repo}/issues/42", "title": title}


@mcp.tool()
def list_pull_requests(repo: str, state: str = "open") -> list[dict]:
    """
    Lists pull requests in a GitHub repository.
    Returns open or closed pull requests with title, author and status.
    Use to see what code changes are pending review or recently merged.
    """
    return [
        {"number": 101, "title": "feat: add semantic search", "state": state, "author": "alice"},
        {"number": 99,  "title": "fix: timeout handling",    "state": state, "author": "bob"},
    ]


@mcp.tool()
def get_repository_info(repo: str) -> dict:
    """
    Returns metadata about a GitHub repository.
    Includes description, language, star count and last commit date.
    """
    return {"name": repo, "description": "Mock repository for PoC",
            "language": "Python", "stars": 128, "last_commit": "2025-04-01"}


@mcp.tool()
def search_code(query: str, repo: str = None) -> list[dict]:
    """
    Searches for code across GitHub repositories using a text query.
    Returns file paths and snippets matching the search term.
    Optionally scoped to a specific repository.
    """
    return [{"file": "src/main.py", "line": 42, "snippet": f"# matches: {query}"}]


async def health(request):
    return JSONResponse({"status": "healthy"})


session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    stateless=True,
)


@contextlib.asynccontextmanager
async def lifespan(app):
    async with session_manager.run():
        yield


async def handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", endpoint=health),
        Mount("/mcp", app=handle_mcp),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
