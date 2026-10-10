# CommentScope

한 영상의 sampled comments에서 서로 다른 관점과 근거를 탐색하는 연구용 프로젝트입니다.

현재는 **공식 API로 로컬 표본 1,000개 확보, 원문 기반 V0 clustering 실행, 로컬 주장 추출 검증 단계**입니다.
주장 기반 전체 파이프라인·검증된 대표 agent·웹 앱은 아직 없습니다. 실제 corpus는 공개 저장소에 포함하지 않습니다.
이어서 작업할 때는 [다음 세션 시작점](docs/NEXT_SESSION.md)을 먼저 확인합니다.

## 읽는 순서

1. [프로젝트 요구사항](docs/requirements-handoff.md): Section 16이 최신 구현 기준입니다.
2. [단계별 구현 계획](docs/IMPLEMENTATION_PLAN.md): 단계별 산출물과 완료 조건입니다.
3. [협업 방법](CONTRIBUTING.md): 브랜치, 변경 검토, 데이터 관리 규칙입니다.
4. [구조 결정](docs/ARCHITECTURE.md)과 [데이터 계약](docs/DATA_CONTRACTS.md): 첫 구현의 경계와 필드·불변조건입니다.
5. [검증 목록](docs/ACCEPTANCE_TESTS.md): 단계별로 구현할 실패 사례와 완료 조건입니다.
6. [YouTube 댓글 수집 안내](docs/YOUTUBE_COLLECTION.md): API 키 발급, 첫 수집, 상한과 오류 처리입니다.

## 현재 범위

- 약 1,000개 댓글/스레드의 준비된 연구 snapshot을 목표로 합니다.
- 다국어 입력, 선택한 UI 언어 출력, 원문 인용 보존을 지향합니다.
- 검증된 cluster만 Perspective Agent가 됩니다. Rare/uncertain 관점도 근거와 함께 보존합니다.
- 각 agent의 증거와 대화 상태를 분리하고 Auditor가 답변을 수정하거나 거절할 수 있게 합니다.
- 첫 구현 목표는 Perspective Factory입니다. 최종 task 구성은 검증 결과에 따라 결정합니다.

## 저장소 경계

이 폴더가 독립 Git 저장소입니다. 수업 전체 폴더와 기존 발표 자료는 저장소에 포함하지 않습니다.
요구사항 원본은 상위 폴더의 `CommentScope_Implementation_Handoff_Requirements_2026-10-07.md`이며,
독립 clone에서도 읽을 수 있도록 동일 내용의 기준본을 `docs/requirements-handoff.md`에 포함합니다.
기준본의 Section 16을 우선하며, 향후 변경은 원본과의 차이 및 이유를 PR에 기록합니다.

실제 댓글, API 키, 대화 기록, 실행 결과는 기본적으로 Git에서 제외합니다.
공유 가능한 합성 테스트 데이터는 `tests/fixtures/`에 있습니다. 모델 weights도 올리지 않으며 원 배포처에서 별도로 받습니다.

## GitHub 연결 상태

공개 저장소: [joowonkime/commentscope](https://github.com/joowonkime/commentscope)

기본 브랜치는 `main`입니다. GitHub Issues/PR로 단계별 작업을 관리합니다.
실제 연구 데이터와 비밀 값은 공개 저장소에 포함하지 않습니다.

## 설치와 실행

Python 3.12 이상이 필요하며 현재 테스트 기준은 3.12입니다. 수집·검증에는 runtime 외부 의존성이 없고, clustering은 추가 설치가 필요합니다.
저장소 폴더에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m commentscope validate tests/fixtures/synthetic-snapshot.json
python -m commentscope normalize tests/fixtures/synthetic-snapshot.json --output artifacts/normalized.json
python -m unittest discover -s tests -v
```

Windows PowerShell에서는 `py -3.12 -m venv .venv`로 생성한 뒤 활성화 없이 `.venv\Scripts\python.exe`로 위의 `python` 명령을 실행할 수 있습니다.
설치하면 `commentscope validate ...` 형태의 console 명령도 제공됩니다.

현재 WSL처럼 `ensurepip`가 없지만 기존 Python에 pip가 있는 환경에서는 다음 경로를 사용할 수 있습니다.

```bash
python3 -m venv --without-pip .venv
python3 -m pip --python .venv install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m commentscope validate tests/fixtures/synthetic-snapshot.json
```

## 이번 단계에서 확인할 수 있는 것

- `validate`: 필드/타입/enum, UTF-8 JSON, 원문 ID, parent 관계, cycle, URL 및 timestamp 형식을 검사합니다.
- `normalize`: 원문을 보존하고 분석용 NFC·공백 정규화와 문맥별 중복 alias를 생성합니다.
- JSON 산출물에 입력 SHA-256, snapshot 전체, 원문/정규화 텍스트, 실행/정규화 버전과 집계를 보존합니다.
- 표본 예제의 결과는 원문 11개, top-level 9개, reply 2개, missing parent 1개, 중복 alias 1개입니다.

## 공식 API 댓글 수집

Google Cloud에서 YouTube Data API v3를 활성화하고 API 키를 만든 뒤 실행합니다.
키는 화면에 표시되지 않는 프롬프트에 입력하며, 영상 URL을 실제 선택한 영상으로 바꿉니다.

```bash
python -m commentscope collect-youtube "https://www.youtube.com/watch?v=VIDEO_ID" --prompt-key --max-comments 100 --top-level-limit 40 --output data/first-video.json
```

일반 실행에서는 `YOUTUBE_API_KEY` 환경변수도 사용할 수 있습니다. `.env` 자동 로딩은 하지 않습니다.
relevance/time을 섞어 조회하고 답글은 별도로 보완합니다. API의 표시 텍스트와 parent 관계를 보존합니다.
본문 100개가 아니라 **최상위 댓글과 답글을 합쳐 최대 100개**이며, 부족하면 실제 개수를 보고합니다.
실제 API 호출과 표본 1,000개 저장을 확인했습니다. 자세한 순서는 [수집 안내](docs/YOUTUBE_COLLECTION.md)를 따릅니다.
첫 cluster 품질 검증까지 기존 1,000개를 재사용하며 자동 재수집하지 않습니다. 전체 수집 또는 무작위 표집이 아닙니다.

같은 output 경로로 다시 실행하면 `OUTPUT_EXISTS` 오류를 반환합니다. 새 파일명을 지정해야 합니다.
입력 또는 기존 결과를 덮어쓰는 옵션은 없습니다. 파일시스템의 hard-link 지원이 필요하며 지원하지 않으면 저장 오류를 반환합니다.

성공은 stdout의 JSON과 종료 코드 0입니다. 입력 계약 오류는 stderr의 JSON과 코드 2,
입출력 오류는 stderr의 JSON과 코드 1입니다. CLI 인자 오류는 argparse의 도움말과 코드 2를 반환합니다.
`validate`는 파일을 생성하지 않고, 실패한 `normalize`는 완료 결과 파일을 남기지 않습니다.

## 검증과 다음 범위

[자동 테스트](tests/test_ingestion.py)는 S01–S12, 긴 reply chain, 중복 JSON key, 동시 저장, 파일 보존을 검사합니다.
PR과 main push에서 GitHub Actions가 Linux/Windows Python 3.12 설치·테스트·CLI 실행을 확인합니다.
CI 결과는 해당 PR의 Checks에서 확인합니다.

다음 사용자 확인 지점은 **실제 댓글의 주장 추출 품질을 확인하고 claim cluster로 연결하는 MVP**입니다.
로컬 모델 우선이며 품질 승인은 아직입니다. corpus 분석·외부 전송 사용 조건도 별도 검토 대상입니다. 인터페이스만을 MVP 완료로 간주하지 않습니다.
합성 JSON 예제와 Factory trace는 직접 작성한 자료이며 모델 결과나 다국어 분석 성능의 근거가 아닙니다.

## 로컬 모델 실행 (개발용, 아직 one-click 앱 아님)

현재 확인한 환경은 WSL/Linux, RTX4060 Laptop 8GB, Qwen3-4B-Instruct-2507 Q4_K_M입니다.
모델은 별도 프로세스에서 실행되며 Python 진단 스크립트는 `127.0.0.1:8091`로만 요청합니다.
댓글을 외부 모델 API로 보내지 않습니다. 최초 모델/패키지 다운로드에는 인터넷이 필요합니다.
다른 OS/GPU의 성능·설치는 아직 실측하지 않았습니다. 비개발 팀원은 우선 담당자가 만든 **로컬 HTML 검수 화면**으로 의견을 남길 수 있습니다.

### 1. 모델과 실행기 준비

- 실행기: [llama.cpp b11541 릴리스](https://github.com/ggml-org/llama.cpp/releases/tag/b11541)의 OS/GPU에 맞는 바이너리. NVIDIA는 해당 CUDA runtime도 필요합니다.
- 원 모델: [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).
- 사용한 양자화: [Unsloth GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/a06e946bb6b655725eafa393f4a9745d460374c9)의 `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`.
- 모델 파일과 실행기는 저장소 밖에 두세요. Git에 weights/API 키/실제 댓글을 추가하지 마세요. 각 배포처의 라이선스와 실행 환경 요구사항을 확인하세요.

`llama-server`가 PATH에 있고 필요한 라이브러리를 찾을 수 있는 환경에서, 별도 터미널에 실행합니다. `/absolute/path/...`는 실제 모델 경로로 바꿉니다.

```bash
llama-server -m /absolute/path/Qwen3-4B-Instruct-2507-Q4_K_M.gguf --host 127.0.0.1 --port 8091 -c 4096 -ngl 99 -t 6 --parallel 1
```

`--host 0.0.0.0`으로 외부에 노출하지 마세요. 메모리 부족 시 다른 GPU 작업을 종료하거나 offload 설정을 조정하고 변경 설정을 실행 기록에 남깁니다.
설정 변경의 품질·시간은 기존 결과와 동일하다고 가정하지 않습니다. 사용 후 서버 터미널에서 Ctrl+C로 종료합니다.

### 2. 공개 합성 예제로 연결 확인

위의 Python 기본 설치 후 다른 터미널에서 실행합니다. YouTube API 키는 필요 없습니다.

```bash
python experiments/local_claim_probe.py --snapshot tests/fixtures/synthetic-snapshot.json --output artifacts/synthetic-probe.json --limit 3 --revision v3 --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 context4096 parallel1"
```

출력은 JSON과 같은 이름의 `.html`입니다. HTML을 브라우저에서 열어 원문·모델 결과·계약 오류를 나란히 확인합니다.
이 합성 fixture는 수집 계약 예제이지 UBI 의미 평가셋이 아니므로 이 실행은 연결 확인용입니다.
`--model-label`, `--model-revision`, `--runtime`은 실제 설치에 맞춰 쓰는 사용자 선언이며 스크립트가 자동 검증한 값이 아닙니다.

### 3. 준비된 로컬 데이터 검증

`--snapshot`을 자신이 사용할 권한이 있는 snapshot 파일로, `--output`을 새로운 경로로 바꿉니다.
현재 단계는 snapshot 최대 1,000개, 기본 추출 표본 12개, seed 407입니다. 실험을 반복해도 YouTube API를 호출하지 않습니다.
프롬프트는 현재 UBI 주제용이므로 다른 영상에 적용할 때에는 주제와 프롬프트 버전을 함께 검토해야 합니다.

- 같은 표본 회귀 비교: `--replay-report artifacts/previous.json` (기존 보고서 전체 ID를 재사용; `--limit`보다 우선).
- 이전 표본과 겹치지 않는 표본: `--exclude-report artifacts/previous.json --limit 12 --seed 408`.
- 두 옵션은 동시에 쓸 수 없으며, snapshot hash가 다르면 거절합니다.
- `v2`/`v3`는 같은 prompt-0.2와 claims-0.2를 사용합니다. v3는 생성 스키마에서 eligibility와 claims 유무를 함께 제한합니다. 논문 설계의 clustering V2와 다른 버전입니다.
- 기존 결과는 덮어쓰지 않습니다. HTTP 오류는 실행을 중단하며, 이 진단 도구는 자동 retry/resume 또는 중간 결과 복구를 제공하지 않습니다.

`contract_pass`는 형식·인용 문자열·필드 일관성 검사입니다. 의미 정확도나 agent 승인 점수가 아닙니다.
모든 성공 결과도 `semantic_review_status=pending`이며 주장 누락·추가·조건 변경을 별도로 확인합니다.
실제 원문이 들어간 HTML/JSON은 공개 GitHub에 올리지 마세요.

### 4. 원문 기반 clustering 기준선 (별도 실험)

```bash
python -m pip install -e '.[clustering]'
python -m commentscope.cluster_baseline tests/fixtures/synthetic-snapshot.json --output artifacts/synthetic-clusters.json
```

처음에는 embedding 모델을 다운로드합니다. 실제 데이터로 실행하려면 입력 snapshot 경로만 교체합니다.
결과 화면은 `artifacts/synthetic-clusters.json.html`입니다. 이는 **원문 묶음 기준선**이며 claim 추출 결과를 연결하거나 agent를 생성하지 않습니다.
ML 의존성은 GPU 없이도 CPU에서 실행할 수 있지만 시간은 환경에 따라 달라집니다. 모델 실행은 CI에 포함되지 않으며 CI는 오프라인 계약 테스트를 수행합니다.
