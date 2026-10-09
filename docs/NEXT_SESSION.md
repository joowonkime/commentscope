# 다음 세션 시작점

**2단계 snapshot 검증·정규화 CLI까지 구현했습니다.** 3단계 모델 연결·claim 추출·clustering은 시작하지 않았습니다.

## 현재 상태

- 저장소: https://github.com/joowonkime/commentscope (public)
- 작업 브랜치: `feat/snapshot-ingestion`
- Issue: https://github.com/joowonkime/commentscope/issues/3
- 1단계 설계 PR #2는 main에 반영했습니다. 2단계 PR의 병합/CI 상태는 다음 세션에서 확인합니다.
- 실제 연구 corpus와 모델 provider는 아직 없습니다. 합성 표본으로 ingestion만 검증합니다.

## 실행 위치와 명령

저장소 루트는 `term-project/commentscope/`입니다. 현재 WSL에 `.venv`를 만들고 editable install했습니다.
이 환경은 ensurepip가 없어 기존 pip의 `--python .venv` 설치 경로를 사용했습니다. 일반 설치와 Windows 실행법은 README를 따릅니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m commentscope validate tests/fixtures/synthetic-snapshot.json
.venv/bin/python -m commentscope normalize tests/fixtures/synthetic-snapshot.json --output artifacts/next-normalized.json
```

output이 이미 있으면 새 파일명을 사용합니다. 로컬 결과 `artifacts/step2-normalized.json`과 GitHub body 초안은 Git에서 제외됩니다.

## 구현한 것과 확인 결과

- strict UTF-8 JSON parser, immutable snapshot/comment 계약, parent 관계와 cycle 검사.
- 원문 보존, 분석용 NFC/공백 정규화, parent별 중복 alias.
- 입력 byte SHA-256, 버전·집계·원문을 포함하는 normalization artifact.
- 기존 파일을 덮어쓰지 않는 원자적 저장과 구조화된 CLI 오류.
- S01–S12를 포함하는 29개 unittest 메서드: 로컬 Python 3.12에서 통과.
- console entry point와 module CLI 직접 실행: 표본 원문 11개, canonical 10개, alias 1개 확인.
- GitHub Linux/Windows Python 3.12 CI 설정. 최종 결과는 PR Checks에서 확인합니다.

테스트의 2,000개 합성 reply chain은 관계 검사 범위입니다. 1,000개 corpus의 모델 처리 성능을 검증한 것이 아닙니다.
실제 의미 분류, 다국어 추출, embedding, Factory, agent, UI는 아직 구현하지 않았습니다.

## 재개 순서

1. `git status --short --branch`와 해당 PR의 CI·검토 상태를 확인합니다.
2. 2단계 변경을 검토해 main에 반영한 뒤 새 브랜치를 만듭니다.
3. 3단계는 먼저 EligibilityRecord/ClaimUnit 계약과 provider 인터페이스를 구현합니다.
4. source span, 조건 보존, context와 evidence 분리, 누락 응답 및 실패 처리 검사를 먼저 추가합니다.
5. 실제 모델 연결 전 provider·모델·키 소유자·예산을 결정합니다. 실제 연구 corpus 확보 방식도 아직 미결정입니다.

[구조 결정](ARCHITECTURE.md), [데이터 계약](DATA_CONTRACTS.md), [검증 목록](ACCEPTANCE_TESTS.md)을 기준으로 이어갑니다.
