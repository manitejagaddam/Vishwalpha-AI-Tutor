from IPython.core import display_functions
import os
import sys
import pandas as pd
# Add parent directory to sys.path to enable imports from the project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ingestion.pipeline import ingest_pdf

df = pd.read_csv("../DataSet/Class_10/Science/class10_science.csv")

# ingest_pdf(
#     pdf_path="../DataSet/Class_10/Science/chapter_4.pdf",
#     class_num=10,
#     subject="Science",
#     chapter="Carbon and its compounds",
# )

for idx in range(1):
    ingest_pdf( 
        pdf_path=str(df.iloc[idx][0]),
        class_num=int(df.iloc[idx][1]),
        subject=str(df.iloc[idx][2]),
        chapter=str(df.iloc[idx][3]),
    )