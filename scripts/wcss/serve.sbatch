#!/bin/bash
# Sovereign LLM serving for ex ante (docs/impl/llm.md §5.4): Bielik 11B v3.1 + PLLuM 12B on one lem-gpu node, vLLM
# OpenAI-compatible API on ports 8000/8001 of the node, reached from the app host through scripts/wcss/tunnel.sh.
# The job actually prepared on WCSS is ~/riskminer-serve/serve.sbatch (1 H100, Bielik v3.1 FP8 + PLLuM on one GPU,
# 12 h, staged vLLM 0.34 stack and cached weights, endpoint file in PD/riskminer-llm/serve); this file is the
# 2-GPU variant kept for reference. NOT SUBMITTED. Before sbatch: the account owner picks the GPU service (--account), the HF token with Bielik v3.1
# terms accepted is in ~/.hf_token (mode 600), the vLLM key is in ~/.riskminer_vllm_key (mode 600), weights and the
# vLLM stack are staged in PD (§5.3 steps 1-2), and preflight passes. Fill <GPU_SERVICE_ACCOUNT> in the 3 places below.
#SBATCH --job-name=riskminer-sovereign
#SBATCH --account=<GPU_SERVICE_ACCOUNT>
#SBATCH --partition=lem-gpu-short
#SBATCH --gres=gpu:hopper:2,storage:local:200g
#SBATCH --cpus-per-task=32
#SBATCH --mem=500gb
#SBATCH --time=15:00:00
#SBATCH --output=/lustre/pd03/<GPU_SERVICE_ACCOUNT>/riskminer/llm/logs/%x_%j.out
#SBATCH --error=/lustre/pd03/<GPU_SERVICE_ACCOUNT>/riskminer/llm/logs/%x_%j.err

set -uo pipefail
source /usr/local/sbin/modules.sh
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/13.0.0
PD="/lustre/pd03/${SLURM_JOB_ACCOUNT}"
LOG="$PD/riskminer/llm/logs"
export HF_HOME="$TMPDIR/hf"
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=8
export TRITON_CACHE_DIR="$PD/llm-stack/triton-cache"
export VLLM_CACHE_ROOT="$PD/llm-stack/vllm-cache"
export VLLM_API_KEY="$(cat "$HOME/.riskminer_vllm_key")"      # never echoed; vLLM reads it from the environment
mkdir -p "$TRITON_CACHE_DIR" "$VLLM_CACHE_ROOT" "$LOG"
tar -xf "$PD/llm-stack/vllm.tar" -C "$TMPDIR"
for f in "$TMPDIR"/venv/bin/*; do
    [ -f "$f" ] && [ "$(head -c2 "$f" 2>/dev/null)" = '#!' ] && sed -i "1s|.*|#!$TMPDIR/venv/bin/python|" "$f"
done
export PATH="$TMPDIR/venv/bin:$PATH"
hostname > "$PD/riskminer/llm/node_${SLURM_JOB_ID}"

BIELIK="$PD/models/bielik-11b-v3.1-instruct"     # fallback without HF token: bielik-11b-v3.0-instruct-fp8 (ungated)
PLLUM="$PD/models/pllum-12b-instruct-2512"
COMMON="--host 0.0.0.0 --max-model-len 32768 --gpu-memory-utilization 0.90 --max-num-seqs 128 --dtype bfloat16"
CUDA_VISIBLE_DEVICES=0 vllm serve "$BIELIK" --served-model-name bielik-11b --port 8000 $COMMON \
    > "$LOG/bielik_${SLURM_JOB_ID}.log" 2>&1 &
CUDA_VISIBLE_DEVICES=1 vllm serve "$PLLUM" --served-model-name pllum-12b --port 8001 $COMMON \
    > "$LOG/pllum_${SLURM_JOB_ID}.log" 2>&1 &
wait
