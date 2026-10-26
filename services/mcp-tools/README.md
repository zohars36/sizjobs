# services/mcp-tools

MCP server exposing the tools Hermes uses (job search, email, storage, ...).
Python, managed with `uv`.

Every AWS dependency has a local stand-in in Part A (SeaweedFS for S3, the `.env`
for SSM).
