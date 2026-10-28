from fastapi import APIRouter, File, UploadFile
from services.face_search_service import FaceSearch, FaceSearchResponse, DetectFacesResponse
from utils.investigation_decorator import save_investigation

router = APIRouter(prefix="/api/face-search")
face_search = FaceSearch()

@router.post("/detect-faces")
async def detect_faces(image: UploadFile = File(...)) -> DetectFacesResponse:
    response = await face_search.detect_faces(image)
    return response

@router.post("/search")
@save_investigation(service_name="face_search", method_name="search_faces")
async def search(image: UploadFile = File(...)) -> FaceSearchResponse:
    response = await face_search.search(image)
    return response