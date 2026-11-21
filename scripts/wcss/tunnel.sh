#!/bin/bash
# Reach the sovereign vLLM job (Bielik 11B v3.1 FP8 + PLLuM 12B) from the app host (docs/impl/llm.md §5.5).
# The login node cannot open TCP connections to compute nodes, so a plain `ssh -L` tunnel does not work. Every local
# connection instead runs a byte pump inside the job (`srun --jobid --overlap`) over the shared `wcss` SSH connection,
# which is what relay.py from the team's WCSS tooling does. It reads the job's endpoint file and binds
# 127.0.0.1:<node port + 100>: Bielik → 8100, PLLuM → 8101 (config llm.providers.wcss_bielik / wcss_pllum).
#
#   RELAY=/path/to/deploy/wcss/relay.py scripts/wcss/tunnel.sh
#
# Needs: an `ssh wcss` alias with BatchMode yes and ControlMaster (three failed password logins lock the account for
# 24 h; never retry an auth failure), the job running (job name rm-sovereign, ~/riskminer-serve/serve.sbatch on WCSS),
# and WCSS_VLLM_KEY in .env (the key is in $PD/riskminer-llm/.api_key, mode 600). After it is up,
# POST /api/settings/llm/providers/wcss_bielik/health runs the known-answer test; confidential calls also run it.
set -euo pipefail
RELAY="${RELAY:?set RELAY to relay.py}"
ENDPOINT="/lustre/pd03/hpc-dawlin1140-1773687823/riskminer-llm/serve/endpoint.txt"
ssh -O check wcss 2>/dev/null || ssh -f -N wcss
exec python3 "$RELAY" --bind 127.0.0.1 --endpoint "$ENDPOINT" --offset 100
