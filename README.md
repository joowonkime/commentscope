# CommentScope

한 영상의 sampled comments에서 서로 다른 관점과 근거를 탐색하는 연구용 프로젝트입니다.

현재는 **1단계 구조·데이터 계약 설계 검토 단계**입니다. 실행 가능한 앱, 모델 파이프라인, 실제 연구 corpus는 아직 없습니다.
이어서 작업할 때는 [다음 세션 시작점](docs/NEXT_SESSION.md)을 먼저 확인합니다.

## 읽는 순서

1. [프로젝트 요구사항](docs/requirements-handoff.md): Section 16이 최신 구현 기준입니다.
2. [단계별 구현 계획](docs/IMPLEMENTATION_PLAN.md): 단계별 산출물과 완료 조건입니다.
3. [협업 방법](CONTRIBUTING.md): 브랜치, 변경 검토, 데이터 관리 규칙입니다.
4. [구조 결정](docs/ARCHITECTURE.md)과 [데이터 계약](docs/DATA_CONTRACTS.md): 첫 구현의 경계와 필드·불변조건입니다.
5. [검증 목록](docs/ACCEPTANCE_TESTS.md): 단계별로 구현할 실패 사례와 완료 조건입니다.

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

설계 검토 후 다음 작업은 **2단계: snapshot 검증·정규화 CLI와 테스트**입니다.
합성 JSON 예제는 설계 검토용이며 실행 모델의 결과가 아닙니다.
