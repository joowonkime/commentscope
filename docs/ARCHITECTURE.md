# 구조 결정 — 1단계

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

## 변경 시 필수 체크리스트

1. 이 문서에 결정/대안/영향 범위를 추가한다. 과거 ADR 변경이면 superseded 대상도 명시한다.
2. 입출력 변경은 `DATA_CONTRACTS.md`와 runtime validator, schema version에 함께 반영한다.
3. 합성 단위 테스트와 고정 development case를 실행한다. 실패 및 회귀도 보존한다.
4. 실행 manifest와 새 artifact를 남긴다. 이전 실행은 덮어쓰지 않는다.
5. `NEXT_SESSION.md`에 실제 실행 결과와 미구현 상태를 갱신한다. 문서상의 계획을 완료 기능으로 표시하지 않는다.
6. 코드/문서는 Git에 기록하되 corpus/모델 출력/비밀키가 포함되지 않았는지 확인한다.
