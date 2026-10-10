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
| claim clustering | `factory/candidates` 설계만 존재 | ClaimUnit+embedding → 후보 | 후보 이후 |
| 의미 검수 | AI 보조 탐색 기록만 존재 | 후보+원문 → 검수 판단 | review 이후 |
| 대표 명세 | `factory/perspectives` 설계만 존재 | 승인 후보+검수 → PerspectiveSpec | 명세/agent 이후 |
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

## 변경 시 필수 체크리스트

1. 이 문서에 결정/대안/영향 범위를 추가한다. 과거 ADR 변경이면 superseded 대상도 명시한다.
2. 입출력 변경은 `DATA_CONTRACTS.md`와 runtime validator, schema version에 함께 반영한다.
3. 합성 단위 테스트와 고정 development case를 실행한다. 실패 및 회귀도 보존한다.
4. 실행 manifest와 새 artifact를 남긴다. 이전 실행은 덮어쓰지 않는다.
5. `NEXT_SESSION.md`에 실제 실행 결과와 미구현 상태를 갱신한다. 문서상의 계획을 완료 기능으로 표시하지 않는다.
6. 코드/문서는 Git에 기록하되 corpus/모델 출력/비밀키가 포함되지 않았는지 확인한다.
