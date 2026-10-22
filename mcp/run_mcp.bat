@echo off
rem Engineering Research Workbench MCP (stdio) launcher.
rem Run from the workbench repo root so that `mcp` resolves to this package.
setlocal
pushd "%~dp0.."
python -m mcp.server %*
popd
