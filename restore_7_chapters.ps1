# restore_7_chapters.ps1
# Instantly restores database to the 7-chapter clean checkpoint (Chapters 1, 2, 3, 10, 11, 12, 13).
# Removes any half-ingested chapters from chapters 4-9 and re-verifies the 7 chapters.

$ErrorActionPreference = "Stop"

Write-Host "Restoring database to 7-chapter clean checkpoint..." -ForegroundColor Yellow
uv run python -m scripts.restore_checkpoint
Write-Host "Restore complete! Current Alembic version is 013 (head)." -ForegroundColor Green
