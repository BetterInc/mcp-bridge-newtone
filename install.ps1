# Install this extension into BetterFL MCP Bridge (development copy).
python (Join-Path $PSScriptRoot "build.py")
$dest = Join-Path $env:LOCALAPPDATA "BetterFL\extensions\mcp-bridge-newtone"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $PSScriptRoot "manifest.json"), (Join-Path $PSScriptRoot "extension.py") $dest -Force
"installed to $dest (run fl_reload or restart FL)"
