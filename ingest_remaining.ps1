# ingest_remaining.ps1
# Ingests remaining Class 10 Science chapters (4, 5, 6, 7, 8, 9)
# that do not have pre-generated JSON files.
# Runs the full pipeline: PDF -> PaddleX OCR -> LLM structuring -> Embeddings -> Supabase DB.

$ErrorActionPreference = "Stop"

$BOARD = "NCERT"
$CLASS = "10"
$SUBJECT = "Science"
$BOOK_TITLE = "NCERT Science Class 10"
$BOOK_KEY = "NCERT_10_Science_en_2023"
$pdfDir = "DataSet\Class_10\Science"

$remainingChapters = @(
    @{ num=4; title="Carbon and its Compounds";               file="chapter_4 (Carbon and its Compounds).pdf" },
    @{ num=5; title="Life Processes";                         file="chapter_5 (Life Processes).pdf" },
    @{ num=6; title="Control and Coordination";               file="chapter_6 (Control and Coordination).pdf" },
    @{ num=7; title="How do Organisms Reproduce";             file="chapter_7 (How do Organisms Reproduce).pdf" },
    @{ num=8; title="Heridity";                               file="chapter_8 (Heridity).pdf" },
    @{ num=9; title="Light - Reflection and Refraction";       file="chapter_9 (Light - Reflection and Refraction).pdf" }
)

Write-Host "Starting direct PDF ingestion for remaining 6 chapters (4-9)..." -ForegroundColor Cyan

foreach ($ch in $remainingChapters) {
    $pdfPath = Join-Path $pdfDir $ch.file
    Write-Host ""
    Write-Host "========================================================"
    Write-Host "Ingesting Chapter $($ch.num): $($ch.title)" -ForegroundColor Cyan
    Write-Host "========================================================"
    
    uv run python -m scripts.ingest $pdfPath --board $BOARD --class $CLASS --subject $SUBJECT --book-title $BOOK_TITLE --book-key $BOOK_KEY --chapter "$($ch.title)" --chapter-num $ch.num --log-file
}

Write-Host ""
Write-Host "All remaining chapters (4-9) ingested successfully!" -ForegroundColor Green
