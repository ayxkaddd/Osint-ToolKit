from fastapi import APIRouter, File, UploadFile
from services.face_search_service import FaceSearch, SearchResult, DetectFacesResponse
from typing import List

router = APIRouter(prefix="/api/face-search")
face_search = FaceSearch()

@router.post("/detect-faces")
async def detect_faces(image: UploadFile = File(...)) -> DetectFacesResponse:
    return await face_search.detect_faces(image)

@router.post("/search")
async def search(image: UploadFile = File(...)) -> List[SearchResult]:
    return await face_search.search(image)
