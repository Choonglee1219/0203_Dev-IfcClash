from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import uuid
import os
import logging
import clash  # clash.py 모듈 임포트

# --- 로깅 설정 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ClashService")

app = FastAPI(title="IFC Clash Detection Microservice")

# --- CORS 미들웨어 설정 추가 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 오리진 허용 (실제 운영 시에는 클라이언트 IP/도메인만 허용 권장)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models (input.json 구조 정의) ---

class IfcSelector(BaseModel):
    file: str
    selector: str
    mode: str

class ClashSet(BaseModel):
    name: str
    mode: str
    a: List[IfcSelector]
    b: List[IfcSelector]
    tolerance: Optional[float] = None
    clearance: Optional[float] = None
    check_all: bool

# --- Helper Functions ---

def remove_file(path: str):
    """파일 삭제 헬퍼 함수 (Background Task용)"""
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Temporary file removed: {path}")
    except Exception as e:
        logger.error(f"Error removing file {path}: {e}")

# --- Endpoints ---

@app.post("/clash", response_class=FileResponse)
async def run_clash_detection(clash_sets: List[ClashSet], background_tasks: BackgroundTasks):
    """
    input.json 형태의 데이터를 받아 간섭 체크를 수행하고 BCF 파일을 반환합니다.
    """
    # 1. 고유한 요청 ID 생성 및 임시 파일 경로 설정
    request_id = str(uuid.uuid4())
    output_filename = f"clash_result_{request_id}.bcf"
    output_path = os.path.abspath(output_filename)

    try:
        # 2. Pydantic 모델을 dict 리스트로 변환 (clash.py 호환)
        # Pydantic v2를 사용하는 경우 model_dump(), v1인 경우 dict() 사용
        clash_data = [cs.dict() for cs in clash_sets]

        logger.info(f"Starting clash detection for request {request_id}")

        # 3. 간섭 체크 실행 (clash.py 로직)
        # raw_clash_data(실제 좌표 포함)를 반환받음
        raw_clash_data = clash.detect_clashes(clash_data, output_path)

        # 4. BCF 후처리 (스냅샷 생성 및 XML 수정)
        # raw_clash_data를 전달하여 정확한 좌표 매핑
        clash.post_process_bcf(output_path, raw_clash_data)

        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="BCF file generation failed.")

        # 5. 파일 응답 및 전송 후 삭제 예약
        background_tasks.add_task(remove_file, output_path)
        
        return FileResponse(
            path=output_path,
            filename="clash_report.bcf",
            media_type='application/octet-stream'
        )

    except Exception as e:
        # 에러 발생 시 임시 파일 정리
        if os.path.exists(output_path):
            os.remove(output_path)
        logger.error(f"Error during clash detection: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
