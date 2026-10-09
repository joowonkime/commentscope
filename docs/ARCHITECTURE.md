# 구조 결정 — 1단계

상태: 구현을 위한 설계 초안. 이 단계에서는 앱이나 모델을 실행하지 않습니다.
기준: [핸드오프 Section 16](requirements-handoff.md#16-implementation-default-specification-added-after-ambiguity-review).

## 첫 구현의 선택

| 항목 | 선택 | 이유 / 적용 범위 |
| --- | --- | --- |
| 런타임 | Python 3.12 이상 | 현재 개발 환경에서 사용 가능하며 Factory 실험과 데이터 처리를 한 프로젝트에서 진행 |
| 패키지 | `src/commentscope/`, `pyproject.toml` | 다음 단계에서 CLI와 테스트의 import 경로를 일관되게 구성 |
| 데이터 계약 | JSON 직렬화 + Python dataclass + 명시적 validation | 2단계는 표준 라이브러리로 시작; dataclass 자체가 validation을 보장하지는 않음 |
| 검사 | `unittest` | 초기 불변조건을 외부 모델이나 설치된 ML 도구 없이 검사 |
| 저장 | 불변 snapshot + run별 JSON 산출물 | 데이터셋과 파생 결과를 구분하고 실험을 재실행 |
| 실행 | 로컬 CLI, 단일 프로세스 | ingestion과 Factory부터 확인하고 같은 함수를 이후 API에서 호출 |
| 모델 | provider 인터페이스만 먼저 설계 | 실제 provider·모델·키·예산은 3단계 전에 선택 |
| clustering | 교체 가능한 구현 | 알고리즘·임계값은 데이터와 V0/V1/V2 실험으로 판단 |
| 웹 / 배포 | 이후 단계에서 선택 | Factory 계약과 사용자 task 확인 뒤 연결 |

Python/JSON/표준 라이브러리는 다음 단계의 기본값입니다. 모델 provider나 framework를 팀의 확정 합의로 간주하지 않습니다.

## 모듈 책임과 의존 방향

```text
CLI (이후 API도 같은 orchestration 호출)
  ├─ ingestion → contracts
  └─ factory   → contracts + provider interfaces + artifact storage
                       ↑
                 provider adapters

이후 agents → accepted PerspectiveSpec + scoped EvidenceBundle
이후 web    → API → factory의 저장된 결과 / agents
```

| 모듈 | 입력 → 출력 | 책임 |
| --- | --- | --- |
| `contracts` | JSON → 검증된 객체 또는 오류 | 타입, enum, 참조, 버전, ID 규칙; 모델/네트워크 호출 없음 |
| `ingestion` | DatasetSnapshot → NormalizedComment[] | 원문 보존, parent 관계 확인, 분석용 정규화, 문맥을 고려한 중복 처리 |
| `factory/extraction` | 원문+명시적 문맥 → EligibilityRecord[] + ClaimUnit[] | eligibility와 추출 결과를 검증; 누락·실패를 0개 claim과 구분 |
| `factory/candidates` | embedding item[] → CandidateCluster[] + unassigned IDs | 후보 생성; embedding space와 issue/stance 호환성 확인 |
| `factory/review` | 활성 후보+근거 → ClusterReview[] | 변경 제안 검증, 원자적 split/merge, terminal 상태 결정 |
| `factory/perspectives` | accepted 후보+claim → PerspectiveSpec[] | 카드 문장마다 근거 연결; rare/uncertain은 별도 결과에 보존 |
| `providers` | 범위가 제한된 요청 → 원시 모델 결과+호출 metadata | 추출·embedding·검토의 구현 교체; 결과 승인 권한은 없음 |
| `storage` | 검증된 산출물 → run별 파일 | 임시 파일 작성 후 교체; 실패 중간 결과를 완료 결과로 표시하지 않음 |
| 이후 `agents` | PerspectiveSpec+질문+개별 history → AnswerDraft → AuditDecision | evidence 범위 검사와 의미 감사 후 답변 공개 |

orchestration이 단계를 연결하고 실패/버전을 기록합니다. 도메인 함수가 환경변수나 전체 corpus를 임의로 읽지 않게 합니다.
API 키는 provider adapter 설정에만 전달합니다. source text와 모델 결과는 지시문이 아닌 입력 데이터로 취급합니다.

## 단계 사이의 계약

1. loader는 snapshot 전체의 구조와 관계를 검증한 뒤 분석에 넘깁니다.
2. normalization은 원문과 원문 좌표를 바꾸지 않고 분석용 텍스트를 따로 생성합니다.
3. extraction은 대상 원문마다 결과 또는 오류를 남깁니다. 판단할 수 없는 항목은 `unclear`로 남깁니다.
4. embedding은 입력 ID·순서·차원·유한 수 여부를 검증합니다. 서로 다른 모델의 벡터를 섞지 않습니다.
5. clustering은 모든 입력을 활성 후보 또는 unassigned 목록으로 설명합니다.
6. review는 기존 후보를 덮어쓰지 않습니다. 새 후보와 lineage를 기록하며 claim 유실·복제를 차단합니다.
7. PerspectiveSpec은 accepted 후보에서만 생성합니다. 인용과 카드의 지원 관계가 없으면 생성을 실패시킵니다.

세부 필드와 불변조건은 [데이터 계약](DATA_CONTRACTS.md)을 따릅니다.

## V0/V1/V2를 위한 공통 경계

- 같은 snapshot hash, normalization/eligibility 정책 및 비교 대상 원문 집합을 고정합니다.
- **V0:** eligibility gate 이후 원문을 embedding합니다. 단위가 `comment`이므로 ClaimUnit을 만든 것처럼 기록하지 않습니다.
- **V1:** 같은 원문에서 추출한 claim을 embedding하고 군집화합니다. 추출 실패나 0개 claim을 coverage에서 숨기지 않습니다.
- **V2:** V1의 저장된 claim·embedding·후보를 그대로 사용하고 검토 단계만 추가합니다. 별도로 재추출하지 않습니다.
- V0/V1의 자동 후보는 evaluation 결과이며 바로 사용자 agent가 되지 않습니다. 사용자 경로에 쓸 때에는 동일한 수동 검증 gate를 거칩니다.
- coverage 분모는 고정한 원문 집합입니다. 전체 source 수, eligible 수, 추출 성공/실패, 미배정, rare/uncertain 수도 별도로 기록합니다.
- human 평가 양식은 variant를 가리고 같은 표본 규칙으로 coherence·분리·claim–citation 지원을 측정합니다.

이 단계는 평가 경계를 정합니다. 실제 평가 도구·모델 성능·1,000개 처리 능력은 아직 검증하지 않았습니다.

## 실행 결과와 실패

`artifacts/<run_id>/`에 manifest, normalized comments, eligibility, claims, embeddings, candidates, review events,
perspectives, errors를 별도 파일로 저장할 예정입니다. 변경된 snapshot·코드·prompt·config는 새 run을 만듭니다.

run 상태는 `running | completed | failed`입니다. source별 실패가 있으면 오류 artifact는 보존하지만 run은 `failed`이며,
정상 완료로 재사용하거나 제품에 노출하지 않습니다. 의미상 불확실한 `unclear`/`uncertain`은 기술 실패와 구분합니다.
첫 구현은 자동 재시작·부분 resume을 제공하지 않습니다. 재실행은 새 run으로 시작합니다.

fixture provider는 오프라인 계약 확인용으로만 표시합니다. 실제 provider 실패를 fixture로 조용히 대체하지 않습니다.
fallback은 명시적으로 선택한 준비된 결과만 사용하며 원래 run과 분리합니다.

## 이번 설계의 구체화와 유보

- 댓글 전체를 읽을 수 있어도 배정되지 않은 claim을 자기 관점의 증거로 사용할 수 없습니다.
- 동일 문구라도 서로 다른 parent 아래의 reply는 의미가 다를 수 있어 자동 중복 제거하지 않습니다.
- 누락된 parent를 명시한 snapshot은 허용하지만, parent가 없는데 있다고 표시한 데이터는 거절합니다.
- 분석용 영어 claim 필드를 초기 기본값으로 제안합니다. 원문은 보존하고 출력 언어는 별개로 처리합니다. 영어 피벗의 의미 손실은 다국어 표본 평가 대상입니다.
- 신뢰도 점수는 보정된 확률이 아니며 단독 승인 기준으로 사용하지 않습니다. 임계값은 이후 버전 있는 config에 기록합니다.
- split/merge는 승인과 별개의 작업입니다. 재구성된 후보도 다시 검토해야 합니다.

## 2단계의 정확한 범위

`pyproject.toml`, snapshot/comment 계약, snapshot loader, normalization, CLI `validate`/`normalize`, 합성 fixture 및 검사만 구현합니다.
claim 추출·모델 호출·clustering·UI는 포함하지 않습니다. 다음 설계 필드가 모두 한 번에 구현되어야 한다는 뜻은 아닙니다.

목표 명령(아직 실행 불가):

```bash
python -m commentscope validate tests/fixtures/synthetic-snapshot.json
python -m commentscope normalize tests/fixtures/synthetic-snapshot.json --output artifacts/normalized.json
python -m unittest discover -s tests
```
