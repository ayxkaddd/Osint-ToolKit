import os
import uuid
import aiohttp
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

load_dotenv()

class OiService:
    def __init__(self):
        self.token = os.getenv("OSINT_INDUSTRIES_API_KEY")

    async def query_oi_api(self, type: str, query: str) -> JSONResponse:
        async with aiohttp.ClientSession() as session:
            headers = {
                'api-key': self.token,
                'accept': 'application/pdf'
            }

            params = {
                'type': type,
                'query': query,
                'timeout': '80'
            }

            async with session.get(f'https://api.osint.industries/v2/request', headers=headers, params=params) as resp:
                if resp.headers['Content-Type'] == 'application/pdf':
                    filename = f'reports/{uuid.uuid4()}.pdf'
                    with open(filename, 'wb') as f:
                        f.write(await resp.read())
                    return JSONResponse({"url": "/" + filename})
                else:
                    return JSONResponse(await resp.json())

    async def get_credits(self):
        headers = {
            'api-key': self.token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.osint.industries/misc/credits', headers=headers) as resp:
                credits = await resp.text()
                return {"credits": credits}
