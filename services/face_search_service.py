import hashlib
import io
import time
from typing import List

import httpx
from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel


class FaceCoordinates(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


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
        # self.API_ENDPOINT = "https://37.60.238.161"
        self.API_ENDPOINT = "https://similarfaces.me"
        self.HEADERS = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://similarfaces.me/",
            "Content-Type": "multipart/form-data; boundary=----geckoformboundary789c6cfffacf9a4766690aefd8f5b006",
            "Origin": "https://37.60.238.161",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=4",
        }

    def hash_string(self, s: str) -> str:
        t = int(time.time() // 60)
        msg = f"{t}:{s}"

        hash_obj = hashlib.sha256(msg.encode())

        return hash_obj.hexdigest()

    async def detect_faces(self, image: UploadFile) -> DetectFacesResponse:
        try:
            image_data = await image.read()

            files = {
                "image": (
                    image.filename or "image.jpg",
                    io.BytesIO(image_data),
                    image.content_type or "image/jpeg",
                )
            }

            hashed = self.hash_string("detect-faces")
            self.HEADERS["X-Frontend-ID"] = hashed

            async with httpx.AsyncClient(timeout=20, verify=False) as client:
                response = await client.post(
                    f"{self.API_ENDPOINT}/bff/detect-faces",
                    files=files,
                    headers=self.HEADERS,
                )
                response.raise_for_status()

            faces = response.json().get("faces", [])

            return DetectFacesResponse(
                faces=[
                    FaceCoordinates(x1=face[0], y1=face[1], x2=face[2], y2=face[3])
                    for face in faces
                ]
            )
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500, detail=f"Error calling face detection API: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

    async def search(self, image: File) -> List[SearchResult]:
        try:
            image_data = await image.read()

            files = {
                "image": (
                    image.filename or "face.jpg",
                    io.BytesIO(image_data),
                    image.content_type or "image/jpeg",
                )
            }

            hashed = self.hash_string("detect-faces")
            self.HEADERS["X-Frontend-ID"] = hashed

            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                response = await client.post(
                    f"{self.API_ENDPOINT}/bff/search-faces",
                    files=files,
                    headers=self.HEADERS,
                )
                response.raise_for_status()

            results = response.json().get("results", [])
            return [SearchResult(**result) for result in results]

        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500, detail=f"Error calling face search API: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
