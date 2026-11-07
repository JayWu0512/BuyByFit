# One-time setup for phone-video -> 3D room reconstruction (VGGT on an NVIDIA GPU).
# Run it yourself from the repo root:   powershell -ExecutionPolicy Bypass -File ar-mvp\room\setup_video_recon.ps1
#
# What it does (about 8 GB of downloads):
#   1. makes a separate Python 3.13 venv in %USERPROFILE%\buybyfit-data\vggt-venv, so the server's CPU
#      PyTorch is untouched
#   2. installs CUDA 12.6 PyTorch + small deps
#   3. clones facebookresearch/vggt and installs it with --no-deps (its pinned old torch would downgrade ours)
#   4. downloads the VGGT-1B weights (~5 GB) from Hugging Face on first run
# VGGT-1B weights are licensed for non-commercial use (fine for a class demo; check before shipping).

$ErrorActionPreference = "Stop"
$data = "$env:USERPROFILE\buybyfit-data"
$venv = "$data\vggt-venv"
New-Item -ItemType Directory -Force $data | Out-Null

py -V:Astral/CPython3.13.5 -m venv $venv 2>$null
if (-not (Test-Path "$venv\Scripts\python.exe")) { py -3.13 -m venv $venv }
$py = "$venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu126
& $py -m pip install einops safetensors huggingface_hub numpy pillow opencv-python-headless
if (-not (Test-Path "$data\vggt")) { git clone --depth 1 https://github.com/facebookresearch/vggt "$data\vggt" }
& $py -m pip install --no-deps -e "$data\vggt"
& $py -c "import torch; from vggt.models.vggt import VGGT; print('CUDA:', torch.cuda.is_available()); VGGT.from_pretrained('facebook/VGGT-1B'); print('VGGT ready')"
Write-Host "`nDone. The room server will now accept phone videos."
