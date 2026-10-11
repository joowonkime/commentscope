# 협업 방법

## 작은 변경 단위

1. Issue에 이번 작업의 목표와 완료 조건을 적습니다.
2. `feat/snapshot-contracts`, `fix/evidence-boundary`, `docs/factory-plan`처럼 목적이 드러나는 브랜치를 만듭니다.
3. 한 가지 목적의 변경과 필요한 검증을 함께 진행합니다.
4. PR에 변경 이유, 확인 방법, 한계 및 요구사항 변경 여부를 기록합니다.
5. 검토한 뒤 main에 합칩니다. 다음 단계는 앞 단계의 결과를 확인한 뒤 진행합니다.

첫 저장소 준비 commit 이후 기능 개발부터 이 흐름을 사용합니다.
GitHub 브랜치 보호와 필수 검사는 원격 저장소 연결 후 설정할 항목이며, 현재 적용된 상태가 아닙니다.

## main 중심 작업 규칙

- `main`을 최신 연구 프로토타입의 공통 시작점으로 사용합니다. 배포/품질 승인 브랜치라는 의미는 아닙니다.
- 새 작업은 최신 main에서 분기합니다. `main → 작업 브랜치 → 검증된 PR → main` 순서로 닫고 다음 작업을 시작합니다.
- 이전 Draft PR 위에 다음 기능을 계속 쌓지 않습니다. 의존 PR이 꼭 필요하면 base·의존 관계·통합 순서를 명시합니다.
- CI 성공은 코드 계약 회귀 확인입니다. 모델 충실성이나 실험 가설의 성공으로 해석하지 않습니다.
- 실험 코드는 실패 결과/기본값 승격 여부를 문서에 표시한 상태로 보존할 수 있습니다. 실패 실험을 성공으로 바꾸거나 삭제하지 않습니다.
- 누적 PR 통합에는 merge commit을 사용해 기존 커밋을 보존합니다. 통합 대상 PR은 최종 통합 PR을 연결한 뒤 정리합니다.
- 과거 브랜치 삭제·강제 push·리베이스·보호 설정 변경은 이번 기준선 정리의 범위에 포함하지 않습니다.
- 연구 데이터/키/로그는 공개 PR에 포함하지 않습니다. 완료 상태는 README, 상세 현재 작업은 NEXT_SESSION, 구조 결정은 ARCHITECTURE에 기록합니다.

## Commit 예시

```text
chore: initialize project planning repository
docs: define snapshot and claim contracts
feat: validate prepared dataset snapshots
test: reject citations outside perspective evidence
```

## 데이터와 실행 결과

- 키와 비밀 값은 `.env`에 보관하고 실제 값을 commit하지 않습니다.
- 실제 댓글과 study 데이터는 `data/`, 결과와 세션 기록은 `artifacts/` 또는 `runs/`에 둡니다.
- 공유 가능한 합성 테스트 데이터만 `tests/fixtures/`에 저장합니다.
- 결과 재현을 위해 데이터셋 버전, sampling rule, pipeline/model/prompt 버전을 기록하도록 구현합니다.
- 실행하지 못한 모델 테스트를 통과했다고 기록하지 않습니다.

## 요구사항 변경

`docs/requirements-handoff.md`의 Section 16을 기준으로 합니다.
기존 문구와 다른 결정을 내리면 설계 문서와 PR에 이유를 남깁니다.
원본 핸드오프와 저장소 기준본을 별개로 조용히 수정하지 않습니다.

## 원격 연결

기존 저장소가 있다면 그 URL을 먼저 확인합니다. 새 원격을 만들 경우 최초 연결이 단순하도록 빈 저장소를 사용합니다.
원격에 기존 commit이 있으면 fetch하여 내용을 확인하고 통합하며 강제 push로 덮어쓰지 않습니다.
로컬 초기화는 GitHub 저장소 생성이나 업로드를 의미하지 않습니다.
