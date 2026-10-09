# CommentScope

한 영상의 sampled comments에서 서로 다른 관점과 근거를 탐색하는 연구용 프로젝트입니다.

현재는 **snapshot 검증·정규화와 공식 YouTube API 수집 CLI 구현 단계**입니다. 모델 파이프라인·웹 앱·실제 연구 corpus는 아직 없습니다.
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
공유 가능한 합성 테스트 데이터는 추후 `tests/fixtures/`에 추가합니다.

## GitHub 연결 상태

공개 저장소: [joowonkime/commentscope](https://github.com/joowonkime/commentscope)

기본 브랜치는 `main`입니다. GitHub Issues/PR로 단계별 작업을 관리합니다.
실제 연구 데이터와 비밀 값은 공개 저장소에 포함하지 않습니다.

## 설치와 실행

Python 3.12 이상이 필요하며 현재 테스트 기준은 3.12입니다. runtime 외부 의존성은 없습니다.
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
실제 키를 사용한 호출은 아직 검증하지 않았습니다. 자세한 순서는 [수집 안내](docs/YOUTUBE_COLLECTION.md)를 따릅니다.

같은 output 경로로 다시 실행하면 `OUTPUT_EXISTS` 오류를 반환합니다. 새 파일명을 지정해야 합니다.
입력 또는 기존 결과를 덮어쓰는 옵션은 없습니다. 파일시스템의 hard-link 지원이 필요하며 지원하지 않으면 저장 오류를 반환합니다.

성공은 stdout의 JSON과 종료 코드 0입니다. 입력 계약 오류는 stderr의 JSON과 코드 2,
입출력 오류는 stderr의 JSON과 코드 1입니다. CLI 인자 오류는 argparse의 도움말과 코드 2를 반환합니다.
`validate`는 파일을 생성하지 않고, 실패한 `normalize`는 완료 결과 파일을 남기지 않습니다.

## 검증과 다음 범위

[자동 테스트](tests/test_ingestion.py)는 S01–S12, 긴 reply chain, 중복 JSON key, 동시 저장, 파일 보존을 검사합니다.
PR과 main push에서 GitHub Actions가 Linux/Windows Python 3.12 설치·테스트·CLI 실행을 확인합니다.
CI 결과는 해당 PR의 Checks에서 확인합니다.

다음 사용자 확인 지점은 **실제 영상·API 키로 소량 수집 후 cluster 결과까지 연결하는 MVP**입니다.
실제 모델 provider·예산과 corpus 분석 사용 조건은 아직 정하지 않았습니다. 인터페이스만을 별도 MVP 완료로 간주하지 않습니다.
합성 JSON 예제와 Factory trace는 직접 작성한 자료이며 모델 결과나 다국어 분석 성능의 근거가 아닙니다.
