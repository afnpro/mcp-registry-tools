"""Mock MCP Server: Jira — simulates Jira tools for semantic discovery testing.

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

mcp = FastMCP("jira-mcp")


@mcp.tool()
def create_ticket(project_key: str, summary: str, description: str,
                  issue_type: str = "Task", priority: str = "Medium") -> dict:
    """
    Creates a new ticket in a Jira project.
    Use to track bugs, tasks, stories or epics in Jira.
    Provide the project key (e.g. PLAT, INFRA), a summary, and optionally
    the issue type and priority.
    """
    return {"key": f"{project_key}-999", "summary": summary, "status": "To Do",
            "url": f"https://jira.example.com/browse/{project_key}-999"}


@mcp.tool()
def get_ticket(ticket_key: str) -> dict:
    """
    Retrieves details of a specific Jira ticket by its key.
    Returns summary, description, status, assignee and comments.
    Example key: PLAT-123
    """
    return {"key": ticket_key, "summary": "Mock ticket for PoC",
            "status": "In Progress", "assignee": "charlie", "priority": "High", "comments": []}


@mcp.tool()
def search_tickets(jql: str, max_results: int = 10) -> list[dict]:
    """
    Searches Jira tickets using JQL (Jira Query Language).
    Use to find tickets by project, status, assignee, sprint or any other criteria.
    Example JQL: project = PLAT AND status = 'In Progress'
    """
    return [{"key": "PLAT-100", "summary": f"Result for: {jql}", "status": "Open"}]


@mcp.tool()
def transition_ticket(ticket_key: str, transition: str) -> dict:
    """
    Moves a Jira ticket to a new workflow status.
    Common transitions: 'In Progress', 'Done', 'In Review', 'Blocked'.
    Use after completing work or updating ticket progress.
    """
    return {"key": ticket_key, "new_status": transition, "success": True}


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
