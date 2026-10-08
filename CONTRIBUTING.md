# 협업 방법

## 작은 변경 단위

1. Issue에 이번 작업의 목표와 완료 조건을 적습니다.
2. `feat/snapshot-contracts`, `fix/evidence-boundary`, `docs/factory-plan`처럼 목적이 드러나는 브랜치를 만듭니다.
3. 한 가지 목적의 변경과 필요한 검증을 함께 진행합니다.
4. PR에 변경 이유, 확인 방법, 한계 및 요구사항 변경 여부를 기록합니다.
5. 검토한 뒤 main에 합칩니다. 다음 단계는 앞 단계의 결과를 확인한 뒤 진행합니다.

첫 저장소 준비 commit 이후 기능 개발부터 이 흐름을 사용합니다.
GitHub 브랜치 보호와 필수 검사는 원격 저장소 연결 후 설정할 항목이며, 현재 적용된 상태가 아닙니다.

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
