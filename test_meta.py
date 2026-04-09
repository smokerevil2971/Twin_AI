import asyncio
import os
from dotenv import load_dotenv

async def test_meta():
    load_dotenv()
    from services.meta_waba_adapter import MetaWABAAdapter
    
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    token = os.getenv("META_ACCESS_TOKEN")
    secret = os.getenv("META_APP_SECRET")
    
    adapter = MetaWABAAdapter(phone_id, token, secret)
    # The phone number in the image is +1 (555) 186-2484
    # Wait, the user phone is probably their test number. Let's use OWNER_PHONE from .env
    phone = "+919075805070"  # from .env
    
    url = "https://drive.google.com/uc?export=download&id=1xkLpc1VhmbNgEYIK9mQ2ukrBf6GxatoH"
    caption = "Test caption\nBrands: EcoPro"
    
    try:
        res = await adapter.send_media_message(phone, url, "image", caption, "product_image.jpg")
        print("Success:", res)
    except Exception as e:
        print("Error:", e)

asyncio.run(test_meta())
