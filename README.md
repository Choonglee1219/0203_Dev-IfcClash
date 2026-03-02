# IFC Clash Detection Microservice

이 프로젝트는 IFC 파일 간의 간섭(Clash)을 탐지하고, 결과를 BCF(BIM Collaboration Format) 파일로 생성하는 마이크로서비스입니다. FastAPI를 기반으로 구축되었으며, `ifcclash` 및 `ifcopenshell` 라이브러리를 사용하여 정밀한 간섭 체크를 수행합니다.

## 주요 기능

*   **간섭 탐지 (Clash Detection)**: 사용자가 정의한 규칙(Clash Set)에 따라 IFC 모델 간의 물리적 간섭을 분석합니다.
*   **BCF 리포트 생성**: 분석 결과를 표준 BCF 2.1 형식(.bcf)으로 내보냅니다.
*   **지능형 후처리 (Post-processing)**:
    *   생성된 BCF 패키지 내의 XML을 수정하여 뷰어 호환성을 개선합니다.
    *   간섭이 발생한 두 객체에 대해 시각적 구분을 위한 색상(빨강/초록) 정보를 주입합니다.
    *   기본 스냅샷(Snapshot) 이미지를 생성하여 포함시킵니다.
*   **REST API 제공**: HTTP POST 요청을 통해 간섭 체크를 요청하고 결과 파일을 다운로드할 수 있습니다.

## 설치 방법

1. 저장소를 복제합니다.
   ```bash
   git clone https://github.com/your_id/clash.git
   cd clash
   ```

2. Python 가상 환경을 생성하고 활성화합니다.
   ```bash
   python -m venv .venv
   
   # Windows
   .venv\Scripts\activate
   
   # macOS/Linux
   source .venv/bin/activate
   ```

3. 필요한 의존성 패키지를 설치합니다.
   ```bash
   pip install -r requirements.txt
   ```

## 실행 방법

### 1. API 서버 실행 (권장)

FastAPI 서버를 실행하여 외부 요청을 처리할 수 있습니다.

```bash
python main.py
# 또는 uvicorn 직접 실행
uvicorn main:app --host 0.0.0.0 --port 8000
```

서버가 실행되면 `http://localhost:8000/docs` 에서 Swagger UI를 통해 API를 테스트할 수 있습니다.

### 2. 독립 실행 (Standalone)

API 서버 없이 로컬에서 테스트하려면 `clash.py`를 직접 실행할 수 있습니다. 단, 코드 내의 파일 경로(`input.json`, `bcf_file_path`)를 환경에 맞게 수정해야 합니다.

```bash
python clash.py
```

## API 사용법

*   **Endpoint**: `POST /clash`
*   **Content-Type**: `application/json`
*   **Response**: `.bcf` 파일 다운로드

**요청 본문 (JSON) 예시:**

```json
[
  {
    "name": "Structural vs MEP",
    "mode": "clash",
    "tolerance": 0.01,
    "check_all": true,
    "a": [
      { "file": "C:/path/to/structure.ifc", "selector": "IfcBeam", "mode": "include" }
    ],
    "b": [
      { "file": "C:/path/to/mep.ifc", "selector": "IfcDuctSegment", "mode": "include" }
    ]
  }
]
```