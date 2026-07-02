"""
retrieval/reranker.py
─────────────────────
Compresses and reranks retrieved context for the LLM.
"""

class Reranker:
    """
    Handles context compression and re-ordering for optimal LLM consumption.
    """
    def __init__(self):
        pass

    def compress_context(self, chunks: list[dict], max_tokens: int = 1500) -> str:
        """
        Compresses and formats the retrieved chunks into a single context string
        for the LLM, ensuring it fits within an approximate token limit.
        """
        context = ""
        current_length = 0
        
        sorted_chunks = sorted(chunks, key=lambda x: x["score"], reverse=True)
        
        for i, chunk in enumerate(sorted_chunks):
            chunk_tokens = len(chunk["content"]) // 4 
            
            if current_length + chunk_tokens > max_tokens:
                break
                
            metadata = chunk["metadata"]
            topic_str = f"[{metadata.get('chapter', 'Unknown Chapter')} - {metadata.get('topic', 'Unknown Topic')}]"
            
            context += f"--- Source {i+1} {topic_str} ---\n{chunk['content']}\n\n"
            current_length += chunk_tokens
            
        return context.strip()
