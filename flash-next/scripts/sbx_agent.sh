#!/usr/bin/env bash
# Run a local-model Claude Code agent inside a Docker Sandbox (sbx microVM) on a private clone of a repo.
# The only network the sandbox gets is the model server on the host (Ollama, or vLLM's /v1/messages). Results come back as commits
# on the host git remote "sandbox-<name>".
#
#   sbx_agent.sh create  <repo> <name>              new sandbox: clone mode, only Ollama reachable
#   sbx_agent.sh setup   <name> <command...>        run a setup command with package registries allowed,
#                                                   then remove that access again. Put a Python env at
#                                                   ~/venv and every later step has it on PATH.
#   sbx_agent.sh guide   <name> <file>              install <file> as the agent's ~/.claude/CLAUDE.md
#   sbx_agent.sh run     <name> <model> <specfile> [max_turns]
#                                                   headless agent run; prints Claude Code's JSON result
#   sbx_agent.sh commit  <name> <message>           commit the agent's work inside the sandbox
#   sbx_agent.sh fetch   <name> <repo>              fetch it to the host; prints branch, stat and diff
#   sbx_agent.sh check   <name> <command...>        run tests inside the sandbox (never on the host)
#   sbx_agent.sh rm      <name> <repo>              remove the sandbox and its git remote
#
# Env: MODEL_PORT = the host port of the model server (default 11434, Ollama; e.g. 9110 for Bolt on vLLM),
#      SBX_TEMPLATE = a saved sandbox template to start from (sbx template save), e.g. with tools pre-installed,
#      SBX_CPUS / SBX_MEMORY = sandbox size (default 4 / 8g; sbx's own default is every core and half the RAM),
#      AGENT_EFFORT (reasoning effort sent by Claude Code; some model templates accept only certain values),
#      AGENT_CONTEXT (the model's context window, so Claude Code compacts before overflowing; default 128000),
#      AGENT_FORMAT (json, or stream-json for a full per-turn transcript), AGENT_MAX_TURNS (default 60), AGENT_TIMEOUT_MIN (default 45; the run is killed inside the sandbox).
set -euo pipefail
MODEL_PORT=${MODEL_PORT:-${OLLAMA_PORT:-11434}}
SBX_CPUS=${SBX_CPUS:-4}; SBX_MEMORY=${SBX_MEMORY:-8g}
REGISTRIES="pypi.org,files.pythonhosted.org,registry.npmjs.org,github.com,**.githubusercontent.com"   # github: uv Python downloads
# shell prefix: put ~/venv on PATH when it exists
VENV='mkdir -p "$HOME/.cc-tmp"; export CLAUDE_CODE_TMPDIR="$HOME/.cc-tmp"; [ -n "${AGENT_EFFORT:-}" ] && export CLAUDE_CODE_EFFORT_LEVEL="$AGENT_EFFORT"; if [ -d "$HOME/venv" ]; then export VIRTUAL_ENV="$HOME/venv" PATH="$HOME/venv/bin:$PATH"; fi;'

workdir() {   # the clone's path inside the sandbox
  sbx exec "$1" sh -c 'git rev-parse --show-toplevel 2>/dev/null || pwd'
}

# The built-in claude kit allows Anthropic/Claude endpoints; deny rules win, so the agent can only reach the model.
VENDOR_DENY="anthropic.com,**.anthropic.com,claude.com,**.claude.com,claude.ai,**.claude.ai,claudeusercontent.com,**.claudeusercontent.com"

cmd=${1:?usage: see header}; shift
case "$cmd" in
  create)
    repo=$(cd "${1:?repo}" && git rev-parse --show-toplevel); name=${2:?name}
    sbx create --clone --name "$name" --no-progress --cpus "$SBX_CPUS" --memory "$SBX_MEMORY" \
      ${SBX_TEMPLATE:+-t "$SBX_TEMPLATE" --pull never} \
      --deny-network "$VENDOR_DENY" \
      -e ANTHROPIC_BASE_URL="http://host.docker.internal:$MODEL_PORT" \
      -e ANTHROPIC_AUTH_TOKEN=ollama -e ANTHROPIC_API_KEY= \
      -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 -e DISABLE_AUTOUPDATER=1 \
      claude "$repo"
    # The rule matches where the host proxy forwards to (localhost), not the name the sandbox uses.
    sbx policy allow network --sandbox "$name" "localhost:$MODEL_PORT" >/dev/null
    echo "sandbox $name ready; workdir: $(workdir "$name")"
    ;;
  setup)
    name=${1:?name}; shift
    sbx policy allow network --sandbox "$name" "$REGISTRIES" >/dev/null
    trap 'sbx policy rm network --sandbox "$name" --resource "$REGISTRIES" --force >/dev/null' EXIT
    wd=$(workdir "$name")
    sbx exec -w "$wd" "$name" sh -c "$*"
    # anything setup wrote inside the repo (egg-info, generated version files) stays out of the agent's diff
    sbx exec -w "$wd" "$name" sh -c 'git status --porcelain --untracked-files=all | sed -n "s/^?? //p" >> .git/info/exclude'
    ;;
  guide)
    name=${1:?name}; file=${2:?file}
    sbx exec "$name" mkdir -p /home/agent/.claude
    sbx cp "$file" "$name:/home/agent/.claude/CLAUDE.md"
    ;;
  run)
    name=${1:?name}; model=${2:?model}; spec=${3:?specfile}; turns=${4:-${AGENT_MAX_TURNS:-60}}
    wd=$(workdir "$name")
    sbx exec -i -w "$wd" -e AGENT_EFFORT="${AGENT_EFFORT:-}" -e AGENT_FORMAT="${AGENT_FORMAT:-json}" -e AGENT_CONTEXT="${AGENT_CONTEXT:-128000}" "$name" sh -c "$VENV"' export CLAUDE_CODE_ATTRIBUTION_HEADER=0 API_TIMEOUT_MS=3000000 CLAUDE_CODE_AUTO_COMPACT_WINDOW="${AGENT_CONTEXT:-128000}" ANTHROPIC_MODEL="$2" ANTHROPIC_DEFAULT_OPUS_MODEL="$2" ANTHROPIC_DEFAULT_SONNET_MODEL="$2" ANTHROPIC_DEFAULT_HAIKU_MODEL="$2" ANTHROPIC_SMALL_FAST_MODEL="$2" CLAUDE_CODE_SUBAGENT_MODEL="$2"; exec timeout "$1" claude -p --model "$2" --output-format "${AGENT_FORMAT:-json}" $([ "${AGENT_FORMAT:-}" = stream-json ] && echo --verbose) \
      --max-turns "$3" --dangerously-skip-permissions' _ "$(( ${AGENT_TIMEOUT_MIN:-45} * 60 ))" "$model" "$turns" < "$spec"
    ;;
  commit)
    name=${1:?name}; msg=${2:?message}
    wd=$(workdir "$name")
    sbx exec -w "$wd" "$name" sh -c 'git add -A && git -c user.name=local-agent -c user.email=agent@sandbox \
      commit -qm "$1" && git rev-parse --abbrev-ref HEAD && git log --oneline -1' _ "$msg"
    ;;
  fetch)
    name=${1:?name}; repo=${2:?repo}
    git -C "$repo" fetch -q "sandbox-$name"
    br=$(sbx exec -w "$(workdir "$name")" "$name" git rev-parse --abbrev-ref HEAD | tr -d '\r')
    base=$(git -C "$repo" rev-parse HEAD)
    echo "branch: sandbox-$name/$br"
    git -C "$repo" diff --stat "$base" "sandbox-$name/$br"
    git -C "$repo" diff "$base" "sandbox-$name/$br"
    ;;
  check)
    name=${1:?name}; shift
    sbx exec -w "$(workdir "$name")" "$name" sh -c "$VENV $*"
    ;;
  rm)
    name=${1:?name}; repo=${2:-}
    sbx rm -f "$name" 2>/dev/null || sbx rm "$name"
    [ -n "$repo" ] && git -C "$repo" remote remove "sandbox-$name" 2>/dev/null || true
    ;;
  *) echo "unknown command: $cmd" >&2; exit 2 ;;
esac
