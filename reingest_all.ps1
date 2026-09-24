$ErrorActionPreference = "Stop"


Write-Host "`nStarting bulk ingestion for Class 10 Science..." -ForegroundColor Cyan
$pdfDir = "DataSet\Class_10\Science"

# Find all PDF files and extract chapter number and title using regex
Get-ChildItem -Path $pdfDir -Filter "*.pdf" | ForEach-Object {
    if ($_.Name -match 'chapter_(\d+)\s*\((.*?)\)\.pdf') {
        $chapterNum = $matches[1]
        $chapterTitle = $matches[2]
        
        Write-Host "`n========================================================"
        Write-Host "Ingesting Chapter ${chapterNum}: $chapterTitle" -ForegroundColor Cyan
        Write-Host "========================================================"
        
        # Run the ingestion pipeline (single line to avoid backtick continuation errors)
        uv run python -m scripts.ingest $_.FullName --board NCERT --class 10 --subject Science --book-title "NCERT Science Class 10" --book-key "NCERT_10_Science_en_2023" --chapter "$chapterTitle" --chapter-num $chapterNum --log-file
    } else {
        Write-Host "Skipping $($_.Name) - did not match naming format." -ForegroundColor Yellow
    }
}

Write-Host "`nAll 13 chapters have been successfully ingested!" -ForegroundColor Green
