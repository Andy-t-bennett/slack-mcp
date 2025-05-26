## Installation

1. Clone this repository
2. Install dependencies: `uv sync`
3. Copy `config.yaml.example` to `config.yaml` and add your Slack token
4. Add to your Cursor MCP config (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "slack": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/path/to/your/slack-mcp"
    }
  }
}
```
```

The `uv` approach is probably best since it handles dependencies automatically and is becoming the standard for Python projects.