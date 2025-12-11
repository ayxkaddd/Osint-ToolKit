from fastapi import File, UploadFile
from typing import List
import httpx
from fastapi import HTTPException
import io
from pydantic import BaseModel

class FaceCoordinates(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

class DetectFacesResponse(BaseModel):
    faces: List[FaceCoordinates]

class SearchResult(BaseModel):
    name: str
    similarity_rate: str
    vk_id: str
    city: str
    image_url: str

class FaceSearch:
    def __init__(self):
        self.API_ENDPOINT = "https://37.60.238.161"
        self.HEADERS = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://similarfaces.me/',
            'Origin': 'https://similarfaces.me',
            'Sec-GPC': '1',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }

    async def detect_faces(self, image: UploadFile) -> DetectFacesResponse:
        try:
            image_data = await image.read()

            files = {
                'image': (image.filename or 'image.jpg', io.BytesIO(image_data), image.content_type or 'image/jpeg')
            }

            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                response = await client.post(
                    f'{self.API_ENDPOINT}/api/detect-faces',
                    files=files,
                    headers=self.HEADERS
                )
                response.raise_for_status()

            faces =  response.json().get("faces", [])

            return DetectFacesResponse(faces=[FaceCoordinates(x1=face[0], y1=face[1], x2=face[2], y2=face[3]) for face in faces])

        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Error calling face detection API: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


    async def search(self, image: File) -> List[SearchResult]:
        try:
            image_data = await image.read()

            files = {
                'image': (image.filename or 'face.jpg', io.BytesIO(image_data), image.content_type or 'image/jpeg')
            }

            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                response = await client.post(
                    f'{self.API_ENDPOINT}/bff/search-faces',
                    files=files,
                    headers=self.HEADERS
                )
                response.raise_for_status()

            results =  response.json().get("results", [])
            return [SearchResult(**result) for result in results]

        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Error calling face search API: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
