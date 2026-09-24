# ingest_class_9.ps1
# Ingests all Class 9 Science chapters (1 to 13) into VishwAlpha database.
# Runs the full pipeline: PDF -> PyMuPDF / PaddleX -> LLM structuring -> Embeddings -> Supabase DB.
#
# Usage:
#   .\ingest_class_9.ps1                  # Ingest all 13 chapters directly into the DB
#   .\ingest_class_9.ps1 -JsonOnly        # Generate debug JSON files without DB write
#   .\ingest_class_9.ps1 -ChapterNum 4    # Ingest only a specific chapter (e.g. Chapter 4)
#   .\ingest_class_9.ps1 -StartFrom 3     # Resume starting from Chapter 3

param(
    [switch]$JsonOnly,
    [int]$ChapterNum = 0,
    [int]$StartFrom = 1
)

$ErrorActionPreference = "Stop"

$BOARD = "NCERT"
$CLASS = "9"
$SUBJECT = "Science"
$BOOK_TITLE = "NCERT Science Class 9"
$BOOK_KEY = "NCERT_9_Science_en_2023"
$pdfDir = "DataSet\Class_9\Science"

$allChapters = @(
    @{ num=1;  title="Exploration Entering the world of Secondary Science"; file="chapter_1 (Exploration Entering the world of Secondary Science).pdf" },
    @{ num=2;  title="Cell The Building Block of Life";                     file="chapter_2 (Cell The Building Block of Life).pdf" },
    @{ num=3;  title="Tissues in Action";                                   file="chapter_3 (Tissues in Action).pdf" },
    @{ num=4;  title="Describing Motion Around Us";                         file="chapter_4 (Describing Motion Around Us).pdf" },
    @{ num=5;  title="Exploring Mixtures and their Seperation";            file="chapter_5 (Exploring Mixtures and their Seperation).pdf" },
    @{ num=6;  title="How Forces Affect Motion";                           file="chapter_6 (How Forces Affect Motion).pdf" },
    @{ num=7;  title="Work, Energy, and Simple Machines";                   file="chapter_7 (Work, Energy, and Simple Machines).pdf" },
    @{ num=8;  title="Journey Inside the Atom";                            file="chapter_8 (Journey Inside the Atom).pdf" },
    @{ num=9;  title="Atomic Foundations of Matter";                       file="chapter_9 (Atomic Foundations of Matter).pdf" },
    @{ num=10; title="Sound Waves Characteristics and Applications";        file="chapter_10 (Sound Waves Characteristics and Applications).pdf" },
    @{ num=11; title="Reproduction How Life Continues";                     file="chapter_11 (Reproduction How Life Continues).pdf" },
    @{ num=12; title="Patterns in Life Diversity and Classification";       file="chapter_12 (Patterns in Life Diversity and Classification).pdf" },
    @{ num=13; title="Earth as a System Energy, Matter and Life";           file="chapter_13 (Earth as a System Energy, Matter and Life).pdf" }
)

# Filter chapters based on parameters
$targetChapters = $allChapters | Where-Object {
    if ($ChapterNum -gt 0) {
        $_.num -eq $ChapterNum
    } else {
        $_.num -ge $StartFrom
    }
}

if ($targetChapters.Count -eq 0) {
    Write-Host "No matching chapters found to ingest." -ForegroundColor Yellow
    exit 0
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "VishwAlpha Class 9 Science Ingestion Pipeline" -ForegroundColor Cyan
Write-Host "Target Chapters: $($targetChapters.Count) chapter(s)" -ForegroundColor Cyan
if ($JsonOnly) {
    Write-Host "Mode: JSON Generation Only (--json-only)" -ForegroundColor Magenta
} else {
    Write-Host "Mode: Direct Database Ingestion" -ForegroundColor Green
}
Write-Host "========================================================" -ForegroundColor Cyan

foreach ($ch in $targetChapters) {
    $pdfPath = Join-Path $pdfDir $ch.file
    
    if (-not (Test-Path $pdfPath)) {
        Write-Host "[ERROR] PDF not found: $pdfPath" -ForegroundColor Red
        continue
    }

    Write-Host ""
    Write-Host "--------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "Ingesting Chapter $($ch.num): $($ch.title)" -ForegroundColor Yellow
    Write-Host "File: $pdfPath"
    Write-Host "--------------------------------------------------------" -ForegroundColor Yellow
    
    $extraArgs = @("--log-file")
    if ($JsonOnly) {
        $extraArgs += "--json-only"
    }

    uv run python -m scripts.ingest $pdfPath `
        --board $BOARD `
        --class $CLASS `
        --subject $SUBJECT `
        --book-title $BOOK_TITLE `
        --book-key $BOOK_KEY `
        --chapter "$($ch.title)" `
        --chapter-num $ch.num `
        @extraArgs

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARNING] Chapter $($ch.num) exited with code $LASTEXITCODE" -ForegroundColor Red
    } else {
        Write-Host "[DONE] Chapter $($ch.num) processed successfully!" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Class 9 Science ingestion batch finished!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
