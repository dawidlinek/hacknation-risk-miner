#!/bin/bash
# Risk Miner: OCR of scanned PDFs (Tesseract, Polish) on one Bem2 CPU node, billed to the PBR service.
#   stage:   rsync input.tar.zst + ocr_batch.py + this file to /lustre/pd03/hpc-dawlin1140-1773687823/riskminer/ocr/
#   check:   ~/wcss-slurm/scripts/preflight.sh ocr.sbatch
#   submit:  sbatch --parsable ocr.sbatch
#SBATCH --job-name=riskminer-ocr
#SBATCH --account=hpc-dawlin1140-1773687823
#SBATCH --partition=bem2-cpu-short
#SBATCH --cpus-per-task=48
#SBATCH --mem=96gb
#SBATCH --time=3:00:00
#SBATCH --output=/lustre/pd03/hpc-dawlin1140-1773687823/riskminer/ocr/logs/%x_%j.out
#SBATCH --error=/lustre/pd03/hpc-dawlin1140-1773687823/riskminer/ocr/logs/%x_%j.err

set -euo pipefail

PD="/lustre/pd03/${SLURM_JOB_ACCOUNT}"
BASE="$PD/riskminer/ocr"
OUT="$BASE/runs/$SLURM_JOB_ID"

copy_out() {
    mkdir -p "$OUT"
    if [ -d "$TMPDIR/out" ]; then cp -r "$TMPDIR/out/." "$OUT/"; fi
    echo "finished  $(date -Is)   results $OUT"
}
trap copy_out EXIT

echo "job       ${SLURM_JOB_ID} on ${SLURM_JOB_NODELIST}"
echo "account   ${SLURM_JOB_ACCOUNT}   partition ${SLURM_JOB_PARTITION}   cpus ${SLURM_CPUS_PER_TASK}"
echo "tmpdir    ${TMPDIR}"
echo "started   $(date -Is)"

cd "$TMPDIR"
# --- software: no module ships tesseract, so build a throwaway env in node-local scratch ---------------
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj bin/micromamba
export MAMBA_ROOT_PREFIX="$TMPDIR/mamba"
./bin/micromamba create -y -q -p "$TMPDIR/env" -c conda-forge python=3.12 tesseract pypdfium2 pillow zstd
export PATH="$TMPDIR/env/bin:$PATH"
mkdir -p "$TMPDIR/tessdata"
cp "$TMPDIR/env/share/tessdata/"*.traineddata "$TMPDIR/tessdata/" 2>/dev/null || true
curl -Lsf -o "$TMPDIR/tessdata/pol.traineddata" https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/pol.traineddata
export TESSDATA_PREFIX="$TMPDIR/tessdata"
tesseract --version 2>&1 | head -1
tesseract --list-langs 2>&1 | tr '\n' ' '; echo

# one tesseract thread per worker process; workers = allocated cores
export OMP_THREAD_LIMIT=1 OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1

mkdir -p in out
tar -I zstd -xf "$BASE/input.tar.zst" -C in
cp "$BASE/ocr_input.tsv" in/
echo "input     $(wc -l < in/ocr_input.tsv) documents   unpacked $(date -Is)"

python "$BASE/ocr_batch.py" --in-dir in --out-dir out --workers "$SLURM_CPUS_PER_TASK" --lang pol
