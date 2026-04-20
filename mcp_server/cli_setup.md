# MCP CLI Setup

MCP server runs at `http://localhost:5001/sse` when Mammon is up.

## Claude Code (auto)
`.mcp.json` in the repo root handles this — no setup needed.
Just `cd Mammon_Clean` and start a session; the server is available.

Or add it globally so it works from any directory:
```
claude mcp add mammon-db --transport sse http://localhost:5001/sse --scope user
```

## Gemini CLI
```
gemini mcp add mammon-db http://localhost:5001/sse
```
Or manually in `~/.gemini/settings.json`:
```json
{
  "mcpServers": {
    "mammon-db": {
      "httpUrl": "http://localhost:5001/sse"
    }
  }
}
```

## Codex CLI (OpenAI)
```
codex mcp add mammon-db --url http://localhost:5001/sse
```
Or manually in `~/.codex/config.yaml`:
```yaml
mcp_servers:
  mammon-db:
    url: http://localhost:5001/sse
```

---

## Project location (host machine)
```
C:\Users\simon\OneDrive\Desktop\Mammon_Clean
```

## MCP server source
```
C:\Users\simon\OneDrive\Desktop\Mammon_Clean\mcp_server\server.py
```

## .mcp.json (Claude Code project scope)
```
C:\Users\simon\OneDrive\Desktop\Mammon_Clean\.mcp.json
```

## Verify it's working
```
claude mcp list
claude "use mammon-db to call list_dbs()"
```
