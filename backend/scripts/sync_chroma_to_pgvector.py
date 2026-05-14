import asyncio
import sys
import os
import json
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import AsyncSessionLocal
from services.knowledge_service import get_chroma_collection
from models.models import KnowledgeChunk, KnowledgeBase
from sqlalchemy import select

async def sync():
    collection = get_chroma_collection()
    results = collection.get(include=["embeddings", "documents", "metadatas"])
    
    if not results["ids"]:
        print("ChromaDB is empty.")
        return
        
    print(f"Found {len(results['ids'])} chunks in ChromaDB.")
    
    async with AsyncSessionLocal() as db:
        # Check if they exist
        existing = (await db.execute(select(KnowledgeChunk.id))).scalars().all()
        if existing:
            print("pgvector already has chunks. Emptying table...")
            await db.execute(KnowledgeChunk.__table__.delete())
            await db.commit()
            
        for i, id_str in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            doc_id = uuid.UUID(meta["doc_id"])
            
            # Ensure KnowledgeBase exists
            kb = await db.get(KnowledgeBase, doc_id)
            if not kb:
                print(f"Creating missing KnowledgeBase {doc_id}")
                kb = KnowledgeBase(
                    id=doc_id,
                    filename=meta.get("filename", "unknown"),
                    category=meta.get("category", "unknown"),
                    chroma_ids=[id_str],
                    is_active=True
                )
                db.add(kb)
                await db.commit()
                
            chunk = KnowledgeChunk(
                knowledge_base_id=doc_id,
                content=results["documents"][i],
                embedding=results["embeddings"][i],
                chunk_metadata=json.dumps(meta)
            )
            db.add(chunk)
        
        await db.commit()
        print("Sync complete.")

if __name__ == "__main__":
    asyncio.run(sync())
