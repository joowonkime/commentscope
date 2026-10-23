# 구조 결정 — 1단계

현재 상태는 [현재 구조와 채택 상태](CURRENT_ARCHITECTURE.md)를 먼저 확인한다.
아래 상단은 초기 설계 기록이며 현재 구현 완료표가 아니다. 2026-10-13부터 다음 실험의 우선순위는 ADR-035의 실제 데이터 비교 준비다.

상태 (2026-10-10): 공식 API 수집·snapshot 검증·정규화 및 로컬 V0 원문 clustering 실행 완료.
로컬 claim 추출은 실험 중이며 claims-0.2 계약/검증과 prompt revision을 추가했습니다. 전체 Factory·에이전트·서비스 UI는 미구현입니다.
이 문서의 하단 결정 기록과 모듈별 상태가 과거 단계 설명보다 우선합니다.
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
| `ingestion/youtube` | 선택한 영상+수집 설정 → DatasetSnapshot | 공식 API transport 주입, bounded 표집·답글 수집·provenance 기록 |
| `factory/extraction` | 원문+명시적 문맥 → EligibilityRecord[] + ClaimUnit[] | eligibility와 추출 결과를 검증; 누락·실패를 0개 claim과 구분 |
| `factory/candidates` | embedding item[] → CandidateCluster[] + unassigned IDs | 후보 생성; embedding space와 issue/stance 호환성 확인 |
| `factory/review` | 활성 후보+근거 → ClusterReview[] | 변경 제안 검증, 원자적 split/merge, terminal 상태 결정 |
| `factory/perspectives` | accepted 후보+claim → PerspectiveSpec[] | 카드 문장마다 근거 연결; rare/uncertain은 별도 결과에 보존 |
| `providers` | 범위가 제한된 요청 → 원시 모델 결과+호출 metadata | 추출·embedding·검토의 구현 교체; 결과 승인 권한은 없음 |
| `storage` | 검증된 산출물 → run별 파일 | 임시 파일 작성·동기화 후 hard link로 새 경로에 원자적 공개; 기존 파일 교체 금지 |
| 이후 `agents` | PerspectiveSpec+질문+개별 history → AnswerDraft → AuditDecision | evidence 범위 검사와 의미 감사 후 답변 공개 |

orchestration이 단계를 연결하고 실패/버전을 기록합니다. 도메인 함수가 환경변수나 전체 corpus를 임의로 읽지 않게 합니다.
API 키는 provider adapter 설정에만 전달합니다. source text와 모델 결과는 지시문이 아닌 입력 데이터로 취급합니다.

YouTube API 키는 별도 read-only `YouTubeClient`에만 전달합니다. `collect-youtube` 명령만 네트워크를 사용하며
기존 validate/normalize는 오프라인입니다. 댓글 데이터 확보를 구체화한 개발자용 도구이며 공개 URL ingestion 서비스는 아닙니다.
[수집 안내](YOUTUBE_COLLECTION.md)에 API 반환 텍스트의 의미, partial 상태와 보관 한계를 기록했습니다.

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

정정 (2026-10-10): 1,000개 중 999 canonical comments에 대한 raw V0 실행은 완료했습니다.
현재 `cluster_baseline.py`는 eligibility를 적용하지 않은 탐색용 기준선입니다. 위의 공정한 V0/V1/V2 비교 설정을 충족한 논문 실험으로 간주하지 않습니다.

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

패키지 설치 후 실행 가능한 명령:

```bash
python -m commentscope validate tests/fixtures/synthetic-snapshot.json
python -m commentscope normalize tests/fixtures/synthetic-snapshot.json --output artifacts/normalized.json
python -m unittest discover -s tests
```

2단계의 초기 JSON envelope는 normalization 결과 전용입니다. 향후 Factory run 저장 형태와 구분합니다.
계약 오류/저장 실패 경로를 포함한 검사는 [tests/test_ingestion.py](../tests/test_ingestion.py)에 있습니다.
GitHub Actions의 checkout/setup-python은 공식 사용법을 확인하고 commit SHA로 고정했습니다:
[checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python).

## 교체 가능한 경계와 실제 상태 (2026-10-10)

| 단계 | 현재 구현/설계 위치 | 입력 → 출력 | 교체 시 재실행 범위 |
| --- | --- | --- | --- |
| 수집 | `ingestion/youtube.py`, `youtube_client.py` 구현 | 영상/설정 → snapshot-0.1 | 데이터 변경이면 전 단계; 기존 snapshot은 그대로 보관 |
| 정규화 | `ingestion/normalize.py` 구현 | snapshot → 원문 ID를 유지한 분석 텍스트 | 추출/embedding 이후 |
| 추출 계약 | `contracts/claims.py` 구현 | 원시 모델 JSON + target → 오류 또는 source-bound claim | 호환되지 않는 변경이면 추출 이후 |
| 프롬프트 | `claim_prompt.py` revision 0.2 | 대상/문맥 역할 설명 → 모델 지시문 | 추출 이후; 원본/V0는 재사용 |
| 로컬 추론 | `experiments/local_claim_probe.py`의 loopback HTTP 실험 | prompt+target+parent → JSON/시간/token/종료 이유 | 모델 변경 시 추출 및 후속 단계만; provider adapter 분리는 후속 |
| 후보 clustering | `cluster_baseline.py`의 raw V0 구현 | canonical 원문 → 후보/근거/검수 HTML | embedding 고정이면 clustering 이후; 현재 V0는 벡터를 별도 저장하지 않아 재임베딩 필요 |
| claim clustering | `factory/claim_clusters.py` 소표본 연결 구현 (2026-10-11) | 추출 artifact+snapshot → 검증된 출처/실패 목록+claim embedding+후보 | 후보 이후; 벡터와 정확한 입력을 저장하되 CLI 자동 재사용은 후속 |
| 의미 검수 | AI 보조 탐색 기록만 존재 | 후보+원문 → 검수 판단 | review 이후 |
| 대표 명세 | 승인된 PerspectiveSpec은 설계만; `factory/perspective_drafts.py`에 미승인 로컬 초안 실험 구현 (2026-10-11) | 후보/원문 → 배정·공통 주장·세부 문장/근거 | 초안/검수 이후 |
| agent / 답변 검수 | 설계만 존재 | 명세+허용 근거+질문 → 감사된 답변 | 해당 agent 단계; upstream 명세는 유지 |

단일 프로세스/로컬 JSON을 유지합니다. 모듈 교체를 위해 별도 마이크로서비스를 만들지는 않습니다.
각 단계는 자신이 받은 입력과 명시된 근거만 사용하며, 모델 결과가 원문 ID/승인 상태를 임의 결정하지 못하게 합니다.

## 아키텍처 결정 기록

새 결정은 아래에 추가하며 과거 결정을 조용히 지우지 않습니다. 각 항목은 상태·이유·대안·영향 범위를 기록합니다.

### ADR-001 — 대표성 우선 (accepted, 2026-10-10)

- 결정: 의미 있는 공통 주장을 충실히 대변하는 agent가 목적. 대립/찬반 균형은 요구하지 않음.
- 이유: 댓글을 토론 구도에 맞추면 원문을 왜곡할 수 있음.
- 대안: 찬반 진영을 먼저 정해 배정하는 방식은 채택하지 않음.
- 영향: eligibility, cluster gate, PerspectiveSpec, 사용자 평가. 같은 공통 주장 아래의 서로 다른 경험은 자동 split하지 않음.

### ADR-002 — 로컬 모델 우선, 품질 승인은 별개 (accepted direction, 2026-10-10)

- 결정: 로컬 소형 모델을 우선 평가. 현재 시험 모델은 Qwen3-4B-Instruct-2507 Q4_K_M / llama.cpp CUDA.
- 이유: RTX4060 Laptop 8GB에서 실행 가능하며 호출 비용과 외부 전송을 줄임.
- 대안: 더 큰 로컬 모델, 유료 API, 혼합 구성은 비교 후 선택. 현재 모델을 영구 고정하거나 API와 동등하다고 간주하지 않음.
- 영향: provider 구현과 실행 설정. contracts/claim IDs/품질 기준은 모델과 독립적으로 유지.

### ADR-003 — 구조 검증과 의미 검수 분리 (accepted, 2026-10-10)

- 결정: JSON grammar + deterministic validator + semantic review를 별개로 둠.
- 이유: 첫 probe는 JSON/인용 문자열 검사12/12 성공했지만 의미 있는 경험 누락과 eligibility 모순이 있었음.
- 계약0.2: stance_target, personal/general scope, modality, reason/condition별 target 원문 quote. 모델은 source ID를 생성하지 않음.
- 구조 검증 실패 시 원시 결과와 오류를 보존하고 downstream 승인 불가. 조용한 자동 수정/삭제 금지.
- 구조 검증 성공도 `semantic_review_status=pending`; 실제 이유/인용의 함의 관계와 누락은 자동 보장되지 않음.
- 대안: 문법만 강제하고 바로 agent로 승격하는 방식은 채택하지 않음.

### ADR-004 — AI 초안 + 사용자 피드백 (accepted development workflow, 2026-10-10)

- 결정: AI가 표본과 검수 초안을 만들고 사용자가 피드백. 전체 1,000개 인간 전수 라벨링은 초기 요구가 아님.
- 이유: 검수 부담을 줄이면서 실제 실패를 발견하고 의미 기준을 맞춤.
- 한계: 초안은 독립 gold가 아님. 개선에 쓴 표본은 development set; 새 평가 표본과 분리.
- 영향: 평가 기록에 작성자/수정자, 버전, 선택 규칙, 불일치·수정 이력을 남김. 논문용 최종 평가 설계는 후속.

### ADR-005 — 버전과 산출물로 교체/회귀 추적 (accepted, 2026-10-10)

- 결정: source snapshot은 불변, prompt/schema/모델 revision은 명시, 실행 결과는 새 파일로 보존.
- 실험 manifest: snapshot SHA256, prompt 본문/version/hash, schema version/hash, 모델 revision/quantization/runtime, seed/temperature/max_tokens/context, 개별 output·오류·시간/token.
- 현재 probe v1→v2는 prompt/schema/grammar/output budget을 함께 변경하므로 단일 요소의 인과 효과를 주장하지 않음.
- 앞으로 기본 rule: 코드/설계는 Git commit, 실제 원문·출력·키·모델 weights는 Git 제외. prompt 변경 후 같은 development case로 회귀 검사하고 별도 표본으로 일반화 검사.
- 대안: 결과 덮어쓰기, prompt를 코드 곳곳에 복제, 모델 변경과 corpus 변경을 섞는 실행은 금지.
- 한계: 전체 DAG 자동 invalidation/cache/replay는 아직 미구현. 위의 재실행 범위는 수동 운영 규칙이며 자동 기능으로 보고하지 않음.

### ADR-006 — 표본 고정 및 생성 grammar 분리 (accepted experiment, 2026-10-10)

- 첫 cluster 품질 확인까지 기존 1,000개를 재사용하고 추가 YouTube 호출/전체 수집 확장을 하지 않음. 보관 만료는 별도로 준수.
- claim-generation-0.3은 claims-0.2 출력 계약을 바꾸지 않고, 생성 grammar의 anyOf 분기로 substantive는 1개 이상, 나머지는 빈 claims만 허용.
- 대안: 모델 출력에서 claims를 사후 삭제하는 자동 수정은 하지 않음. 실패 결과와 validator를 유지.
- 같은 snapshot/prompt/모델/설정에서 v2→v3의 실제 JSON 변경은 사례 7/8뿐. 계약 통과 8/12→10/12. 의미적 정확도 개선 전체를 증명하지 않음.
- 새 seed408 표본 12개는 기존 12개 ID를 제외. 계약 11/12지만 의미 검수에서 조건 반전·개인 범위 오분류·짧은 주장 누락 확인. 출시/agent 승격 보류.
- 공개 실행기는 private ID/정답을 내장하지 않음. local 보고서로 replay/exclude하며 snapshot hash를 검사. 실제 원문/결과와 모델 파일은 Git 제외.
- 영향 범위: `contracts/claim_generation.py`, 진단 CLI, README. provider adapter와 전체 Factory 연결은 여전히 후속.

### ADR-007 — 작은 claim-cluster 연결부터 검증 (accepted development slice, 2026-10-11)

- 결정: 기존 V0의 자동화·물가·짧은 반응 묶음을 골라 주장 추출부터 후보/검수 HTML까지 연결. 목적 표집임을 명시하며 정확도·대표성 실험으로 보고하지 않음.
- 대안: 아직 검증되지 않은 extractor를 즉시 1,000개 전체/agent에 적용하지 않음. 이번에는 prompt-0.2와 grammar-0.3을 유지해 연결 단계에서 생기는 문제를 분리.
- 새 경계: `factory/claim_clusters.py`가 snapshot hash, 실제 target/parent 텍스트, claims-0.2, 종료 상태를 재검증. 저장된 contract_pass/bound_claims는 신뢰하지 않고 ID를 재생성.
- 모든 선택 source를 included/blocked/duplicate_alias로 기록. 오류와 0 claims를 구분. 크기는 unique canonical source 수로 세며 하나의 댓글의 여러 claim으로 지지수를 부풀리지 않음.
- embedding은 기존 고정 MiniLM/CPU chunk pooling. 입력 문장과 claim ID 순서 및 벡터를 함께 저장. 작은 표본용 결정적 cosine-average-linkage 구현을 사용하며 60 sources/300 claims로 제한. stance label은 경고로 표시하고 자동 분할/승인 기준으로 쓰지 않음.
- semantic gate 이전 후보 생성은 진단용으로만 허용. AI review artifact는 candidate 파일 hash와 소속 claim을 검사. 전체 묶음 제안은 모든 member와 3개 이상 source를 설명해야 함. AI가 accepted로 승격하는 경로는 제공하지 않음.
- 상위 계획의 실패 run 노출 금지와 구분: 실패를 포함한 결과 화면은 개발자 진단 artifact이며 정상 완료된 제품 Factory run이 아님. agent가 소비할 수 없음.
- 분리 제안은 부모 claim 전체를 자식에 중복/누락 없이 배정하는지 검증하고 저장. 제안된 자식의 공통 주장·근거·유보사항을 HTML에서 확인 가능. 실제 후보 재배정/승인으로 간주하지 않음.
- 미구현: 생산용 provider/orchestrator, 자동 의미 검수, 실행된 split/merge lineage, 사람 승인 저장 흐름, PerspectiveSpec/agent. 현재 검수 초안은 사용자가 확인할 제안이지 최종 승인 아님.

### ADR-008 — 대표 주장 생성과 근거 검사의 권한 분리 (experimental, 2026-10-11)

- `providers/local_llama.py`: loopback만 호출, proxy/redirect 금지. 생성 transport는 승인 권한 없음. 기존 claim probe는 아직 자체 transport를 사용하며 전체 통합은 후속.
- `factory/perspective_drafts.py`: 기존 assistant 검수 초안 없이 원문/후보에서 로컬 초안 생성. 저장된 후보를 snapshot/추출 hash와 전체 claim partition으로 재검증.
- v1 `perspective-draft-0.1`: 모델이 member 배정과 부분 인용을 생성. 누락/변형 인용 때문에 3개 후보 전부 계약 실패.
- v2 `perspective-assignment-0.2`: 모든 member를 필수 object key로 요구. 공통 주장에는 해당 그룹 전체 원문, detail에는 모델이 고른 그룹 내 ID의 전체 원문을 호스트가 연결. 누락·위조 인용 기회를 줄이나 의미 지원은 보장하지 않음.
- v2는 prompt/input/schema/citation 방식이 모두 달라 단일 요소 개선 효과로 주장하지 않음. 출력 변환은 명시적 wire→canonical binding이며 원시 모델 JSON을 보존.
- `factory/draft_audit.py`: 원문–문장 쌍에 supported/partial/unsupported/unclear 제안. 같은 모델의 두 번째 판단이며 독립 gold 아님. supported 오판·불필요한 기각을 실제 발견; 승인 gate로 단독 사용 금지.
- 양쪽 모두 후보별 checkpoint/원시 결과/오류/버전/hash를 보존. 대형 입력 실험 설정은 context8192/no-context-shift, 모든 metadata는 실행자 선언임을 표시.
- 승인 PerspectiveSpec과 구분해 accepted_perspectives=0, semantic_review_status=pending 유지. 생성→검사 성공만으로 agent를 만들지 않음.
- 다음 검토 대상: ID만 적힌 placeholder 문장 차단, 문장-원문 단위 입력으로 검사 문맥 간섭 완화, 예측/필요성 구분. 전체 corpus 확대보다 현재 실패 수정 우선.

### ADR-009 — 쌍별 독립 요청과 규칙 차단의 분리 (experimental, 2026-10-11)

- 결정: `draft_audit --mode pairwise`에서 한 제안 문장–한 인용 TARGET만 새 요청으로 검사. 기존 batch/SYSTEM/판정 스키마/모델 설정은 비교용으로 유지합니다. 독립 요청은 독립 평가자나 독립 gold를 뜻하지 않습니다.
- 이유: batch에서 다른 문장의 필요성·일자리 논리를 가져와 타당한 예측을 거절하거나, ID placeholder를 주장으로 해석하는 실패가 관찰됐습니다.
- ID-only는 좁은 deterministic lint로 모델 호출 전에 차단. `verdict_origin`으로 코드 규칙과 모델 판단을 구분하고 합산 정확도를 주장하지 않습니다. 모든 의미 검사를 규칙으로 대체하지 않습니다.
- 변경 범위: audit 실행/저장/진단 HTML만 변경. 수집·claim 추출·embedding·후보·대표 초안은 재생성하지 않음. pair별 checkpoint 보존, 자동 resume/승인은 미구현.
- 실제 22쌍 = 모델18회 + 규칙4쌍. 총 모델 호출시간 합15.38초(서버 로딩 제외, prompt cache 포함). 이전 batch14.32초와 단일 실행 비교일 뿐 일반 성능 추정 아님.
- 실행 전 작성한 assistant 기대 판단 8개 중 모델 판정 일치5개(이전1개), ID-only 기대4개는 규칙으로4개 차단. 알려진 실패 중심의 개발 회귀 표본이므로 정확도 점수나 인간 gold로 보고하지 않음.
- 과장 일부를 잡았으나 원문과 동등한 문장도 여전히 partial로 판정. 다른 문장이 없어도 필요성/인과성 조건을 불필요하게 요구하므로 문맥 분리만으로 해결되지 않음. prompt 내 경고의 과잉 적용은 다음에 검증할 가설이지 확정 원인 아님.
- 다음 대안: 동일 pairwise 입력/설정을 고정하고 텍스트 함의 검사 prompt만 수정하는 실험. 댓글 주장의 사실 여부와 제안 문장이 댓글에 충실한지를 구분. 검사 자동승격 금지 및 새로운 표본/사용자 검토 필요성 유지.

### ADR-010 — 프롬프트 단독 변경을 보존하되 기본값 승격 보류 (experimental, 2026-10-11)

- audit prompt-0.2는 댓글의 사실 여부/정책 타당성과 원문에 대한 충실성을 구분. 기존 pairwise의 입력·판정 형식·모델 설정·lint를 유지하며 `--prompt-revision v2`로만 선택합니다.
- 같은 개발 22쌍(모델18회+lint4쌍)에서 사전 작성한 모델 기대8사례의 일치5→5. 예측2건의 불필요한 거절은 교정됐으나 과장2건을 다시 supported로 판정. 일부 문장/이유의 오류도 남아 기본 prompt는 v1 유지. 단순 supported 증가를 개선으로 보지 않습니다.
- 별도 생성 실험 draft prompt-0.3은 v2 입력/assignment wire/원문 binding을 고정. 원문별 공통 주장 검토, 세부 문장의 실질 내용, 예측/필요성 분리를 강조. 생성 revision과 audit prompt revision은 독립 선택입니다.
- 생성 후보3개 중 구조 통과2개. ID-only 상세는 사라졌으나 자동화 묶음은 필요성/예측을 계속 혼합했고, 물가 묶음은 서로 다른 주장을 같은 common에 배정. 나머지 후보는 비제외 배정에 제외 사유를 붙여 차단. 생성 기본값도 v2 유지.
- 관찰은 현재 Qwen4B 양자화/프롬프트/목적 표본의 한계이지 모든 로컬 모델의 불가능성 증명은 아닙니다. 합성 코드 테스트는 요청 경계와 재현 조건을 검증할 뿐 의미 정확도를 검증하지 않습니다.
- 대안/후속: 자유로운 그룹 배정+요약을 한 번에 맡기는 대신 원문별 assertion type/modality/조건 확인과 그룹 공통 명제 생성을 분리하는 소표본 실험을 검토. 필요 시 다른 로컬 모델과 동일 표본 비교. 이번에는 새 모델 다운로드/유료 API/전체 corpus 확장을 하지 않음.
- 원래 초안과 실패·회귀를 모두 보존. assistant 수정 제안은 별도 기록하며 로컬 모델 산출물이나 인간 승인으로 위장하지 않습니다.

### ADR-011 — 범위 동결과 실패 단계 분리 (development diagnostic, 2026-10-11)

- 사용자 우려: clustering부터 문제라면 프로젝트 범위가 커지는 것 아닌가. 목표는 기존 영상→댓글→충실한 주장 묶음→검수된 agent를 유지. 신규 debate/서비스/agent 기능, 새 모델, 전체 corpus 확장 없이 고정9개로 실패 위치부터 확인합니다.
- `experiments/source_frame_probe.py`: 기존 후보/출처 검증을 재사용하는 개발 진단만 추가. production extractor/군집/대표 생성/승인 계약은 변경하지 않습니다.
- 원문과 기존 claim의 embedding을 동일 선택 subset/알고리즘/임계값에서 비교. 0.45에서는 둘 다9개 단일 후보. 0.25/0.35에서도 예측/필요성 혼합이 남음. 임계값 변경만으로 해결되거나 추출만이 유일한 원인이라고 주장할 수 없음.
- 원문 M04의 도입 예측은 기존 claim 단계에서 이미 필요성·일자리 이유가 추가됨. 별도 대표 생성은 원문을 직접 읽어도 과장했으므로, 추출과 합성 양쪽의 오류를 구분합니다.
- 원문 한 개씩 assertion type/certainty/이유·조건 인용만 출력: 구조9/9, 사전 assistant 기대와 type8/9·certainty6/9. 시간 표현을 논리 조건처럼 뽑는 오류도 남음. 재서술을 없앤 실험이므로 paraphrase 품질 향상/새 extractor 성공으로 보고하지 않습니다.
- 결정: embedding은 주제상 후보를 좁히는 역할로 유지하고, 다음 수정 한 곳은 관점 승격 전 원문별 주장/조건 확인에 집중. label을 강제 그룹 경계로 사용하지 않음. 모델 검사만으로 승인하지 않고 기존 사용자 검토 경계를 유지합니다.
- 종료/확장 기준: 고정 사례의 이유 추가·예측→필요성 변경·조건 누락을 해결하지 않은 채 새 기능을 붙이지 않음. 수정 결과는 아직 사용하지 않은 소표본에서 확인한 뒤 확대 검토. 지금은 진단만 완료했으며 확정 cluster/agent는0.

### ADR-012 — 생성 대신 원문 선택 + 직접 지원 배정 (experimental B, 2026-10-11)

- 사용자 원칙: 기존 댓글을 왜곡하지 않는 것이 우선. 자유 요약/배정의 대안으로 `factory/extractive_keypoints.py`를 추가. 기존 기본 pipeline은 바꾸지 않음.
- 경계: 검증된 기존 후보 → `anchors_for`(호스트가 전체 원문/offset/source를 고정) → `judge`/`score_pairs`(방향 있는 지원 관계) → `assemble`(코드 배정) → 미승인 HTML. 모델은 대표 문장이나 ID를 작성할 수 없음. 기존 추출문은 관계 판단 입력에서 제외하지만 후보 선택에 따른 편향은 남음.
- 후보 전체를 대표 후보로 사용. source당1개 claim, 최대12개 source/원문500자. 이는 장문·다중 주장·문맥 해소까지 해결한 extractor가 아님. N×(N−1) 호출, 동일 원문은 `identity_text_only`로 구분하고 모델 정확도에 합산하지 않음.
- 코드 배정은 greedy disjoint star cover: 각 member→대표의 직접 supports만 인정, 알려진 양방향 contradiction이 있으면 동시 포함 금지. 연결 요소/추이적 지지 추론/모든 pair가 서로 동등한 clique가 아님. 크기→짧은 대표→ID로 결정하며 충돌 가지치기는 member ID 순서에 의존. 최소3개의 서로 다른 source, 미배정 원문도 보존.
- API/파싱/완료 상태 오류는 지원 edge가 될 수 없음. 단, 오류가 없다는 것이 의미적 지원 증명은 아니며 contradiction 판정도 모델 오류에 취약. 모든 결과는 needs_human_review, accepted_perspectives=0.
- 고정9개 실제 실행: 72회/16.77초, 2묶음에7개 배정/2개 미배정. 사전 부정 회귀9쌍 중8개를 지지하지 않는 것으로 판정했지만 다른 배정에서 필요성→도입 예측 오류를 발견. 두 묶음 모두 수정 필요. 이 수치는 정확도/일반화 성능이 아니며, 새 relation prompt/schema도 바뀌어 extractive 변경만의 인과 효과를 분리할 수 없음.
- 다음 수정 한 곳: 원문–대표 관계 판정기. 후보/대표/배정 알고리즘은 고정해 비교하며 긍정·부정·애매 사례를 포함한 검수와 미사용 표본 확인이 필요. 프롬프트 반복만으로 해결됐다고 주장하거나 지금 전체 corpus/agent로 확대하지 않음. 다른 로컬 판정기 검토는 후속; Jev 비교는 외부 전송/비용 조건 결정 전 실행하지 않음.
- 영향: 신규 모듈/합성 테스트/설명 문서만 공개. 실제 입력/출력/검수는 ignored artifacts에 보존, snapshot 만료 상속. 자동 resume/사람 승인 저장/프로덕션 agent 연결은 미구현.

### ADR-013 — 고정 입력으로 로컬 NLI 비교, 기본값 승격 보류 (experiment, 2026-10-11)

- ADR-012의 원문/대표/배정 코드를 유지하고 `providers/local_nli.py`만 판정 대안으로 추가. 기존 Qwen 경로는 수정하지 않음. `experiments.compare_local_nli`에서 동일72쌍과 합성20사례를 비교.
- 영어용 DeBERTa-v3-base-mnli-fever-anli를 revision 고정/safetensors/remote code 금지/offline CPU로 사용. 전용 NLI의 entailment/neutral/contradiction을 공통 relation으로 매핑, 최고 softmax<0.8은 unclear. 임계값은 실행 전 고정했으나 보정된 confidence가 아님. 모델과 판정 정책이 함께 달라 단일요소 효과를 주장하지 않음.
- 원문=전제, 대표=가설 순서를 테스트. 입력 길이 초과/오류 시 조용한 truncation/승인 대신 실패. 쌍/모델 raw logits와 scores, 환경, 평가표/사전 계획/기존 결과/배정 코드 hash를 기록. 동일 원문은 의미 평가 점수에서 제외.
- 실제 부정12쌍 비지지8→12, 필요성→도입 오연결3건 제거. 그러나 합성 조건 삭제를 supports로 판정(0.987), 정상 연결은 양쪽7/8, 실제3개 이상 그룹은2→0. 부분 개선을 clustering 성공으로 보고할 수 없음.
- 결정: baseline 기본값 유지, threshold 튜닝/추가 모델 반복/전체 corpus 확장하지 않음. 다음 판단에는 사용자 의미 기준 피드백 및 실제 긍정 pair 검수가 필요. 합성 표본은 실제 positive recall이 아니며, unknown 실제 표본/다국어 검증이 남음.
- 한계: snapshot 만료/입력 출처는 재검증하나 Qwen 서버 identity는 운영자 선언. NLI threshold는 미보정이고 영문 범위만 확인. 성능은 CPU/GPU 단일 실행의 관찰. auto approval/agent는0. 자세한 실행은 LOCAL_NLI_COMPARISON.md 참조.

### ADR-014 — 원문 보존형 계열 제안과 명시적 assistant 수정 (assisted experiment, 2026-10-11)

- 사용자 요청: assistant가 평가→수정 루프를 맡고 논문에 사용할 기록을 남김. 자유 요약 대신 topic/type/polarity/원문 구절을 분류하고, 이유·조건·표현 강도는 전체 원문 카드로 보존하는 별도 실험 추가. 이전 문장 전체 entailment와 다른 과제이며 성능 수치를 직접 비교하지 않음.
- `factory/source_facets.py`: 한정된 자동화–UBI 주제의 계열명은 코드로 생성. type/polarity에 따라 제안하되 mixed/unclear/기타/범위 밖/계약 실패는 보류, 3개 미만은 희소 상태. 같은 계열이 모든 member의 조건·이유까지 공유한다는 뜻은 아님. 일반 clustering/동적 agent 전체 구현이 아님.
- `experiments.source_facet_loop`: source-bound 기대값을 모델에 전달하지 않고 개별 원문만 분류. snapshot/plan/code/prompt hash, 원시 출력/checkpoint, 입력 겹침/원문/만료 검사와 전체 원문 보존. 두 revision 모두 개발8/9로 사전 자동 성공 기준9/9 실패.
- 실패 후 프로토콜 변경을 명시적으로 저장하고 v2 고정 확인12개를 진단. 계약10/12·사전 기준 일치5/12로 실패. 확인 표본은 reviewer가 구현 전에 읽어 blind holdout이 아니며 재튜닝하지 않더라도 논문 독립 검증 아님.
- `experiments.review_source_facets`: assistant가21개 전수 검수해 확인13/수정8. confirm/correct/abstain과 한국어 근거·해석·보존할 차이를 저장. 수정은 입력 hash에 묶고 model_result를 보존, origin=assistant_review로 분리. 기대값 자동 복사나 실패 출력 덮어쓰기 없이 새 결과를 만듦.
- 검수 결과 필요성7/도입 예측4/가능한 이점2/보류8. 지지수3개 이상 계열2개는 검수 제안일 뿐 accepted_perspectives=0. 원문 보존이 agent 발화의 충실성을 보장하지 않음. 기존 pipeline 기본값/모델 변경 없음.
- 한계/후속: assistant 자기 검수는 독립 gold가 아니므로 정확도100%로 보고 금지. 독립 평가·미사용 표본·다국어·복합 주장 분해·실제 agent 검증이 남음. 자세한 기록/실행/프로토콜은 SOURCE_FACET_REVIEW_LOOP.md.

### ADR-015 — 검수 입력에서 독립 에이전트 응답으로 연결 (development vertical slice, 2026-10-11)

- 사용자 정정: clustering 연구가 아니라 댓글 기반 관점 에이전트 시스템 전체가 프로젝트/논문 대상. Section16.4의 end-to-end 우선 순서로 돌아가 기존 검수 입력을 runtime에 연결. 추가 clustering 튜닝은 하지 않음.
- `agents/profiles.py`: snapshot/검수 hash, 만료, 원문, canonical source, 전체 배정을 재검증. 3개 이상 계열만 동적으로 개발용 프로필 생성. 이유·조건은 개별 원문/검수 해석/주의사항에 귀속, 희소/보류 항목은 에이전트로 승격하지 않음.
- 기존 production PerspectiveSpec은 accepted claim cluster를 요구하므로 별도 development-perspective-bundle-0.1 사용. build와ask 모두 --allow-unapproved를 요구. 사람 승인/accepted_perspectives=0을 유지하면서 실제 개발용 AgentSession2개는 실행됨. 이 수와 승인 agent 수를 혼동하지 않음.
- `agents/runtime.py`: 같은 기반 모델을 독립 evidence/state로 호출. 다른 agent 응답을 전달하지 않고 자기 최근2개 대화만 참조. 질문/이전 출력은 증거가 아님. 한 문장=한 source ID, 호스트가 원문 인용을 고정.
- 형식/ID 검사→별도 모델Auditor→최대1회수정→통과 또는보류. 모든 문장이 supported여야 개발용 답변 표시. 거절 초안과 미검사 자유문 한계 설명은 최종 HTML에서 숨김. 원시/검사/수정 기록은 private JSON에 보존. Auditor는 같은 모델로 독립 정확성 보장이 없으며 실제 과도한 거절을 발견함.
- 현재 로컬 CLI+저장 HTML 비교. 웹서비스/사용자 입력 서버/에이전트간 토론/Reflection은 구현하지 않음. 전달 경로와 보관은 기존 localhost/JSON/expiry 경계 유지. 상태 변경/재시도/오류/코드·모델·schema·prompt provenance 기록.
- 실제3질문×2agent 보완 실행: 관점 설명2답변은 원문 지원 확인, 과장 전제 질문2건은 보류(감사 오류 포함), 근거 없는 국가별 수치2건은 보류. 4개 표시 문장을 assistant가 원문 대조했지만 독립 평가 아님. 전체 프로젝트/논문 검증 완료로 보고하지 않음.
- 다음 시스템 단계: 비교/질의 웹UI와 원문 inspect 동선, 정식 PerspectiveSpec 승격과 evidence-bounded 대화/토론, Reflection/전체시스템 독립평가. Auditor의 질문 관련성/원문 지원 혼동은 별도 수정 지점으로 기록하고 clustering 실험으로 되돌리지 않음.

### ADR-016 — 로컬 비교/질의 UI와 세션·증거 경계 (2026-10-11)

- ADR-015의 저장형 HTML에 직접 질문 경로를 추가. 모델/생성·감사 프롬프트/승인 조건/cluster 배정은 변경하지 않음.
  `agents/web.py`(HTTP·세션·작업·private checkpoints) → 기존 `AgentSession`(생성·검사) → `demo.render`(저장형 export).
  `comparison.html/js/css`는 프레임워크/외부 asset 없는 브라우저 클라이언트이며 모델 호출을 직접 하지 않음.
- 기존 Python 표준 라이브러리로 loopback 전용 구현. 사용자 승인 없는 외부 호스팅/업로드를 하지 않으며 공개 서비스용 서버가 아님.
  Host allowlist, same-origin POST, 별도 메모리 session token, no-store/CSP, 요청 크기 제한, 임의 파일 경로 미제공.
  이는 로컬 브라우저 경계이며 같은 OS 사용자의 악성 프로세스로부터 데이터를 보호하는 로그인 체계는 아님.
- 브라우저 세션마다 모든 AgentSession을 새로 생성. 에이전트별 evidence/history 격리 유지. 로컬 모델은 한 번에 한 질문만 처리,
  질문 내 agent는 순차 실행. 다른 질문은 409로 거절해 무제한 큐를 만들지 않음. request_id 재전송은 중복 추론하지 않음.
- 요청은 비동기 작업 + polling. 생성/검사 단계 및 요청 수만 공개, 거절 초안/감사 이유/미검사 한계 설명은 live API에서 제외.
  모든 agent 완료·출처 재검증·저장 후에만 비교 round 공개. 중간 실패 시 해당 질문의 agent histories 모두 원복.
- 세션당 6질문(실패 포함 제출 12회 상한), 메모리 세션 최대8개/비활성1시간. 시작/질문 전/게시 전 출처 검증,
  모델 호출 전/게시·조회·내보내기 시 보관 만료 검사. 기존 다운로드 파일의 만료 접근 차단·자동 삭제는 불가능하므로 별도 보관 책임.
- `runs/agent-ui/<uuid>/`에 세션 manifest, 질문 request, agent별 전체 turn, 완료 round를 덮어쓰기 없이 저장.
  새 대화는 history 초기화이지 로그 삭제가 아님. 서버 재시작/브라우저 새로고침 자동 복원은 미지원.
- 모델 서버 identity는 여전히 운영자 선언. UI는 정식 승인0/동일 모델 감사/표본 한계를 표시.
  실제 브라우저 시각 QA는 이번 환경에서 미수행. HTTP 회귀 + Node의 최소 DOM 계약 검사는 레이아웃 검증을 대체하지 않음.
- 다음 교체 지점: HTTP/UI와 무관하게 auditor 교체 가능. 에이전트 간 반문/토론은 별도 메시지 계약으로 구현해야 하며
  동료 발언을 지지 evidence나 자기 검수 history로 승격하지 않을 것. Reflection/시스템 전체 사용자 평가도 별도 남음.

### ADR-017 — 서비스 실행 중 수동 개입 없는 자동 Factory (2026-10-11)

- 사용자 최신 결정: 서비스에서 사람이 분류·묶음 수정·승인하지 않음. ADR-014/015의 assistant 검수는
  개발 비교 기준으로만 유지하며 새 자동 경로의 입력으로 사용하지 않음. 품질의 사후 표본 평가는 별개.
- `automatic_contract.py`(원문 구간 선택·주장/검사 계약) → `automatic.py`(embedding top-k 후보·직접 지지 gate·
  결정론적 disjoint support-star) → automatic bundle → 기존 AgentSession/UI로 연결.
  주제 whitelist 없음. 의미 판정은 모델, 출처/개수/범위/배정/예산/재시도 경계는 코드가 담당.
- 후보는 cosine/표현 유형으로 찾지만 후보 유사도만으로 agent를 만들지 않음. 각 member는 anchor의 공통 주장을
  직접 지지해야 하며 self gate도 필수. 최소 서로 다른 canonical 댓글 3개, 중복 alias 제외.
  형식만 한 번 수정, 의미 실패는 보류. source/claim 누락·예산 제한·0 agent를 결과에 명시.
- 새 `auto_accepted_unvalidated`는 사람 승인을 기다리는 상태가 아니라 자동 정책 통과/독립 품질 평가 전 상태.
  production PerspectiveSpec의 품질 검증 완료를 가장하지 않음. human_handling=false, accepted_perspectives=0을
  별도로 기록. 서비스-time 사람 승인 플래그를 추가하지 않음.
- 원문 전체를 agent에 주는 기존 개발 경로와 달리 자동 경로는 배정된 span과 claim scope만 전달하고 답변도
  같은 범위에서 검사. 원문 전체/부모는 인용 문맥으로 보존. 공통 주장은 검사된 anchor statement를 사용하며
  추가 자유 요약 단계에서 주장·이유를 다시 만들지 않음.
- 모듈별 교체 가능 지점: 추출 provider/schema, embedding/retriever, 의미 gate, group policy, profile adapter.
  기존 UI/답변 시스템 전체를 갈아엎지 않음. checkpoint는 입력/설정/코드/prompt hash에 연결하고 재시도/거절도 보존.
- 한계: gate가 같은 모델이므로 의미 보장은 없음. greedy 순서/top-k/표현 유형 제한은 누락·분할·중복 관점을 만들 수 있음.
  지지 수는 사람 수가 아님. 0 agent/낮은 coverage는 실행 완료일 수 있어도 품질 성공은 아님.
  독립 평가와 품질·coverage의 사전 기준이 필요. 실행 명령과 제한은 AUTOMATIC_FACTORY.md 참조.

### ADR-018 — 부모 문맥 및 생성 라벨의 증거 오염 분리 (2026-10-11)

- ADR-017의 입력 경계를 부분 대체합니다. 0.1 실제 실행에서 부모의 상세 주장이 짧은 동의 답글로 전이됐고,
  생성된 claim/title을 제공받은 답변·감사도 이를 반복했습니다. 금지 프롬프트만으로 막히지 않았습니다.
- Factory 0.2의 추출 입력은 자기 댓글의 구간만 포함합니다. parent 텍스트는 코드에서 전달하지 않습니다.
  `context_dependent`는 독립 명제가 없는 동의/참조 반응이며 claims는 빈 배열입니다. 실제 동의 대상이나 stance를
  자동 확정하는 관계 추출은 아직 없으며, source/parent 관계는 원본 snapshot에 보존합니다.
- 묶음 후보를 비교하기 전에 별도 SOURCE_AUDIT에 해당 member의 원문 span과 검사할 주장만 전달합니다.
  다른 member·공통 주장·parent를 보지 않습니다. 실패하면 common gate를 호출하지 않고 해당 edge를 거절합니다.
  동일 member 입력 검사는 immutable Calls cache로 재사용합니다. 고정 edge 예산은 유지하되 모델 호출 수는 늘어납니다.
- 자동 agent의 생성에는 claim/title/profile을 주지 않고 배정 원문 span만 줍니다. 첫 감사는 POINT와 원문만,
  첫 감사 통과 후 두 번째 감사는 POINT와 allowed_claim의 범위만 비교합니다. 둘 다 통과해야 공개합니다.
  scope 판정은 원문의 지지를 증명하거나 원문 검사 거절을 구제할 수 없습니다. 기존 검수 기반 agent는 유지합니다.
- 원문/부모/생성 라벨은 화면·citation에서 이력 확인용으로 보존합니다. 과거0.1 보고서와 bundle은 그대로 읽되,
  새0.2 보고서에는 각 edge의 source_audit가 필수입니다. 재실행은 새 디렉터리이며 과거 membership을 수정하지 않습니다.
- 잔여 위험: 같은 모델의 오승인, 잘못 선택된 span, scope·시점·조건 오분류, 한국어 오역은 남습니다.
  배정 구간이 넓으면 불필요한 생성 후 scope 거절이 늘 수 있습니다. 이번 변경은 의미 보증이나 독립 검증이 아닙니다.
  작은 실제 회귀와 고정 표본부터 확인하며, 전체1,000개 재실행/검색 정책 변경은 별도 단계입니다.

### ADR-019 — 명시적 호환성 필터의 분리와 실패 시 기본 미채택 (2026-10-11)

- ADR-018 기본 경로는 유지합니다. `factory/claim_frame.py`에 범위·시점·표현 강도·조건 분류와
  코드 비교를 격리했습니다. 추출·embedding·그룹 배정·AgentSession을 바꾸지 않고 이 모듈만 교체할 수 있습니다.
- 원문 span과 추출 claim은 각각 별도로 분류합니다. 다른 member/parent/common claim/평가 라벨을 주지 않습니다.
  현재 분류기는 scope/status, commitment, time, condition의4요청으로 나누고, time 요청만 같은 텍스트의
  fallible commitment를 추가로 받습니다. 같은 텍스트는 cache를 재사용하므로 독립 심사자4명이 아닙니다.
- 호스트는 필드 불일치·unclear·비단일 주장을 거절합니다. 조건은 원문 내 정확한 인용이어야 하고,
  양쪽에 조건이 있다는 사실만으로 통과시키지 않습니다. 동일 조건 외에는 별도 등가성 판정이 필요합니다.
  이 필터 통과도 원문 충실성/common gate를 대체하지 않습니다. 지리·수량 제한 등 모든 의미 범위를 포괄하지 않습니다.
- 판정 trace에 입력 hash, 각 요청/응답/오류, 합성 필드, 조건 비교, 거절 사유를 보존하고 replay로 재계산합니다.
  필드 비교 코드는 결정적이지만 입력 라벨 자체는 모델 판단입니다. 원문 인용 일치는 해석 정확성 보장이 아닙니다.
- 고정 합성16쌍·기존 개발18쌍을 두 방식으로 검사했습니다. 한 요청 방식은 정상 합성3/7유지,
  분해 방식은0/7유지로 실패했습니다. 전부 거절은 성공이 아닙니다. 세부 결과는 AUTOMATIC_FACTORY에 기록합니다.
- 따라서 `automatic-factory-0.3`은 CLI `--experimental-frame-guard` 또는 run의
  `experimental_frames=True`로만 실행합니다. 기본은0.2이며0.1/0.2 과거 산출물을 재표기하지 않습니다.
  실패한 필터로 전체1,000개 재실행/agent 승격을 하지 않습니다. 다음 비교도 양성 보존과 음성 차단을 함께 봅니다.

### ADR-020 — 생성형 필드 분류와 직접 NLI 지지 판정 비교 (2026-10-11)

- ADR-019의 기본 미채택 결정은 유지합니다. 필드를 또 생성하는 대신 이미 설치된 영어 NLI 모델로
  원문→claim 지지를 직접 비교하는 offline 실험 `experiments/claim_support_probe.py`를 추가했습니다.
  Qwen 프롬프트/추출/검색/배정이나 서비스 기본 판정기는 변경하지 않습니다. 모델 가중치만 바꾼 비교가 아니라
  판정 구조 전체의 비교입니다. 평가 라벨과 이전 frame 출력은 추론 입력에 포함하지 않습니다.
- directional은 anchor 원문→anchor claim, member 원문→member claim, member 원문→anchor claim의
  세 검사를 모두 요구합니다. mutual_claims는 claim 간 양방향 지지까지 추가합니다. source 검사 실패는
  다른 검사로 구제하지 않습니다. 원문 구간은 순서대로 줄바꿈으로 연결하며 부모 문맥을 더하지 않습니다.
- 같은34개 고정 사례, 모델 revision, 기존 threshold0.8, 두 정책 및 다음 단계 조건을 manifest에 먼저 기록합니다.
  새 모델 다운로드/threshold 탐색/평가 정답 수정은 하지 않습니다. 합성·실제 각각의 양성/음성이 모두 맞고
  실행 오류가 없어야 다음 통합 후보이며, 이 기준도 독립 품질 승인 기준이 아니라 개발 회귀 조건입니다.
- 두 정책 모두 합성 양성7/7·음성8/9, 실제 양성5/7. 실제 음성은 directional10/11,
  mutual11/11입니다. 합성 현재/미래 혼합과 실제 물가 원문2개의 과잉 거절로 다음 단계 조건에 실패했습니다.
  실제 양성에서 anchor self case를 제외하면1/3 유지입니다. 정상 claim을 충분히 묶었다고 보고하지 않습니다.
- 양방향 동치는 서로 다른 상세 근거를 가진 올바른 공통 관점도 거절할 수 있어 서비스 원칙으로 승격하지 않습니다.
  높은 NLI 점수도 시점 오류를 놓쳤습니다. 다음 설계는 시간 보존 검사와 최소 공통 명제 탐색을 별도 경계로 다뤄야 하며,
  후자는 아직 미구현 가설입니다. 기존 판정기의 미해결 품질 문제도 그대로 남습니다.

### ADR-021 — 시간 보존과 공통 명제 탐색 분리 및 기능 진단 (2026-10-12)

- ADR-020 다음 작업을 구현했습니다. `temporal_guard.py`는 시간/표현 강도, `shared_core.py`는 공통 명제 후보와
  원문 지지, `core_groups.py`는 고정 공통 명제에 대한 직접 배정을 담당합니다. 기본 Factory0.2/opt-in frame0.3은 변경하지 않습니다.
- 시간/강도 분류는 기존 두 단일 작업 프롬프트를 유지하고, 명시적 영어 will/would 및 일부 'd 행동 동사에 한해
  원문 offset을 보존하는 제한된 lexical correction을 추가했습니다. 경쟁 modal/hope/일부 과거 표지가 있으면 보정하지 않습니다.
  이것은 일반 문법 분석기나 다국어 시간 보증이 아니며, 문맥 속 인용/여러 절/복잡한 시제는 한계입니다.
- 모델은 두 claim에서 최대1개의 공통 후보만 제안합니다. 두 원래 claim과 생성 후보(중복 제외 최대3개)를 고정해 검사하고,
  각 원문→자기 claim 충실성, 시간/강도 호환성, 각 원문→core 및 각 claim→core 지지를 모두 요구합니다.
  지원 후보 중 짧은 것을 선택하는 휴리스틱이지 수학적으로 최소인 공통 의미 탐색이 아닙니다. semantic retry는 하지 않습니다.
- 영어 if/unless 등의 명시적 조건은 operator와 antecedent를 분리합니다. 원문 인용은 그대로 기록하고
  선행 조건 내용에만 NLI 양방향 등가성을 검사합니다. 여러 조건은 보류하며 완전한 조건/범위 분석이라고 주장하지 않습니다.
  'I would' 등 명시적 개인 행동 표지의 유무가 달라지면 원문→claim, claim쌍, claim→core에서 별도로 차단합니다.
- v2 lexical correction은 실제 양성 보존을 높였지만 개인→일반 합성 오류를 새로 통과시켰습니다.
  v3는 개인 행동 표지 차단을 추가했습니다. 모든 중간 결과/기대 라벨/threshold0.8은 그대로 보존합니다.
  최신 고정 사례는 합성 정상6/7·오류9/9, 실제 정상6/7·오류11/11이며 새 주제12개는 정상5/6·오류6/6입니다.
  원래 개발 통과 조건은 여전히 실패입니다. 실제 양성 중 self4개를 제외하면2/3이며, 취직/계속 근무 뉘앙스도 사후 검토 대상으로 남습니다.
- 사용자의 전체 진행 요청에 따라 **품질 승격과 분리한 기능 진단**을 명시적으로 추가했습니다. 실행 전 manifest에
  `quality_gate_passed=false`와 protocol amendment를 저장하며 `--diagnostic-only`가 필수입니다.
  이전 실패를 통과로 바꾼 것이 아닙니다. 기존 source-only0.2의64개 이하 추출만 받고, 새 수집/전체1,000개 확장은 금지합니다.
- 조립은 anchor당 최대2개 seed pair, 전체 결정 예산, 그룹당 최대9개 원문/10,000자를 따릅니다.
  seed에서 core를 고정하고 나머지 member를 모두 같은 core에 직접 검사합니다. 3개 canonical 원문 미만은 agent가 아니며
  간접 연결을 통해 합치지 않습니다. 프로필은 기존 AgentSession에 연결되지만 승인0이며 기본 UI/서비스 loader에 승격하지 않습니다.
- 실제64개 기능 진단은123claims→28seed decisions→0agents, 미배정123, 예산 미소진입니다.
  exact-input cache로 판정/조립 replay를 확인했습니다. 합성 테스트에서는3-source profile→기존 AgentSession 응답 연결까지 확인했지만
  실제 새 agent 답변 검증은0개이므로 하지 못했습니다. 전체 MVP 완료가 아닙니다.

## ADR 022 후보 검색과 방향성 의미 보존 진단

- 상태: 실험 구현, 기본 Factory0.2 미변경. ADR-021 결과를 덮어쓰지 않습니다.
- 후보 검색은 판단과 분리합니다. 동일123개 claim/vector에서 유형 일치+cosine0.55/top8,
  유형 제한 제거+동일 threshold/top8, 유형 제한 없는 semantic8+lexical4를 비교합니다.
  hybrid의 낮은 유사도 후보도 비교 대상일 뿐 가입 승인이 아닙니다. 한 source의 claim끼리는 연결하지 않습니다.
- `grounded_core.py`는 시간/태도 범주명의 equality 대신 원문→검사 문장의 직접 지지와
  범위·시점·강도·조건·부정·전제 보존을 검사합니다. 기존 NLI threshold0.8과 source-only 격리는 유지합니다.
  NLI 실패는 LLM 판정으로 구제하지 않으며, 원문 인용 substring 검증은 의미 보증과 구분합니다.
- 공통 후보는1회 제안+입력 claim2개의 고정 집합입니다. 전부 원문/claim별로 검증하고 제안한 교집합을 우선합니다.
  문자열 최단 선택을 제거하지만 이것만으로 최소 공통 명제의 정확성이 보증되지는 않습니다.
- 조립은 명시적 cross_mode 옵션일 때만 다른 분류 유형을 허용합니다. 최소3개 canonical source,
  고정 core에 대한 직접 가입 검사, seed2개/결정64개/원문10,000자 제한은 유지합니다.
- 평가 프로토콜은 실행 전에 고정합니다. 기존 합성16개·실제18개·추가주제12개는 관점 연결 라벨 그대로 유지하고,
  새 합성12개는 특정 대표 문장이 원문에 충실한지 별도로 평가합니다. self control과 cross-source 결과를 구분합니다.
  개발 라벨은 inference 입력에 전달하지 않습니다. 실패 후의64개 조립도 진단일 뿐 품질 승격이 아닙니다.
- 다음 승격 조건은 고정 검사에서 중요 왜곡 오승인 없음, 생성 core의 사후 충실성 평가, 미사용 실제 평가,
  원문에 충실한 agent 답변입니다. 결과에 맞춘 threshold/기대값 조정이나 전체1,000개 재실행은 하지 않습니다.
- 첫 실행은 직접 감사에서도 미래→현재/조건 삭제를 오승인했습니다. 후속 `qualification_guards`는 영어 원문 표지의
  위치를 기록하고 명시적 시간 변화/조건 연산자 개수 변화를 거절합니다. 시간 표지가 없거나 복합/인용 문장이면
  이 코드만으로 판정하지 않습니다. 조건 동의어는 문장 단위 의미 검사에 맡깁니다. 다국어 parser가 아닙니다.
- 후속 고정 합성7/7·9/9, 실제5/7·11/11, 추가주제6/6·6/6, exact4/6·6/6.
  실제 nonself 정상1/3이며 오탈자 조건 표현을 과잉 거절합니다. 연결 라벨 통과와 core 충실성은 다릅니다.
- 실제64개 조립은123claims/seed64개/새 agent0개/예산 소진입니다. 고유66개 검사 중31개 source 통과,
  11개 seed에서 공통 제안까지 갔지만 성공0입니다. 검색 후보를 넓힌 것만으로 agent 생성은 개선되지 않았습니다.
- 별도12개 source 새 추출20개 중 모델 승인12개. 사후 검토에서 새 의미 추가2개와 독립성 실패1개,
  자기 댓글 문맥을 선택 span에서 누락한 문제가 남았습니다. 이 표본은 과거 full1000에 포함됐으며 독립 gold가 아닙니다.
  source-only는 parent-blind라는 뜻이지 필요한 자기 댓글 문맥을 버리라는 뜻이 아닙니다.
- 결정: 기본 채택하지 않습니다. 다음은 독립적인 실질 주장 eligibility, 자기 댓글 내부의 evidence-context 완성,
  추출/판정 부품의 별도 비교입니다. 재추출/문맥 보완은 이 ADR의 완료 기능이 아니며 후속 구현입니다.
  혼합 검색에서 거의 모든 목록이12개가 되면 degree 기반 anchor 순서가 ID 순서에 가까워지는 예산 한계도 분리 측정합니다.

## ADR 023 원문 선택과 자기 댓글 문맥

- 상태: 진단 구현. ADR-022의 실패를 보존하고 기본 Factory0.2는 변경하지 않습니다.
- 원인 가설을 분리합니다. 재작성된 claim의 의미 추가, 자기 댓글 내 근거 문맥 누락, 문자적 함의와 독립적 주장
  eligibility의 혼동, 그리고 포화된 이웃 수로 인한 seed 예산 낭비를 각각 검사합니다.
- `evidence_units`는 모델에 연속 sentence-ID 범위만 선택하게 합니다. statement는 host가 원문에서 복사하므로
  모델이 단어/번역/해석을 새로 추가할 출력 필드가 없습니다. 원문 위치·source digest·선택 범위를 다시 조립해 검증합니다.
  이것은 문자 보존의 구조적 보장이지 선택된 발언의 의미·인용 맥락·중요성에 대한 보장은 아닙니다.
- 독립적인 eligibility 호출은 전체 자기 댓글과 focus만 받습니다. substantive 판정과 원문에 있는 concrete topic quote가
  필요합니다. 영어 지시어/기능어뿐인 focus는 host에서도 거절합니다. 임의 언어·대명사를 전부 판별하는 parser는 아닙니다.
- 짧은 댓글은 전체 자기 댓글을, 긴 댓글은 focus/topic을 포함하는 연속 범위와 인접 문장을 evidence로 보존합니다.
  최대500자이며 넘으면 보류하고 자르지 않습니다. parent/다른 사람의 댓글은 어떤 단계에서도 원문 근거에 넣지 않습니다.
- `evidence_core`는 retrieval focus를 별도 사실 권위로 보지 않습니다. 공통 문장 자체의 독립성 검사와 각 원문의
  직접 지지를 요구합니다. 검증된 원문 표현을 우선하고 없을 때만1회 공통 제안을 검증합니다. 의미 판정기는 여전히 fallible입니다.
- 조립은 최소3개 canonical source를 유지하며 새 source_density 순서는 서로 다른 두 이웃 source의 유사도로 우선순위를
  정합니다. degree 순서와 동일 입력/후보/모델/64결정 예산으로 비교합니다. 유사도는 가입 승인 기준이 아닙니다.
- 사전 고정 검증: 합성16개(개발/전이 각각8개), 기존 실제12개, 별도 hash-order12개 확인 표본을 고정합니다.
  확인 표본은 이번 수정에 사용하지 않지만 과거 full1000 실행에는 포함돼 있어 독립 gold/완전 미사용 corpus는 아닙니다.
- 원인 ablation은 기존20개 claim을 바꾸지 않고 같은 checker에서 기존 span과 전체 짧은 자기 댓글을 비교합니다.
  문자 변조 검사는 임의100개 원문에서 수행하며, 이것을 의미 정확도100%로 보고하지 않습니다.
- 기능 검증은 기존64개 새 선택 추출 뒤 실행합니다. 추가32개는 기존 검색 기하에서 자동 선택한 밀집 표본이며
  새 source-only 추출을 수행합니다. 과거 claim이나 사람 labels는 새 모델 입력이 아니고, 이 표본은 대표성 평가가 아닙니다.
  전체1,000개 새 추출·수집은 하지 않습니다. 실제 profile이 나오면 모든 근거와 실제 답변을 별도로 평가합니다.

- 실행 결과: 최초 선택형 추출은 정상1/8·제외8/8이었습니다. `response_format` schema가 prompt에 보이지 않는
  실행 계약 누락을 확인하고 선택/eligibility 두 단계에만 opt-in `SchemaVisibleCalls`를 추가했습니다.
  cache 전에 실제 prompt를 구성하며 기존 request와 분리합니다. 같은 표본/모델/threshold에서 정상7/8·제외7/8입니다.
  기제는 [공식 llama.cpp 문서](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)와 일치하지만
  모든 과거 오류의 원인이라고 일반화하지 않습니다. 기본 transport와 다른 검사 prompt는 그대로입니다.
- 확인12개에서 생성12units 사후 검토: 실질 주장8, 미해결 지시어2, 최종 evidence 문맥 누락1, 수사 의문문 모호성1.
  전체 댓글의 eligibility와 저장된 evidence의 문맥이 어긋날 수 있습니다. 조건부 의미 보존의 완료 기능이 아닙니다.
- 실제64개59units/3source 가능anchor1개, 밀집32개22units/anchor2개. degree/density 각각2·4결정 후0agent이며
  예산 미소진입니다. 순서 변경 성공은 입증되지 않았습니다. 자유 텍스트 topic quote의 원문 불일치24·3건도 남습니다.
- 두 probe와 두 조립을 모델 호출 없이 replay했습니다. 문자 보존·재현성은 확인했으나 품질/기본 승격은 하지 않습니다.
  후속은 topic quote의 위치 선택 계약, 최종 evidence 기준 eligibility, 알려진 실제 연결의 retrieval recall 측정입니다.
  수치·실패·재현 경로는 [원문 선택 진단](EVIDENCE_SELECTION_DIAGNOSTIC.md)에 저장합니다.

## ADR 024 판정 전용 로컬 OpenJev 비교

- 상태: 기본 Factory 변경 없는 진단. TypeSafe 상용 Jev와 별도 공개 모델인 OpenJev를 구분합니다.
  대상은 `AlexWortega/openjev`, revision `a20448012c213128955ca0c693e7c943865cab77`, `qwen3.5-2b-nli-v5`입니다.
  8GB GPU를 고려해2B를 고정했습니다. README에 있는0.8B v5 경로는 이 revision의 실제 배포 목록에 없어 쓰지 않습니다.
- 기존 Qwen 추출/문장 제안은 변경하지 않습니다. DeBERTa와 OpenJev에 같은 premise/target만 주어 원문 지지 판정을
  비교하고, 별도 고정 meta-hypothesis로 실질 주장 eligibility 가능성을 측정합니다. 두 과제의 수치를 합치지 않습니다.
- 입력53개를 첫 실행 전에 고정합니다. 기존 exact12개, 새 합성 전이12개, 이전 실제 검토의 명확한 fidelity13개,
  기존 eligibility16개입니다. 실제20개 중 뉘앙스2·선택 문맥 부족4·독립성만의 문제1은 fidelity 점수에서 사전 제외합니다.
  모델 결과를 보고 라벨을 고치거나 표본을 선택하지 않습니다. assistant 개발 라벨이지 독립 gold가 아닙니다.
- `local_openjev`는 fixed NLI template, label ID, pad/pooling 계약을 확인합니다. pinned safetensors와 tokenizer만
  local_files_only/trust_remote_code=false로 읽고 원문500자/입력512token을 넘으면 자르지 않고 오류 처리합니다.
- API로 실제 댓글을 보내지 않습니다. 모델 파일만 내려받으며 추론은 offline입니다. 최초 GPU 계획은 라이브러리
  다운로드 비용 때문에 OpenJev 추론 전에 중단했습니다. 원본 계획/DeBERTa 결과를 보존하고 별도 CPU 계획을 고정합니다.
  같은 CPU/6threads/float32를 쓰되 tokenizer와 transformers 버전이 다르므로 시간은 이 환경의 운영 관측치입니다.
  OpenJev 전용 환경에서만 새 transformers를 설치하고 기존 CPU torch를 읽기 전용으로 재사용합니다.
  기존 NLI/embedding 환경은 변경하지 않습니다. OpenJev 점수는 이 데이터에서 보정된 확률이 아닙니다.
- 직접 NLI eligibility와 공식 OpenJev wrapper 형식의 typed routing을 별도 실험으로 구분합니다. 후자는 같은16개에
  substantive/non_substantive/context_dependent의3개 고정 가설을 검사하고 entailment 점수를 상대 정규화합니다.
  이는 DeBERTa 직접 eligibility 실패를 본 뒤, OpenJev 결과를 보기 전에 추가한 실험임을 명시합니다.
  상대 점수가 높아도 절대 entailment가 낮으면 strict 승인하지 않습니다. 동점/오류는 의미 판정 성공이 아니며,
  routing 결과는 댓글 삭제나 서비스 승인을 결정하지 않습니다. 모델별48개 요청의 원시 점수를 보존합니다.
- threshold0.8은 기존 보수적 정책 그대로이고 새 모델에 맞춰 최적화하지 않습니다. 오류는 정답 음성으로 세지 않으며,
  정상 보존·오승인·unclear·latency·GPU memory를 함께 기록합니다. 모든 원시 scores/logits/request hash를 보존합니다.
- 판정기만 비교하므로 새 cluster/agent 생성이나 default 승격은 수행하지 않습니다. 정식 도입은 명백한 왜곡 차단,
  정상 보존, 새 실제 평가와 원문 충실한 agent 실행이 추가로 필요합니다. 독립성 사전 분류는 라우팅 후보이지 강제 삭제 기준이 아닙니다.
- 실제 결과: 합성 왜곡 비승인6/12→12/12이나 정상12/12→11/12. 실제 정상8/8·왜곡3/5는 동일하고
  기존 의미 추가2개가 그대로 오승인됩니다. 직접 eligibility는 정상5/8·제외6/8입니다.
  typed routing은 정상8/8·제외3/8, 상대/절대 strict는 정상2/8·제외8/8입니다. 양쪽 모두 기본 채택하지 않습니다.
  오류0/두 비교 replay 일치/317tests는 실행 재현성이지 의미 품질 보장이 아닙니다.
  CPU 메모리·성능·남은 실패와 새 환경 사용법은 [OpenJev 비교](OPENJEV_COMPARISON.md)에 보존합니다.

## ADR 025 주제 위치 선택과 최종 근거 검사

- 상태: 별도 진단. 기존 Factory0.2와 evidence-units0.1/OpenJev 실험을 보존합니다.
  `evidence_positions`는 주제의 첫/끝 token ID만 허용하고 원문 위치에서 topic quote를 복사합니다.
  같은 표현이 여러 번 나오면 선택된 occurrence를 유지하며 가까운 문자열로 바꾸지 않습니다.
- focus와 topic이 있는 연속 문맥 및 이웃 문장을500자 안에서 저장합니다. 부분 절단/부모 내용 추가는 하지 않습니다.
  위치 전용 결과를 먼저 보존하고, 최종 저장 evidence/focus/topic만 보는 별도 eligibility 결과로 후속 units를 만듭니다.
  전체 댓글을 읽은 첫 판정이 최종 검사 입력에 들어가지 않습니다. 구조적 보존과 의미 완결성은 구분합니다.
- 고정 합성16개·기존 실제 개발12개·이전 확인12개의 선택 범위를 그대로 재사용합니다. topic prompt/schema/표현 변경을
  한 개입으로 측정하고 final 검사 추가 효과는 같은 position units에서 분리합니다. 이전 확인 표본은 이제 회귀 표본입니다.
  과거 독립성/문맥 실패12units도 원래 evidence 그대로 final 검사합니다. 정상/제외 기대값을 결과 후 수정하지 않습니다.
- 기존 실제 정상 cross-source3쌍의 추가 endpoint5개를 포함해 총45입력을 고정합니다. 실제29source의 같은 pool에서
  원문/position units/final units와 기존 cross-mode·hybrid 검색을 비교합니다. source 노출 및 추출 잔존율을 보고하며,
  원문이 검색됐다는 것을 올바른 claim 연결/cluster 가입/전체 corpus recall로 보고하지 않습니다.
- 코드/자료/라벨/모델 revision을 추론 전에 고정합니다. 결과를 본 뒤 threshold/예외 어휘를 바꾸지 않고 오류를 정답 제외로 세지 않습니다.
  고정 정상8/8·제외8/8 및 확인 출력 검토를 통과하기 전 assembly로 확장하지 않습니다. 전체1,000개 재실행·새 수집은 없습니다.
- 결과: GPU133요청/고정 정상7/8·제외7/8, 확인 최종8units 중 정상5·지시 대상2·저장 문맥 누락1입니다.
  최종 감사는 기존 명백한 실패3개를 막지 못하며 정상도 잃었습니다. topic 위치9개가120자 상한에서 실패했습니다.
  원문29source의 기존 정상3쌍은 raw검색3/3노출이나 추출 후 source 잔존0/3입니다.2개anchor를 공유하는 작은 대조군입니다.
  기본 채택·assembly로 확장하지 않습니다. 후속은 필수topic/상위4선택 전에 원문 검색 후보를 보존하는 경로 비교입니다.
  수치·runtime fallback·전수 사후 검토·재현은 [위치 선택 진단](EVIDENCE_POSITIONS_DIAGNOSTIC.md)에 보존합니다.

## ADR-026: 원문 검색 우선과 지지도/시간 경계 (2026-10-12)

- 이전 selector/topic/final 실패로 검색 전에 원문이 사라진다. 생성형 복원·검사를 전 댓글에 반복하는 대신
  canonical 원문을 먼저 embedding하고 후보와 후속 비교 예산을 분리한다. Factory0.2 기본값은 변경하지 않는다.
- 구현: `raw_candidates-0.1`, 최대1,000 source, semantic8+lexical4, round-robin 무방향64쌍.
  모델/threshold 교체가 아니라 단계 순서와 실패 격리의 변경이다. dense O(N²) 비용은 남는다.
- 지지도는 검색 수가 아니라 고정 공통 주장에 대한 canonical 댓글별 통과 수다.
  주요/제한적/희소 구분과60초/300초 목표는 잠정 제안이며 아직 의미 집계/latency 검증을 통과하지 않았다.
- [정확한 계약·재현·범위](RAW_RETRIEVAL_MVP.md). 원문·cache·대기 목록을 보존하고
  후속 모듈에 두 원문을 정확히 전달한다. agent 승인/지지 집계는 다음 구현이다.

## ADR-027: Raw pair 공통 주장과 독립 지지 ledger (2026-10-12)

- [구현·사전 평가 계약](RAW_SUPPORT_MVP.md). 원문 쌍당 제안 하나를 고정한 뒤 각각의 전체 원문→주장을 검사한다.
  추출 문장 자체의 승인이나 peer 정보를 membership 근거로 쓰지 않는다. 원문은 검색 registry에 계속 남는다.
- 같은 NLI 가중치의 별도 raw adapter는500자 대신 실제512token 한도를 검사한다. truncation 없이 초과를 미검사로 보존한다.
  전체 원문 NLI와 관계 감사 후 supporting quote에 보조 lexical guard를 적용한다. schema도 system에 노출한다.
- 지지 ledger는 canonical source 중복 제거, core/source digest 결합,5상태 분모를 검증한다.
  exact-string core만 병합하고 유사도 연결의 전이적 합집합은 금지한다. 주요/희소 등급은 잠정 표시일 뿐 승인 아니다.
- 기존37직접 판정+12쌍 회귀와 실제64쌍을 고정한다. 회귀 오승인/오류/미검사가 없을 때만 첫2core를64source에 확장한다.
  이 모듈에서 agent를 생성하지 않는다. 진단 결과와 사후 의미 검토를 분리하고 기존 경로는 유지한다.
- 실행 결과: 직접 회귀 정상15/20·부정13/17,오승인1/오류4. 실제64쌍의 양쪽 통과0이며 확장/agent0.
  개별 support12건에도 범위 추가/독립 주장 자격 문제가 남았다. source 검색 이후의 제안/감사/인용 계약 실패다.
  모델 응답 모순에 대한 중복 수리와 자유 인용 복사를 다음 설계 대상으로 기록하되 현재 gate를 완화하지 않는다.

## ADR-028: 검색 이후 근거 위치 선택과 host 판정 (2026-10-12)

- 기존 raw-support0.1 및 실패 결과는 보존한다. 이미 검색된 pair 내부에서만 원문 구간을 대응시키고 공통 주장을 제안한다.
- 모델의 중복 supported verdict를 없애고 assertion/eligibility/속성값을 host가 보수적으로 조합한다.
  의미 불일치를 형식 오류로 재요청하지 않는다. 전체 source와 정확히 저장된 evidence의 NLI를 모두 요구한다.
- 근거는 원문 S-ID→offset→code copy로 저장한다. topic120/quote400자 상한 대신 실제 source/token 예산을 검사한다.
  구간 선택 실패가 원문 registry를 지우지 않는다. 기존0.1 ledger와 agent에는 자동 연결하지 않는다.
- [사전 계약·48직접 판정/12합성쌍/3실제쌍 평가](POSITIONAL_SUPPORT.md). 독립성/의미는 여전히 모델 판단이며
  개발 사례 통과만으로 agent 품질 승인이나 일반 정확도 개선을 주장하지 않는다.
- 실행 결론: 계약 오류는 직접37개에서4→0이지만 정상15/20→10/20, 오승인1→2로 악화했다.
  실제3쌍 양쪽 통과0, 확장/agent0. 위치 결합은 보존하되 이 진단 경로를 기본 채택하지 않는다.
  다음은 고정 입력으로 구간 선택과 관계 감사를 분리 비교한다. 검사 추가/임계값 완화로 성공을 만들지 않는다.

## ADR-029: 생성과 판정의 고정 입력 분리 진단 (2026-10-12)

- [컴포넌트 비교 계약](COMPONENT_ISOLATION.md). 원문/자동 구간/사전 선택 구간으로 제안 입력만 바꾸고,
  생성 주장과 사전 기준 주장을 구분해 같은 검사기에 전달한다. 모델·프롬프트·기본 pipeline은 유지한다.
- 사전 기준은 offline assistant 개입이며 서비스의 사람 입력이나 자동 성과로 쓰지 않는다.
  생성기는 기준 주장/라벨을 받지 않고 생성 결과는 항상 두 전체 원문으로 검사한다.
- 기존48개 판정의 NLI-only 대조도 함께 보존한다. 검사 제거와 정상 통과 증가를 품질 개선으로 동일시하지 않는다.
  고정 정상 pair3개도 임의 core를 보장하지 않는다. 모호한 기준 해석과 자동 실패를 분리한다.
- 실행 결과: 실제1쌍은 전체/사전 구간에서 충실한 제안·원문 검사에 성공했으나 자동 선택 구간에서는 실패했다.
  합성 기준 주장을 직접 줘도2/6쌍만 통과했고 생성된 조건 범위 확장도 오승인했다. 선택과 감사 모두 별도 병목이다.
  다음은 추출형 원문 문장 후보 baseline과 고정 source-target 감사 비교다. 기본 채택/agent0을 유지한다.

## ADR-030: 추출형 원문 문장 후보 baseline (2026-10-12)

- [설계·평가 경계](EXTRACTIVE_CANDIDATES.md). 생성 제안 대신 원문 단일 문장을 exact target으로 사용한다.
  위치 결합한 후보를 기존 MiniLM으로 순위화하고 source별2개를 검사한다. reference/라벨은 검색 입력이 아니다.
- 문자 보존은 코드 계약이고 의미 자격·다른 댓글의 지지는 별도 문제다. origin도 독립 검사하며 유사도 투표는 금지한다.
  긴 target을 자르지 않고 미검사로 남긴다. 문맥이 필요한 문장과 짧은 기준249자 제한은 한계로 보존한다.
- 합성 정상/부정12쌍+실제3쌍으로 선택과 판정을 따로 측정한다. 후보당 검사 비용 증가를 공개하고 기존 판정기를 완화하지 않는다.
  기본 Factory/agent 경로 미연결이며 모델 양쪽 통과만으로 품질 승인하지 않는다.
- 결과: 실제 핵심 구간3/3쌍 양쪽1순위 노출, 실제 지지0/3. 합성 정상2/6·부정 오통과0/6.
  literal 후보로 재작성 오류는 피했지만 구간 단위와 판정기 한계가 남았다. 동일 감사 요청의 실행 간 변화도 관측했다.
  후보 baseline을 고정하고 새 추론 반복성→독립 판정기 비교 순서로 진행한다. 현재 기본 승격/agent0 유지다.

## ADR-031: 판정기 fresh 반복성 분리 (2026-10-12)

- [고정 설계](AUDIT_REPEATABILITY.md): 후보/프롬프트/모델을 고정하고 cache on/off × blocked/interleaved 144회 비교한다.
- 매 arm 새 소유 서버, 실제 HTTP 호출별 보존, 중단 후 문맥 이력 재개 금지. response cache 재생과 fresh 추론을 분리한다.
- provisional 속성 판정만 측정하며 NLI 포함 지지 승인과 구분한다. 안정적 오판도 공개하고 기본 승격/agent 생성은 하지 않는다.
- 결과: 144회에서 요청별 출력 변화0, 정상6/10 잠정 지지·부정2/2 오승인이 모든 설정에 동일했다.
  캐시 원인/해결 근거는 없으며 과거 변동은 미재현이다. 캐시 기본값을 바꾸지 않고 다음은 감사 모듈만 교체 비교한다.

## ADR-032: 고정 요청의 로컬 판정기 모델 비교 (2026-10-12)

- [비교 계약](AUDIT_MODEL_COMPARISON.md): 기존4B 대8B 비추론, 동일 system/data/schema/host projection.
  원문 후보 선택기와 생산 경로를 유지하고 학습 버전/native template 차이는 제한으로 공개한다.
- 기존40라벨/39고유 요청×2모델=78회, 정상/의미 왜곡/자격을 분리 평가한다. 수동 라벨은 추론 입력이 아니다.
- 오류0·각 군 오승인0·군별 정상 비열화·반복군 정상9/10 이상이어야 다음 통합시험 후보가 된다.
  개발군 통과와 서비스 품질 승격은 분리하며 결과를 보고 같은 실험을 재튜닝하지 않는다.
- 10월13일 결과: 반복군 정상7/10→10/10, 의미 추가 오승인2/2→1/2지만 자격 제외8/8 오승인은 두 모델 모두 같다.
  8B 기본 교체/통합시험 진입 기준 실패다. 올바른 거절에서도 scope 등의 속성 오류가 있어 설명으로 신뢰하지 않는다.
  다음은 SOURCE-only 자격 대조이며 성공 시 source별 재사용을 검토한다. 아직 구현/성공한 모듈이 아니다.

## ADR-033: 자격 단일 작업과 TARGET 입력 분리 대조 (2026-10-13)

- [계약](SOURCE_ELIGIBILITY.md): 기존 joint/자격 전용 with-target/source-only의3조건, 동일4B·32원문·96회다.
  전용 두 조건은 TARGET 필드만 다르며 joint와 전용은 prompt/schema/정책 명료화가 함께 바뀌는 패키지 비교다.
- source-only 요청은 기대 라벨/target을 받지 않고 단일 자격 enum을 반환한다. 불확실/문맥 의존/오류는 승인하지 않는다.
  자격 통과가 모든 문장이나 target의 충실성을 보장하지 않으며 원문 삭제/agent 생성/기본 경로 연결은 없다.
- 기존 정상8/8·새 대비7/8 이상·양쪽 제외 오승인0·오류0일 때만 실제 표본 시험 후보가 된다.
  source별 재사용 키는 정의하지만 실제 cache/생산 필터는 검증 후 별도 결정한다.
- 결과: 정상16/16→전용15/16→source-only15/16, 제외 오승인16/16→12/16→9/16으로 일부 개선됐으나 기준 미달이다.
  source-only 남은 오승인은 지시 대상 미해결8·독립 인용1이고 질문+경험 정상1개도 소실했다. 기본 경로 연결0.
  다음은 발화 구간/지시 대상/저자 동의 근거의 원문 위치 결합 계약을 검토하며 아직 구현·검증한 해법이 아니다.

## ADR-034 원문 위치 근거 자격 검사 2026-10-13

- [계약과 사전 기준](ELIGIBILITY_WITNESS.md). 단일 enum 대신 한 주장 구간·발화 유형·작성자 입장·지시 대상 근거를 제출한다.
  host는 범위와 관계 구조만 검증한다. 의미적으로 틀린 연결/미신고 참조를 모두 검출한다고 주장하지 않는다.
- 기존32+새16개, 정상24/제외24의 두 조건96회다. 기존 단일 enum도 같은 환경에서 새로 실행한다.
  모든 군 정상8/8·오승인0·오류0·필수 원문 구간 보존일 때만 다음 실제 표본 시험 후보가 된다.
- 원문 재작성/전체 의미 복원/추가 수집 없이 단어 위치로 복원한다. 입력 초과는 자르지 않고 보류한다.
  기본 Factory/후보/충실성/ledger/agent는 불변이고 실제 cache도 연결하지 않는다.
- 결과: 정상 source 통과23/24→5/24, 제외 오승인15/24→1/24이며 정상5개도 근거가 불완전했다.
  위치상 유효한 한국어 참조 연결1개는 의미 오승인으로 남았다. 필수 구간 보존0/7, 새 방식 채택·실제 시험 진입을 거부한다.
  다음은 기존 문장 후보 baseline을 재사용하는 제한된 선택/문맥 비교 설계다. 단어 위치·참조 그래프 생성은 연결하지 않는다.

## ADR-035 실제 데이터 비교 준비로 실험 선택 전환 2026-10-13

- [현재 구조](CURRENT_ARCHITECTURE.md)와 [평가 프로토콜](FACTORY_EVALUATION_PROTOCOL.md)을 분리한다.
  witness의 다음 prompt 변형보다 고정 실제 표본·정책 보정·V0/V1/V2 공통 평가 경계를 우선한다.
- 원문·출처 보존과 수동 처리 없는 서비스는 유지한다. 세부 enum/참조 그래프/검사 조합은 교체 가능한 가설이다.
- 기존 개발64개와 스레드·동일문장 component가 겹치지 않는 예약64개,12개 정책 보정 사례, cached V0 후보를 준비했다.
  과거 전체 corpus가 실행됐으므로 미사용 holdout이나 독립 gold가 아니다. split 그룹화는 지지 수 중복 제거 정책을 바꾸지 않는다.
- V0 후보58개/3개 이상1개는 의미 품질 성과가 아니다. V1/V2의 adapter·공통 출력·수치 기준·예산은 아직 미동결이다.
  이번은 model 호출0의 평가 준비이며 비교 완료/새 agent/기본 교체가 아니다.

## ADR-036 동일 실제64개에서 원문/주장/감사 패키지 비교 2026-10-13

- [동결 조건](MATCHED_FACTORY_COMPARISON.md): ADR-035의 미구현 adapter를 별도 opt-in runner로 연결한다.
  V0 cached raw vectors, V1 fresh 주장 벡터에 같은 clustering/draft contract를 적용하고 V2는 정확한 V1 카드를 감사한다.
- canonical source 분모64·중복 없는 후보 수·common/detail 출처 계약을 공유한다. scope는 V0 전체 원문/V1 선택 span이다.
  이 차이를 추출 단일 요소의 인과 효과로 부르지 않는다. 감사는 같은4B 모델의 판단이며 독립 gold가 아니다.
- 최대320생성 요청/완료된 생성 시간1,800초, repair0, 임계값0.45를 동결했다. 결과를 보고 완화하지 않는다.
  >=3 출처의 유효 카드와 정상 보존·왜곡·실제 비용을 함께 평가한다.0-agent를 품질 성공으로 간주하지 않는다.
- 서비스 기본 Factory·agent 승격 경로는 불변이다.
- 결과:64개에서113claim, V0/V1/V2 카드6/15/10개. 충실한3-source 이상 카드는 모두0개로 세 구성의 기본 채택을 거부한다.
  V1 유일3-source 카드에는 반대 입장이 오가입했고 V2가 제거했다. 반면 물가 공통 후보는 검색에 잡혔으나 생성에서 흩어졌다.
  감사 후 남은10개 중5개는 assistant 검토상 문제 인용이 있다.135fresh 호출·형식 오류0, 의미 품질 미완료.
- 다음은 frozen 공통 주장·원문별 관계·상세 이유 출력을 분리하는 경계이며 아직 구현/채택하지 않았다.
  예약 표본·1,000개 확대·새 agent0. offline assistant 평가는 독립 gold나 서비스 입력이 아니다.

## ADR-037: 고정 주장과 독립 가입을 분리하고 실험 중단 경계 적용 (2026-10-13)

- [사전 계약·실측](FIXED_CORE_COMPARISON.md). 원문/claim 추출/검색은 재사용하고 joint draft/assignment만 제거한다.
  기존 claim에서 후보당 중심1개+diverse2개를 결정적으로 선택하며 내용/threshold를 사후 변경하지 않는다.
- 원문별 독립 감사는 고정 주장 하나와 해당 full own-comment만 본다. anchor도 검사, 다중 가입 허용, source당1표다.
  모델 지지와 검증된 지지 수를 분리하고 상세는 원문 인용만 보존한다. public 기본/agent 경로와 미연결이다.
- 고정 target 개념은 이전 raw_support/grounded_core에도 있었다. 최신 matched 경계의 단순화 비교이며 새로운 의미 보장이나 단일 인과 효과가 아니다.
- 결과:24target/72관계,195.09초·오류0. 모델상 물가3댓글이 모였지만 부연의 출처 이동이 남아 충실한3-source 카드0이다.
  반대 노동 입장 오가입은 거절했다. assistant 전체 대조에서 모델 지지23중8개가 partial이며 독립 gold가 아니다.
- 사전 한 번의 개선 비교가 실패했으므로 같은4B prompt/auditor 변형은 중단한다. 예약64개·전체 확대·새 agent0.
  다음은 의미 모듈의 모델/학습 방식 또는 명시적 MVP 범위 결정이다. 원문 충실성/수동 runtime 없음/초기 제품 목표를 완화하지 않는다.

## ADR 038 주요 사실 근거 판정과 에이전트 입력 조립 분리 2026-10-13

- 사용자 합의와 [현재 정책·구현 범위](FACT_GROUNDED_AGENTS.md)에 따라 원문 충실성 검사와 외부 사실 근거 검사를 분리한다.
  원문을 충실하게 재현했다는 이유만으로 사실 근거를 승인하던 가정은 새 경로에서 대체한다. ADR-037의 반복 중단은 유지한다.
- 모든 댓글이 아니라 후보가 사용하는 주요 사실을 검사한다. 사실·가치·예측, 필수 전제, 핵심 지지 수·개별 이유 지지 수를 구분한다.
  전제 탈락으로 입장을 왜곡하거나 외부의 새로운 논거로 보강하지 않는다. 필수 전제 또는 모든 주요 사실 근거 탈락 시 보류한다.
- `factory/fact_checks.py`는 동결 문서·인용 구간에 대한 로컬 단일 판정과 재생 검사를 맡는다.
  주장·문서·선택 구간·모델/실행기·프롬프트/schema를 기록에 결합한다. 검색·캐시 스케줄러·출처 인증은 구현하지 않았다.
- `agents/grounded_inputs.py`는 원문 지지와 supported 사실만 허용하는 결정적 입력 조립을 맡는다.
  원문 인용 보관과 모델 입력을 분리하고 변경·만료 시 재사용을 거부한다. 의미적으로 틀린 upstream 분류/판정을 증명하는 장치는 아니다.
- 새 상태는 `fact_screened_input_not_runtime_approved`, `quality_gate_passed=false`, `agents=[]`다.
  기존 runtime·UI에는 연결하지 않는다. 순수 가치 관점은 사실 인증 없이 입력 후보로만 보존하며 최종 수용 정책은 후속 단계다.
- 합성 시나리오 5개를 네트워크/모델 호출 없이 실행하고 새 계약 회귀 34개를 통과했다.
  실제 댓글·팩트 판정 정확도·자동 생성 성공 증명이 아니다. 다음은 통제된 실제 근거 판정→자동 검색→Factory adapter→답변/UI 순서다.

## ADR 039 시연 시간 예산과 가치 관점 발화 정책 2026-10-13

- 사용자와 영상 1개 시연·추후 다른 영상 설정 가능, 첫 분석 최대1시간, 새 개발 사이클 로컬 추론 누적8시간을 합의했다.
  시간의 측정 범위와 미합의 품질 수치는 [현행 정책](FACT_GROUNDED_AGENTS.md)에 분리한다. 모델 다운로드·유료 API 등의 권한을 확대하지 않는다.
- 가치 판단도 원문 지지·충실성을 충족하면 agent 후보가 된다. ADR-038에서 유보했던 가치 관점 수용 방향을 결정하되,
  새 runtime/UI가 구현됐다는 뜻은 아니다. “카드만 허용” 제안은 미채택이다.
- Agent는 묶음의 핵심 입장·출처별 이유·자료 지원 사실·응답 한계를 구분한다.
  원문에 없는 설득 논거·개인 경험·효과를 추가하지 않고, 사실 전제를 지워 가치 관점으로 우회하는 것도 금지한다.
- 이번 변경은 정책 기록이다. 코드·model 호출·평가 라벨·기본 경로는 변경하지 않는다.
  95%/80%/90% 등의 사전 제안 수치와 구조별 반복 횟수는 별도 확정이 필요하다.

## ADR 040 사실 판정 예산과 선택형 답변 경로 2026-10-13

- 사용자 승인 최소 기준은 handoff16.13과 [MVP 상태표](MVP_ACCEPTANCE_STATUS.md)를 따른다. ADR-039의 수치 미확정 상태를 대체한다.
- `providers/budget.py`는 새 runner들의 공유 SQLite 예산을 관리한다. 호출 전 예약, 별도 프로세스 deadline,
  실패·중단 비용 보존으로8시간을 제한한다. 기존 실험 전체를 자동으로 제어하지 않으므로 새 추론은 반드시 이 경로를 사용한다.
- `factory/evidence_fetch.py`는 허용된 공개 자료의 원문과 조회 URL·hash를 보존한다. Kela의 공개 본문 endpoint adapter이며
  검색 엔진·주장별 자동 검색·publisher 정확성 인증을 대신하지 않는다.
- 사실 모델 비교와 답변 runtime을 분리한다. 실제 문서40건 진단에서8B 단독은 비지원 오승인1건으로 미달했다.
  로컬 NLI의 개별 passage 판정과 일치 조합을 비교하되, threshold/표본을 사후 조절하거나 정상 보존 기준을 완화하지 않는다.
- `agents/grounded_runtime.py`는 claim ID 선택만 허용하고 host가 원래 entry·출처·필수 전제를 렌더링한다.
  자유 생성 후 모델 감사만으로 공개하는 경로와 독립된 opt-in 구현이다. 새로운 논거·인용 생성은 막지만 관련성 선택 오류는 남는다.
- 기존 Factory·AgentSession·UI를 기본 승격하지 않는다. 입력 계약 테스트와 실제 자동 에이전트의 원문·사실 품질을 별도로 검증한다.
- 동일40건에서 NLI 단독이 지원9/10·비지원 오승인0·충돌10/10을 기록하여 다음 통합 후보로 선택한다.
  LLM과의 일치 조합은 승인 정밀도 이득 없이 충돌5건을 보류하므로 현재 기본 후보로 삼지 않는다.
- 답변0.1의 실제 실행 실패 후0.2는 역할을 명시하고 JSON 분기에서 상태 조합을 강제한다.
  동일 합성 질문에서 답변/보류 각각20/20, 비교 P95 10.27초지만 실제 관점 생성·UI 통과는 아니다.

## ADR 041 원문 후보 생성과 가입 및 근거 기록 분리 2026-10-13

- 자율 MVP 진행 요청에 따라 실제 연결 경로를 구현한다. 사용자가 정한 최소 품질 기준은 변경하지 않는다.
- raw 유사도 묶음을 크기·ID로 결정적으로 선택한 뒤, 캐시된8B가 최소 핵심과 개별 이유·필수 사실 전제를 제안한다.
  별도 full own-comment 판정으로 고정된 핵심에 가입한다. 후보 생성 출력의 member 수를 지지 수로 사용하지 않는다.
  이는 기존 fixed-core와 같은 분리 원칙을 재사용하는 통합 후보이지 검증된 새 해법이라는 선언이 아니다.
- 고정100 source 관계를 실행 전에 오프라인 평가한다. LLM 단독을 우선 검사하고 필요하면 기존 고정 NLI와 교집합을 비교한다.
  NLI 단독은 작성자 발화 자격을 보증하지 않으므로 진단용이다. 사후 threshold/분모/target 변경을 하지 않는다.
- NLI 사실 record는 생성형 판정과 별도 버전·로그잇·label mapping·packet 결합을 가진다. 원문 관계 NLI 성능과 분리한다.
- grounded 전용 UI는 기존 승인 경로를 변경하지 않는다. `--experimental`로 입력 검사된 관점을 비교하고 미승인 상태를 표시한다.
  이는 개발 모드 선택이며 사람의 의미 승인·runtime repair 단계가 아니다. 모델은 주장 ID만 고르고 host가 문장·인용을 표시한다.
- 기존 API corpus와 공개 문서 capture를 재사용하고 외부 검색·새 다운로드·유료 모델을 추가하지 않는다.
  실제 corpus 평가와 첫 실행 속도를 통과하기 전에는 자동 MVP로 승격하지 않는다.

## ADR 042 가입 실패와 제한된 추론 배포 비교 2026-10-13

- ADR041의 joint proposal은 core-only 생성 → 별도 가입 → 유형/이유/필수 전제 추출로 분리한다.
  생성 단계에서 잘못된 anchor quote나 전제 연결을 함께 만드는 문제를 줄이기 위한 구조 변경이며 품질 통과는 아니다.
- 고정100 관계의 기존8B/DeBERTa 조합은 조기 실패 상한이 입증됐고, OpenJev도 정밀도62.5%·보존71.4%로 미달했다.
  같은 판정기 표를 임의로 합치거나 threshold를 조절하지 않는다. 사실 문서용 NLI의 통과를 원문 가입 성능으로 전용하지 않는다.
- 기존8B를 full GPU/context4096에 배치한 뒤 추론 off와256token 제한 on을 비교한다. 같은 원문·주장·참조·프롬프트·schema를 유지한다.
  on은 최종 답변까지512tokens, off는180tokens이고 모두90초 deadline/재시도0이다. 추론 내용은 private 로그이며 사용자 답변이 아니다.
  모델 크기·기존 CPU offload·context 변경 효과와 추론 효과를 혼동하지 않도록 matched off 배포를 함께 동결한다.
- `experiments/membership_checkpoint.py`는 분모100을 고정한 관측치와 최선의 정밀도/보존율 상한을 계산한다.
  미실행 사례는 정상 거절이 아니며 부분 실행으로 합격할 수 없다. 합격 불가능해지면 남은 동일 호출을 아낄 수 있다.
- compiler0.2는 NLI record를 별도 validator로 검사한다. runtime0.3은 호출 후 재검증한 입력으로만 문장과 출처를 렌더링한다.
  가변 세션 캐시나 모델이 작성한 설명이 공개 문장·지지 수를 바꾸지 못하게 한다. upstream의 의미 정확성 검증을 대체하지 않는다.
- fresh runner는 기존 stage 계약을 한 실행으로 연결하되 개발 source gate 통과 전에는 실행을 준비하지 않는다.
  snapshot 경로를 인자로 받고 오프라인 새 임베딩부터 시작한다. 전체3600초와 공유 추론 예산을 함께 적용한다.
  실패/시간 초과/빈 입력을 MVP로 승인하지 않는다. 입력 조립 이후 실제 관점 감사와 질의/UI 평가는 별도로 남는다.
- 전원 종료 복구는 완료 응답을 재사용하고 응답 유실은 오류·예약 비용으로 보존한다. 새 continuation plan으로 미실행 요청만 처리한다.
  운영 복구 코드가 바뀌어도 과거 plan의 code hash를 덮어쓰지 않는다. 동일 의미 요청과 새 실행기 버전을 구분해 기록한다.
- 제한 추론만으로는 정상 참조5건을 잃어 보존율 상한76.2%로 실패했다. 마지막8B 지침 개선은 source→target 함의 방향만 명료화한다.
  구체적인 활동에서 더 약한 활동 주장으로 세부사항을 생략하는 것과, 주체/조건/양화/인과를 부당하게 확대하는 것을 구분한다.
  별도 합성 통제8건에서 지지4/4·비지원 오승인0/4를 확인한 뒤 같은100건 비교를 수행한다. 독립 gold나 실제 agent 승인으로 읽지 않는다.
  사전 상한으로 불합격이 확정되면 호출 사이에 자동 중단한다. 같은4B auditor 반복과 사후 라벨/임계값 변경은 계속 금지한다.

## ADR 043 판정 정책 연결 보완 2026-10-13

평가된 가입 system과 실제 통합 기본 system이 달랐고, 추론 배포의512token 요청을 유형 분류 후180token 기본 요청과
비교하는 연결 오류가 있었다. `membership_policy`에서 평가된 system/schema/max_tokens를 동결해 핵심·상세 검사에 전달한다.
유형/필수 전제 metadata만 바꿀 수 있고 text/scope는 그대로 유지해야 한다. fresh/staged runner의 계약은0.2로 올렸다.
합성 회귀로 정책 보존과 위변조 거부를 확인했지만 실제 agent 의미 품질을 통과한 것은 아니다.

8B core-only 생성은 동일20묶음에서 계약 통과17개를 만들었다. 새100 사전 참조와 같은 directed 판정기를 사용했고,
사용자 중단 이전13건 중 J005가 오승인됐다. J014 중단 오류를 포함한 고정 gate는 정밀도 상한94.7%로 채택할 수 없다.
마지막 동일 지침 non-thinking 배포는 새 합성8통제에서 정상4/4·비지원 오승인1/4로 실패했다.
돌봄 조건을 삭제한 target을 승인했으므로 실제100관계 실행을 시작하지 않았다. 같은 모델군의 프롬프트 탐색은 종료한다.
중단·실패 기록과 분모를 유지하며 더 큰 로컬 모델1종 비교는 다운로드 허가 후에만 진행한다.

## 변경 시 필수 체크리스트

1. 이 문서에 결정/대안/영향 범위를 추가한다. 과거 ADR 변경이면 superseded 대상도 명시한다.
2. 입출력 변경은 `DATA_CONTRACTS.md`와 runtime validator, schema version에 함께 반영한다.
3. 합성 단위 테스트와 고정 development case를 실행한다. 실패 및 회귀도 보존한다.
4. 실행 manifest와 새 artifact를 남긴다. 이전 실행은 덮어쓰지 않는다.
5. `NEXT_SESSION.md`에 실제 실행 결과와 미구현 상태를 갱신한다. 문서상의 계획을 완료 기능으로 표시하지 않는다.
6. 코드/문서는 Git에 기록하되 corpus/모델 출력/비밀키가 포함되지 않았는지 확인한다.
