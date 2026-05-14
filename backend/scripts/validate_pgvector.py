import asyncio
import sys
import os

# Ensure the backend directory is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import AsyncSessionLocal
from services.knowledge_service import query_knowledge_base, query_knowledge_base_pgvector, embed_texts

async def validate():
    # 1. Embed a test query
    query = "What is the price of marble?"
    print(f"Embedding query: {query}")
    try:
        embeddings = embed_texts([query])
        query_emb = embeddings[0]
    except Exception as e:
        print(f"Failed to embed text. Do you have API keys configured? Error: {e}")
        return

    # 2. Query ChromaDB
    print("\n--- Querying ChromaDB ---")
    try:
        chroma_res = query_knowledge_base(query_emb, n_results=5)
        print(f"ChromaDB returned {len(chroma_res['documents'])} chunks.")
        for i, (doc, dist) in enumerate(zip(chroma_res['documents'], chroma_res['distances'])):
            print(f"[{i+1}] Dist: {dist:.4f} | {doc[:80]}...")
    except Exception as e:
        print(f"ChromaDB query failed: {e}")
        chroma_res = {"documents": [], "distances": []}

    # 3. Query pgvector
    print("\n--- Querying pgvector ---")
    try:
        async with AsyncSessionLocal() as db:
            pg_res = await query_knowledge_base_pgvector(db, query_emb, n_results=5)
        
        print(f"pgvector returned {len(pg_res['documents'])} chunks.")
        for i, (doc, dist) in enumerate(zip(pg_res['documents'], pg_res['distances'])):
            print(f"[{i+1}] Dist: {dist:.4f} | {doc[:80]}...")
    except Exception as e:
        print(f"pgvector query failed: {e}")
        pg_res = {"documents": [], "distances": []}

    # 4. Compare
    print("\n--- Comparison ---")
    if len(chroma_res['documents']) == 0 and len(pg_res['documents']) == 0:
        print("Both databases are empty. Please upload some knowledge base documents first.")
        return

    matches = 0
    for c_doc in chroma_res['documents']:
        if c_doc in pg_res['documents']:
            matches += 1
    
    total = max(len(chroma_res['documents']), len(pg_res['documents']))
    print(f"Overlap: {matches} / {total} chunks match.")
    
    if matches > 0 or total == 0:
        print("✅ Validation successful: pgvector retrieval aligns with ChromaDB.")
    else:
        print("❌ Validation failed: Mismatch between pgvector and ChromaDB.")

if __name__ == "__main__":
    asyncio.run(validate())
