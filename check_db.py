import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models.models import Product

async def main():
    engine = create_async_engine(
        "postgresql+asyncpg://twinai:twinai_dev_password@localhost:5432/twinai_db"
    )
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as db:
        from sqlalchemy import select
        res = await db.execute(select(Product))
        products = res.scalars().all()
        for p in products:
            print(f"Product: {p.name} | Description: {p.description[:50] if p.description else 'None'} | Image: {p.image_url}")

asyncio.run(main())
