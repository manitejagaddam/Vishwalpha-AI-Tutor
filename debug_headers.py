import os, json
from dotenv import load_dotenv
load_dotenv()
from ingestion.parser import PDFParser

parser = PDFParser(use_ocr=False)
pages = parser.parse("DataSet/Class_10/Science/chapter_1.pdf")

# Print all Header elements with their font sizes
for page in pages:
    for el in page.get("elements", []):
        if el["type"] == "Header":
            print(f"  Page {page['page_num']} | size={el['font_size']} bold={el['is_bold']} | {el['text'][:120]}")
