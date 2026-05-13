import os
import re

os.makedirs('utils', exist_ok=True)
with open('utils/__init__.py', 'w') as f: pass

with open('utils/logger.py', 'w') as f:
    f.write('''import logging
import sys

def setup_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
    return logger
''')

files = [
    'main.py', 
    'ingestion/parser.py', 
    'ingestion/llm_repair.py', 
    'ingestion/structurer.py', 
    'ingestion/summarizer.py', 
    'routing/router.py', 
    'routing/vector_store.py', 
    'routing/embedder.py',
    'retrieval/engine.py', 
    'retrieval/cache.py',
    'db/database.py'
]

for file in files:
    if not os.path.exists(file): continue
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'setup_logger' not in content:
        content = 'from utils.logger import setup_logger\nlogger = setup_logger(__name__)\n' + content
        
    content = re.sub(r'print\("WARNING: (.*?)"\)', r'logger.warning("\1")', content)
    content = re.sub(r'print\(f"Error (.*?)"\)', r'logger.error(f"\1")', content)
    content = re.sub(r'print\(f"LLM Repair failed: \{e\}"\)', r'logger.error(f"LLM Repair failed: {e}")', content)
    content = re.sub(r'print\(f"Database error: \{e\}"\)', r'logger.error(f"Database error: {e}")', content)
    content = re.sub(r'print\((.*?)\)', r'logger.info(\1)', content)
    
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)
print('Done!')
