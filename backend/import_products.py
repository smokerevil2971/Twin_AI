import asyncio
import sys
sys.path.append('/app')
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models.models import Product
from services.products_offers_service import parse_products_file, bulk_import_products
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    engine = create_async_engine('postgresql+asyncpg://twinai:twinai_dev_password@db:5432/twinai_db')
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    csv_data = b"""name,description,price,is_active,image_url
Gyproc Gypsum Board,"High-performance plasterboard.",350,true,https://drive.google.com/uc?export=download&id=1k-ghWAQisCKfVpvePii1RVN-8GH7sOVU
Gyproc Gypsum Plaster,"Ready-to-use gypsum plaster.",380,true,https://drive.google.com/uc?export=download&id=1sJaNLTONT9iuU5lxyFxrFSpqMS7V8tXa
Fiber Cement Board (Normal & Plus),"Multi-use fiber cement sheets.",45,true,https://drive.google.com/uc?export=download&id=1xkLpc1VhmbNgEYIK9mQ2ukrBf6GxatoH
Premium Plank & Designer Boards,"Fiber cement planks for cladding.",85,true,https://drive.google.com/uc?export=download&id=1Z-vjQTp6YdreDGXA2qnanyq-iSfI001M
PVC Ceiling & Tiles,"Versatile PVC ceiling systems.",35,true,https://drive.google.com/uc?export=download&id=1cpyV6voZ0zau2CFQGx6F40XlKQKRWXxP
Plastic & PVC Gypsum Ceiling Tiles,"Decorative PVC ceiling tiles.",18,true,https://drive.google.com/uc?export=download&id=1otlpTIShYAcczeVu3rWjlptr6jmzImGi
PVC Wooden Panel,"Wood-finish PVC panels.",40,true,https://drive.google.com/uc?export=download&id=1bdCm66kVLZCcSRP6dZP0KbI44k9Cl11_
Gypframe Expert (Metal Framing System),"Metal framing system.",80,true,https://drive.google.com/uc?export=download&id=1TEPTrpaU7qsJOSwv2m18rh6d_mHrl6t5
Ready-Made Wall Panels,"Pre-finished wall panels.",55,true,https://drive.google.com/uc?export=download&id=1y9zo0R3yud9zvRWUJhDwcmpNNfjjVYyZ
T-Grid False Ceiling System,"Suspended T-grid system.",25,true,https://drive.google.com/uc?export=download&id=1gzT_gHDDLUEH9y09MfyMLZwO8k6068HA"""
    
    parsed = parse_products_file(csv_data, 'products.csv')
    
    async with SessionLocal() as db:
        res = await bulk_import_products(db, parsed['rows'])
        print('Import Result:', res)

asyncio.run(main())
