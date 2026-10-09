# 다음 세션 시작점

사용자 요청에 따라 **1단계 설계를 마친 뒤 중단**합니다. 2단계 구현은 시작하지 않았습니다.

## 현재 상태

- 저장소: https://github.com/joowonkime/commentscope (public)
- 작업 브랜치: `docs/snapshot-contracts`
- Issue: https://github.com/joowonkime/commentscope/issues/1
- 이 브랜치는 설계 검토용입니다. main 반영 여부는 다음 세션에서 PR 상태를 확인합니다.
- 앱, Python 패키지, 실행 CLI, 실제 모델 연결, 연구 corpus는 아직 없습니다.
- `artifacts/`의 GitHub body 초안은 로컬 도구용이며 Git 추적 대상이 아닙니다.

## 이번 단계 산출물

1. [구조 결정](ARCHITECTURE.md): Python 3.12+, JSON, 첫 표준 라이브러리 구현, 모듈 의존 방향.
2. [데이터 계약](DATA_CONTRACTS.md): 필수 필드, source span, 문맥/근거 경계, 상태 전이, 실패 처리.
3. [검증 목록](ACCEPTANCE_TESTS.md): 2단계부터 구현할 성공·실패 사례.
4. [합성 snapshot](examples/synthetic-snapshot.json)과 [설계 trace](examples/synthetic-factory-trace.json).

## 확인한 것과 한계

JSON을 읽는 일회성 검증으로 다음을 확인했습니다.

- 댓글 11개, canonical 원문 10개, claim 8개의 ID와 참조가 일치합니다.
- 원문 좌표/quote가 한국어·영어 원문과 일치합니다.
- parent 관계, missing parent, eligibility와 duplicate alias가 일관됩니다.
- review를 순서대로 재생하면 split/merge에서 claim 유실·중복이 없습니다.
- accepted 2개, rare 1개, uncertain 1개가 남으며 accepted에만 PerspectiveSpec이 있습니다.
- 각 관점의 지지 원문은 3개이고, 카드의 인용은 배정된 claim 안에 있습니다.
- 설계 문서의 로컬 파일 링크와 Git whitespace 검사를 통과했습니다.

검증 스크립트는 일회성 설계 점검이며 제품 validator 또는 자동 테스트 suite가 아닙니다.
claim·review·카드는 직접 작성한 예시입니다. 실제 모델 추출, clustering 품질, 1,000개 규모 처리, UI는 검증하지 않았습니다.

## 재개 순서

1. `git status --short --branch`와 원격 PR 상태를 확인합니다. 기존 변경을 덮어쓰지 않습니다.
2. 이 설계를 검토하고 필요한 수정을 반영한 뒤 main에 통합합니다.
3. 별도 브랜치에서 2단계만 구현합니다: `pyproject.toml`, snapshot/comment 계약, loader, normalization, `validate`/`normalize` CLI, 합성 fixture, `unittest`.
4. 검증 목록의 S01–S12를 중심으로 검사하고 결과를 공유합니다.

provider/모델·embedding·실제 corpus 확보·최종 사용자 task는 아직 선택하지 않았습니다.
다음 단계의 구조 검증은 합성 fixture만으로 진행할 수 있습니다.
