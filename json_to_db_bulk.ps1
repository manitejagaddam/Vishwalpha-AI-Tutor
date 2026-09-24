# json_to_db_bulk.ps1
# Inserts all 7 pre-generated JSON files into the database.
# No OCR or LLM structuring — only embedding calls (one per block).

$ErrorActionPreference = "Stop"
$jsonDir = "DataSet\Class_10\Science\json_files"
$BOARD = "NCERT"
$CLASS = "10"
$SUBJECT = "Science"
$BOOK_TITLE = "NCERT Science Class 10"
$BOOK_KEY = "NCERT_10_Science_en_2023"

# Map each JSON file to its chapter number and title
$chapters = @(
    @{ num=1;  title="Chemical Reactions and Equations";  file="ingest_debug_chapter_1 (Chemical Reactions and Equations).pdf.json" },
    @{ num=2;  title="Acids, bases and Salts";            file="ingest_debug_chapter_2 (Acids, bases and Salts).pdf.json" },
    @{ num=3;  title="Metals and Non-Metals";             file="ingest_debug_chapter_3 (Metals and Non-Metals).pdf.json" },
    @{ num=10; title="The Human Eye and the Colourful World"; file="ingest_debug_chapter_10 (The Human Eye and the Colourful World).pdf.json" },
    @{ num=11; title="Electricity";                       file="ingest_debug_chapter_11 (Electricity).pdf.json" },
    @{ num=12; title="Magnetic Effects and Electric Current"; file="ingest_debug_chapter_12 (Magnetic Effects and Electric Current).pdf.json" },
    @{ num=13; title="Our Environment";                   file="ingest_debug_chapter_13 (Our Environment).pdf.json" }
)

Write-Host "Starting JSON-to-DB bulk insert for 7 chapters..." -ForegroundColor Cyan

foreach ($ch in $chapters) {
    $jsonPath = Join-Path $jsonDir $ch.file
    Write-Host ""
    Write-Host "========================================================"
    Write-Host "Inserting Chapter $($ch.num): $($ch.title)" -ForegroundColor Cyan
    Write-Host "========================================================"
    uv run python -m scripts.json_to_db $jsonPath --board $BOARD --class $CLASS --subject $SUBJECT --book-title $BOOK_TITLE --book-key $BOOK_KEY --chapter $ch.title --chapter-num $ch.num --log-file
}

Write-Host ""
Write-Host "All 7 chapters inserted successfully!" -ForegroundColor Green
