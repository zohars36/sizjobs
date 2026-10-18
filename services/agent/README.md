# services/agent

Hermes, the job-search agent. Python, managed with `uv`.

Calls the model through LiteLLM and uses tools exposed by `services/mcp-tools`.
Personal data (profile, company list, emails) is read at runtime from the
private bucket and never committed or logged.
