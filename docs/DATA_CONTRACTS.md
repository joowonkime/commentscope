# 데이터 계약 v0.1

이 문서는 wire format과 검증 규칙의 구현 명세입니다. 2단계에서 DatasetSnapshot/Comment 검증과 normalization을 구현했습니다.
Eligibility 이후의 계약과 전체 RunManifest는 후속 구현 명세이며, JSON Schema 파일은 아직 제공하지 않습니다.
합성 예시는 [snapshot](examples/synthetic-snapshot.json)과 [Factory trace](examples/synthetic-factory-trace.json)에 있습니다.

## 공통 규칙

- JSON은 UTF-8이며 `NaN`/`Infinity`를 허용하지 않습니다. 정수 필드에 bool을 허용하지 않습니다.
- 아래 필드는 별도 표기가 없으면 필수입니다. `T | null`은 필수 키이지만 값이 없음을 명시할 수 있습니다.
- 알 수 없는 필드·enum·schema major version은 거절합니다. 필드 추가는 계약 버전을 올려 명시적으로 처리합니다.
- ID는 비어 있지 않은 opaque 문자열입니다. timestamp는 시간대가 있는 ISO 8601 문자열이며 출력은 UTC `Z`로 통일합니다.
- source의 식별 범위는 `(snapshot_id, comment_id)`입니다. 파생 ID의 범위는 `(run_id, entity_id)`입니다.
- 저장 envelope는 `schema_version`, `run_id`, `snapshot_id`를 포함합니다. snapshot 자체는 run에 종속되지 않습니다.
- 순서가 의미 없는 ID 배열도 중복을 허용하지 않습니다. 참조는 같은 snapshot/run 내부에서 해석합니다.
- `null`은 모름/해당 없음이며, `[]`는 확인한 결과 항목 없음입니다. 오류를 빈 배열로 위장하지 않습니다.
- confidence는 유한한 `[0,1]` 값이며 없으면 `null`입니다. confidence가 높다고 source 검사나 의미 검토를 생략하지 않습니다.

초기 loader는 정확히 schema `0.1`만 허용하며 JSON의 중복 object key와 UTF-8에 없는 surrogate도 거절합니다.
timestamp는 `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` 또는 같은 날짜/시간에 `±HH:MM` 형식을 받습니다.
offset의 시/분 범위와 실제 달력 날짜를 검사합니다. 입력 파일을 수정하지 않고 직렬화된 timestamp만 UTC로 통일합니다.
언어 태그는 기본 문자열 형식만 검사하며 등록된 언어인지 또는 실제 댓글 언어와 일치하는지 추론하지 않습니다.

## DatasetSnapshot

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `schema_version` | string | 초기 `0.1` |
| `snapshot_id` | string | immutable revision을 식별; 내용 변경 시 새 ID |
| `source_kind` | `synthetic | research` | synthetic을 실제 YouTube 댓글로 표시하지 않음 |
| `video` | object | `video_id: string`, `title: string`, `url: string|null`, `primary_language: string` |
| `captured_at` | timestamp | 실제 수집 또는 합성 표본 작성 시점 |
| `sampling` | object | `method: string`, `description: string`, `target_count: int|null` |
| `usage` | object | `basis: string`, `expires_at: timestamp|null`; 사용 근거 기록이며 자동 적법성 판정은 아님 |
| `comments` | Comment[] | 고유 comment ID, 한 영상에 속하는 원문만 포함 |

research video URL은 HTTPS 원본 링크를 요구합니다. synthetic URL은 `null`로 두어 가짜 원본 링크를 만들지 않습니다.
primary_language는 표본 설명용이며 다른 언어의 댓글을 거절하는 필터가 아닙니다.
실제 sample size는 `len(comments)`에서 계산합니다. target_count나 thread 수와 혼용하지 않습니다.
source 수, top-level 수, reply 수는 별도 집계합니다.

## Comment — 불변 원문

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `comment_id` | string | snapshot 내 고유 |
| `text_original` | string | 빈 문자열도 provenance를 위해 보존; 원문을 번역/정규화로 교체하지 않음 |
| `parent_id` | string|null | top-level이면 null; 누락된 parent도 외부 ID 보존 |
| `parent_status` | `root | present | missing` | root ↔ parent_id=null; present이면 참조 존재; missing이면 참조 부재 |
| `replies_status` | `complete | partial | unknown` | 현재 snapshot의 reply 확보 정도; `complete`는 명시적 수집 근거가 있을 때만 사용 |
| `published_at` | timestamp|null | 없는 시간을 추정하지 않음 |
| `language` | object | `tag: string`, `confidence: number|null`, `method: provided|detected|unknown` |
| `source_url` | string|null | 사용 가능한 원문 링크; synthetic은 null |
| `sampling_origins` | object[] | 원본 표집 기록 `{method: string, rank: int|null}`; rank는 있으면 1 이상 |
| `likes` | int|null | 0 이상; perspective 포함 여부의 기준이 아님 |

language tag는 `ko`, `en` 등 언어 태그를 사용하며 불명은 `und`입니다. 전체 원문이 여러 언어를 섞으면 `mul`을 허용합니다.
self-parent와 snapshot 내부 parent cycle은 오류입니다. missing parent는 빈 댓글로 생성하지 않습니다.
사용자명·계정 프로필은 초기 계약에 넣지 않습니다.

## NormalizedComment / EligibilityRecord

NormalizedComment 필수 필드:

- `comment_id`, `text_analysis`, `normalization_version`
- `duplicate_of: string|null`: 대표 원문의 ID. 대표는 null이며 같은 snapshot의 직접 참조만 허용합니다.

초기 normalization은 분석용 Unicode NFC와 공백 정리를 적용합니다. URL 제거·소문자화·번역은 하지 않습니다.
URL 정규화 규칙은 URL이 표현하는 차이를 지우지 않는 방식으로 이후 버전화합니다.
중복 key는 `(text_analysis, parent_id)`이며 빈 텍스트는 중복 묶음을 만들지 않습니다.
같은 key에서는 comment_id 사전순 첫 항목을 대표로 선택합니다. 원문과 alias는 삭제하지 않습니다.
중복 alias는 지지 source 수를 늘리지 않습니다. parent는 대표 ID로 재작성하지 않습니다.

2단계 CLI는 별도 `artifact_kind=snapshot_normalization` envelope를 저장합니다.
필드는 `schema_version`, `artifact_kind`, `run_id`, `snapshot_id`, `snapshot_sha256`, `pipeline_version`,
`normalization_version`, `created_at`, `counts`, `snapshot`, `normalized_comments`입니다.
snapshot 원문 전체를 함께 저장하므로 hash만 남기고 원문을 잃지 않습니다. 이 파일은 Factory 완료 결과나 RunManifest가 아닙니다.
counts는 source/top-level/reply/missing-parent/canonical-comment/duplicate-alias/empty-analysis 수이며 eligibility를 추정하지 않습니다.
빈 corpus도 명시적으로 source_count=0으로 반환합니다. 대상 표본 수를 만족했다거나 Factory 실행에 적합하다는 뜻은 아닙니다.

EligibilityRecord 필수 필드:

- `comment_id`
- `status: argument_or_experience | contextual_reaction | question_or_request | non_substantive | spam_or_duplicate | unclear`
- `rationale: string`, `context_comment_ids: string[]`, `confidence: number|null`

모든 원문에 하나의 기록을 남깁니다. contextual reaction은 parent 문맥에 연결하지만 standalone claim을 만들지 않습니다.
low-like·짧은 댓글·소수 언어 자체는 제외 이유가 아닙니다. duplicate alias의 status는 `spam_or_duplicate`입니다.
누락된 parent 때문에 해석 불가능하면 `unclear`로 남기며 missing ID를 존재하는 context ID 목록에 넣지 않습니다.
언어별·eligibility별 오제외율을 인간 표본 검토 대상으로 남깁니다.

## ClaimUnit / 원문 구간

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `claim_id` | string | run 내 고유 |
| `source_comment_id` | string | canonical 원문에 참조; alias를 독립 claim의 출처로 쓰지 않음 |
| `source_spans` | Span[] | 최소 하나; 원문과 일치하는 지지 구간 |
| `context_comment_ids` | string[] | 실제 존재하는 parent/reply 문맥; 지지 근거와 구분 |
| `claim_text` | string | 충실한 해석/요약 |
| `analysis_language` | string | 초기 제안 `en`; 원문 언어와 별도 |
| `issue` | string | 논의 대상의 정규화된 설명; enum으로 고정하지 않음 |
| `stance` | `support | oppose | conditional | mixed | neutral | unclear` | issue에 대한 stance |
| `reason` | string|null | 명시된 이유만 기록 |
| `condition` | string|null | 명시된 조건만 기록; 앞 문장의 조건을 잘라내지 않음 |
| `confidence` | number|null | 추출의 불확실성 |

Span은 `{start: int, end: int, quote: string}`입니다. **원문 Unicode code point 기준의 반열린 구간 `[start,end)`**이며
`0 ≤ start < end ≤ len(text_original)` 및 `text_original[start:end] == quote`를 요구합니다.
Python 문자열 좌표를 기준으로 하고 JavaScript는 UTF-16 index를 그대로 사용하지 않습니다.
분석용 텍스트와 번역문에서 계산한 좌표를 원문 좌표로 사용하지 않습니다.

하나의 원문이 여러 claim을 낼 수 있습니다. 독립 주장은 나눌 수 있지만 “찬성, 단 예외가 있어야 함”은 조건을 붙여 보존합니다.
source span은 provenance 검증 수단이며 그 span이 claim을 의미적으로 지지한다는 자동 증명이 아닙니다.
원문 1개에서 claim 3개가 나와도 지지 source 수는 1입니다.
V1/V2에서 `argument_or_experience`는 0..n claim을 가질 수 있습니다. 0개면 추출 이유를 결과에 기록합니다.
그 밖의 eligibility는 claim 0개이며 `unclear` 원문도 별도 확인 목록에서 보존합니다.

## EmbeddingItem / CandidateCluster

EmbeddingItem 필수 필드: `item_id`, `unit_kind: comment|claim`, `unit_id`, `input_text`, `vector: number[]`.
model identity, model revision(알 수 없으면 null), dimensions, input-template version은 run manifest에 기록합니다.
벡터는 같은 차원의 유한 수이며 cosine 기반 처리 시 영벡터를 거절합니다. 응답 개수·ID 대응을 검사합니다.

CandidateCluster 필수 필드:

- `cluster_id`, `unit_kind: comment|claim`, `member_ids: string[]` (빈 cluster 금지)
- `provisional_label: string`, `status: candidate|accepted|rare|uncertain|superseded`
- `parent_cluster_ids: string[]`, `created_by_review_id: string|null`
- `uncertainty_notes: string[]`

V0의 member는 comment, V1/V2의 member는 claim입니다. 같은 cluster 안에서 종류를 섞지 않습니다.
초기 clustering 결과는 candidate이며 unassigned ID를 별도 보존합니다.
활성 cluster(candidate/accepted/rare/uncertain) 사이에 member 중복은 금지합니다. superseded 이력과의 중복은 허용합니다.
최종 Factory 완료 시 candidate를 남기지 않습니다. 검토를 마치지 못하면 completed가 아닙니다.
이 규칙은 여러 claim을 가진 한 댓글이 여러 cluster와 연결되는 것을 금지하지 않습니다.

## ClusterReview — 상태 전이와 lineage

필수 필드:

- `review_id`, `operation: accept|split|merge|rare|uncertain`
- `input_cluster_ids`, `output_cluster_ids`, `inspected_unit_ids`, `neighbor_cluster_ids`
- `rationale: string`, `uncertainty_notes: string[]`
- `reviewer: {kind: human|model|fixture, identifier: string}`
- `checks: {coherent: bool|null, distinct: bool|null, citation_support: bool|null}`: 의미 검토 결과; 미판정은 null

검토 이벤트는 순서대로 적용합니다. 입력 cluster는 당시 candidate여야 합니다. neighbor는 읽기 전용 참고이며 자동 흡수하지 않습니다.
inspected ID는 입력 또는 명시된 neighbor의 member여야 하고, terminal 판정은 모든 입력 member를 검토 범위에 포함해야 합니다.
긴 cluster는 chunk 검토를 묶어 모든 member가 검토되었음을 보장합니다. 일부 대표 댓글만 보고 완료로 처리하지 않습니다.

| operation | 입력 → 출력 | 적용 후 상태 / 불변조건 |
| --- | --- | --- |
| `split` | 1 → 2 이상 새 cluster | 입력 superseded; 출력 candidate. 출력 집합의 합집합=입력, 출력끼리 서로소 |
| `merge` | 2 이상 → 1 새 cluster | 입력 superseded; 출력 candidate. 출력 집합=입력들의 합집합 |
| `accept` | 1 → 동일 cluster ID | accepted; claim 단위, 서로 다른 canonical 원문 ≥3, coherence/분리/인용 지원 검토 필요 |
| `rare` | 1 → 동일 cluster ID | rare; 의미 있는 관점이지만 서로 다른 canonical 원문 <3 |
| `uncertain` | 1 → 동일 cluster ID | uncertain; source 수와 무관하게 의미·조건·일관성·언어 해석이 불확실 |

claim 단위 terminal 검토와 원문 기반 V0 평가를 혼동하지 않습니다. V0 결과는 이 accept 경로로 agent를 생성하지 않습니다.
accept는 checks의 세 값이 모두 true여야 합니다. 이 플래그는 검토자의 판단 기록이며 의미적 정확성을 자동 보장하지 않습니다.
rare 조건과 uncertain 조건이 함께 있으면 uncertain을 우선하고 낮은 지지 수를 uncertainty_notes에 기록합니다.
split/merge는 member를 추가·삭제하지 않습니다. 모델의 제안에 외부 ID·중복·유실이 있으면 전이 전체를 거절합니다.
검토를 다시 열어야 하면 새 run을 만듭니다. accepted 결과를 제자리에서 바꾸지 않습니다.

## PerspectiveSpec / 문장별 인용

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `perspective_id` | string | run 내 고유 |
| `cluster_id` | string | accepted claim cluster 하나 |
| `title` | string | 근거에서 도출한 짧은 명칭; 사람/집단을 가장하지 않음 |
| `issue`, `stance` | string, stance enum | 해당 cluster의 의미를 반영 |
| `output_language` | string | 사용자 선택에 따른 카드 언어 |
| `summary` | SupportedText | 아래 형식 |
| `reasons`, `conditions` | SupportedText[] | 명시된 근거가 없으면 [] |
| `evidence_claim_ids` | string[] | cluster member와 같은 집합 |
| `representative_claim_ids` | string[] | evidence의 비어 있지 않은 부분집합 |
| `uncertainty_notes` | string[] | coverage/표본/해석의 한계 |

SupportedText는 `{text: string, claim_ids: string[]}`이며 claim_ids는 evidence의 비어 있지 않은 부분집합입니다.
각 중요 카드 문장을 해당 원문 구간으로 따라갈 수 있어야 합니다. 단순히 페이지 끝에 공통 출처 목록만 붙이지 않습니다.
accepted cluster당 하나의 spec만 만들며 claim은 최대 하나의 spec에 속합니다.
언어별 카드 재생성은 동일한 관점/증거에 대한 표현입니다. 여러 언어를 별개 관점으로 세지 않습니다.

후속 EvidenceBundle은 `support_claims`와 `context_comments`를 구분합니다.
원문 전체는 검증용으로 표시할 수 있지만 agent는 배정된 claim/span만 관점의 지지 근거로 인용합니다.
문맥이 새로운 관점을 담더라도 배정 없이 evidence로 승격하지 않습니다.
번역 표시는 `{comment_id, language, text, translator, is_translation: true}`를 별도 보관하며 원문을 덮어쓰지 않습니다.

## RunManifest / 오류

manifest 필수 필드:

- `schema_version`, `run_id`, `snapshot_id`, `snapshot_sha256`, `pipeline_version`
- `variant: V0|V1|V2`, `provider_mode: fixture|live|manual`, `analysis_language`, `output_language`
- `config: object`, `components: object` (단계별 provider/model/revision/prompt 버전), `input_artifact_hashes: object`
- `started_at`, `finished_at: timestamp|null`, `status: running|completed|failed`
- `counts: object` (source/eligible/claims/accepted/rare/uncertain/unassigned/failed 항목), `errors: PipelineError[]`

hash는 입력 파일의 정확한 바이트에 대한 SHA-256입니다. whitespace만 바뀌어도 새 입력으로 취급합니다.
config와 components에는 실제 실행 설정을 저장하되 key/token은 저장하지 않습니다.
V2는 재사용한 V1 산출물의 hash를 기록합니다. fixture 예제는 실제 실행 manifest를 만들어내지 않습니다.

PipelineError 필수 필드: `code`, `stage`, `entity_id: string|null`, `message`, `retryable: bool`.

| code | 처리 |
| --- | --- |
| `INVALID_SNAPSHOT` | 타입/필수 필드/URL/timestamp/중복 ID 오류; 실행 시작 전 거절 |
| `INPUT_READ_ERROR` | 파일 읽기 실패; 코드 1, 원문 내용은 오류에 포함하지 않음 |
| `OUTPUT_EXISTS` | 파일/링크/디렉터리 또는 동시 작성 결과가 이미 존재; 기존 경로 보존 |
| `OUTPUT_WRITE_ERROR` | 디스크/권한/hard-link 지원 등 저장 실패; 완료 결과 공개 금지 |
| `INVALID_REFERENCE` | 거짓 present parent, cycle, 잘못된 claim/source 참조; 실패 |
| `INVALID_SOURCE_SPAN` | 범위 또는 quote 불일치; 추출 결과 거절 |
| `INVALID_MODEL_OUTPUT` | 알 수 없는 상태/필드, 누락 응답; 단계 실패, 원본 응답은 로컬 진단용 |
| `PROVIDER_UNAVAILABLE` | 시간 제한/연결 실패; retryable 표시, 자동 fixture 대체 금지 |
| `INVALID_EMBEDDING` | 응답 수·차원·유한 수·영벡터 오류; clustering 금지 |
| `INVALID_REVIEW` | member 유실/중복/무단 추가/잘못된 상태 전이; 원자적으로 거절 |
| `INSUFFICIENT_SUPPORT` | accept의 지지 수 미달; 승인 거절, explicit rare/uncertain 재판정 필요 |
| `EVIDENCE_BOUNDARY_VIOLATION` | 미배정 claim 또는 context를 근거로 사용; 카드/답변 공개 차단 |

## 이후 AnswerDraft / AuditDecision 경계

6단계에서 세부 계약을 추가합니다. 지금 보존할 연결은
`(run_id, perspective_id, session_id) → question → AnswerDraft → AuditDecision → final answer`입니다.
다른 perspective나 session의 대화 상태를 섞지 않고, 인용은 해당 spec의 claim/span으로 제한합니다.
Auditor의 approve/revise/add_uncertainty/abstain을 저장하며 draft와 final을 구분합니다.
존재하는 citation ID라는 이유만으로 의미적 지지가 있다고 승인하지 않습니다.

## 합성 예제의 읽는 순서

1. c1의 두 문장이 safety review와 fee waiver의 서로 다른 claim으로 추출됩니다.
2. c2/c5는 한국어 원문이고 claim은 영어, PerspectiveSpec은 한국어입니다.
3. c7은 c3에 대한 반응이며 claim·source 지지 수를 늘리지 않습니다.
4. c8은 missing parent를 명시하여 보존하지만 해석 불가로 claim을 만들지 않습니다.
5. c9는 c3의 중복 alias이며 c3의 지지 수를 늘리지 않습니다.
6. k1 split과 k5+k2 merge를 거쳐 안전심사/수수료면제 관점이 각각 원문 3개로 승인됩니다.
7. k3은 rare, k7은 uncertain이며 agent용 spec을 받지 않습니다.

예제의 모든 추출·검토·카드는 사람이 작성한 합성 설계 자료입니다. 모델 출력이나 평가 결과가 아닙니다.
trace 파일의 `initial_clusters`, `review_created_clusters`, `expected`는 전이를 설명하는 설계 전용 컨테이너입니다.
실제 실행 artifact의 파일 형식이나 RunManifest를 대신하지 않습니다. replay 시 초기 후보에서 시작해 review 순서에 따라 출력 후보를 추가합니다.
