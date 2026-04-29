#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/setup_mcp.sh [options]

Install Aksi's local MCP server dependencies and print a ready stdio config.

Options:
  --dev                 Install development dependencies too.
  --multilang           Install optional multi-language Tree-sitter grammars.
  --write-config PATH   Write the MCP JSON snippet to PATH.
  --claude-desktop      Merge Aksi into Claude Desktop's macOS config.
  -h, --help            Show this help.

Examples:
  scripts/setup_mcp.sh
  scripts/setup_mcp.sh --write-config .mcp/aksi.json
  scripts/setup_mcp.sh --claude-desktop
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
venv_dir="${repo_dir}/.venv"
install_args=("fastmcp>=3.2" "tree-sitter>=0.25" "tree-sitter-python>=0.25")
write_config=""
setup_claude="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)
      install_args+=("pytest>=8.0")
      shift
      ;;
    --multilang)
      install_args+=("tree-sitter-languages>=1.10; python_version < '3.14'")
      shift
      ;;
    --write-config)
      if [[ $# -lt 2 ]]; then
        echo "Missing path after --write-config" >&2
        exit 2
      fi
      write_config="$2"
      shift 2
      ;;
    --claude-desktop)
      setup_claude="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "${venv_dir}" ]]; then
  python3 -m venv "${venv_dir}"
fi

python_bin="${venv_dir}/bin/python"
"${python_bin}" -m pip install "${install_args[@]}"

config_json="$("${python_bin}" - <<PY
import json
from pathlib import Path

python_bin = Path("${python_bin}")
server = Path("${repo_dir}") / "mcp_server.py"
print(json.dumps({
    "mcpServers": {
        "aksi": {
            "command": str(python_bin),
            "args": [str(server)],
        }
    }
}, indent=2))
PY
)"

if [[ -n "${write_config}" ]]; then
  mkdir -p "$(dirname "${write_config}")"
  printf '%s\n' "${config_json}" > "${write_config}"
  echo "Wrote MCP config snippet to ${write_config}"
else
  echo "MCP config snippet:"
  printf '%s\n' "${config_json}"
fi

if [[ "${setup_claude}" == "true" ]]; then
  claude_config="${HOME}/Library/Application Support/Claude/claude_desktop_config.json"
  mkdir -p "$(dirname "${claude_config}")"
  "${python_bin}" - <<PY
import json
from pathlib import Path

config_path = Path("${claude_config}")
snippet = json.loads("""${config_json}""")
if config_path.exists():
    config = json.loads(config_path.read_text(encoding="utf-8"))
else:
    config = {}
config.setdefault("mcpServers", {})
config["mcpServers"]["aksi"] = snippet["mcpServers"]["aksi"]
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print(f"Updated Claude Desktop config: {config_path}")
PY
fi

echo "Aksi MCP setup complete."
