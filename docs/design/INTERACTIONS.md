# Explore·Converse·Reflect 상세 설계

설계 `commentscope-detailed-design-20261106-v8`. DEC-002/003/004/006, REQ-004~009.

비교·대화·성찰의 생성 역할과 Controller/저장/출처의 코드 책임, 배정 provenance는
[Decision 계층](DECISION_LAYERS.md)의 GEN-3/H2를 따른다. 첫 Jev 비교는 Factory 논거 component에 한정한다.
아래는 후보 상세 계약과 후속 확장을 포함한다. 현재 `/api/v1` 개발 구현·필드·차이는 [현재 API](../PRODUCT_API.md), 검증 범위는 [결과](../PRODUCT_DELIVERY_RESULT.md)를 따른다. 기존 [M0 API](../COMPARE_BACKEND_API.md)는 유지한다.

## I-01. 공통 요청·권한·revision

analysis는 `analysis_id + bundle_revision`으로 동결한다. session/room은 이를 참조하고 대화 중 교체하지 않는다.
서버가 등록한 analysis만 선택한다. source hash·사용기한·적격 Agent를 호출 전과 게시 전에 확인한다.
개발용 experimental bundle과 정식 검증 bundle의 상태를 구별하며, CI 통과로 qualified를 부여하지 않는다.

신규 anonymous session은 클라이언트가 생성한 충분한 난수의 32-byte token을 `X-Session-Token`으로 전달하고
서버는 token hash만 저장한다. 새 session 생성의 재요청에도 같은 token/request_id를 사용한다.
기존 `/api/session`의 서버 token 발급 방식은 바꾸지 않는다. 모든 자원은 token 소유 session 아래에서만 찾는다.
다른 session의 room/message/reflection ID는 존재 여부를 노출하지 않고 404다.

모든 변경 요청은 `request_id`(기존과 같은 ASCII 영숫자/하이픈, 1~80자)와 revision을 갖는다.
동일 session+operation+request_id+본문 hash는 같은 job/결과를 반환하고 새 추론하지 않는다.
본문 hash에는 operation·대상 resource ID·입력 revision도 포함한다.
같은 key의 다른 본문은409다. stale `expected_revision`도409이며 서버의 최신 revision을 함께 반환한다.
GET/poll/source 열람은 추론하지 않는다. model/키/지출 장부는 클라이언트가 정하지 않는다.

session 만료·저장 기한은 deployment의 명시적 정책 값이다. 누락 시 prepare를 거부하고 임의 상수로 채우지 않는다.
source 열람·생성의 유효기간은 session과 source 만료 중 빠른 시점이다. 사용자 자체 의견/저장본 읽기와
만료된 댓글 원문 재노출은 구별한다. 근거가 만료되면 링크는 expired 상태로 반환하고 원문을 다시 게시하지 않는다.
초기 worker queue는8개, room당 active job은1개로 제한한다. 초과는429 queue_capacity/409 room_busy다.
모델 호출은 전역1개이며 pause/close/GET는 모델 queue에 기다리지 않고 제어 상태를 반영한다.

## I-02. 리소스와 API

신규 API의 JSON은 아래 명시한 키만 허용한다. hash·유효 IDs·길이·소유권을 host가 재검증한다.
201은 비용 없는 리소스 생성, 202는 작업 접수, 200은 기존 결과/GET이다. 실제 모델 완료는 job 상태로 확인한다.

| 경로 | 요청의 핵심 필드 | 결과 |
| --- | --- | --- |
| `GET /api/v1/analyses` | 없음 | 등록 자료의 영상 metadata·revision·available/experimental/expired·가용 Agent |
| `POST /api/v1/sessions` | `analysis_id,bundle_revision,initial_opinion,request_id` | session_id·initial_revision=1·관점 목록. header token과 중복 요청 결합 |
| `GET /api/v1/sessions/{sid}` | 없음 | 초기/현재 의견 revision·관점·room 목록·성찰 저장 목록·가용 동작 |
| `PUT /api/v1/sessions/{sid}/opinions/initial` | `text,expected_revision,request_id` | 새 initial_revision. 이전 room/분석의 입력은 덮어쓰지 않음 |
| `PUT /api/v1/sessions/{sid}/opinions/current` | `text,expected_revision,request_id` | 새 current_revision과 host 구간 ID. 생성 호출 없음 |
| `POST /api/v1/sessions/{sid}/comparisons` | `perspective_id,initial_revision,request_id` | comparison job. 완료 결과는 정확한 initial/bundle revision에 결합 |
| `POST /api/v1/sessions/{sid}/rooms` | `mode,participant_ids,initial_revision,request_id` | room_id·revision·idle. 리소스 생성만으로 토론 실행하지 않음 |
| `GET /api/v1/rooms/{rid}` | `after_seq` 선택 | room 상태·revision·그 이후 게시 메시지·partial round·현재 job |
| `POST /api/v1/rooms/{rid}/start` | `opening_question,expected_revision,request_id` | 그룹 opening/reply job 또는1:1 첫 질문 job |
| `POST /api/v1/rooms/{rid}/messages` | `text,reply_to_message_id,expected_revision,request_id` | 사용자 질문에 대한 bounded job. reply_to는 null 또는 같은 room의 게시 메시지 |
| `POST /api/v1/rooms/{rid}/control` | `action,expected_revision,request_id` | pause/resume/next_round/close/acknowledge_error. 다음 실행 가능 여부 포함 |
| `POST /api/v1/sessions/{sid}/reflection-analyses` | `initial_revision,current_revision,context_message_ids,request_id` | 정확한 두 의견 revision의 성찰 분석 job |
| `POST /api/v1/sessions/{sid}/reflections` | `initial_revision,current_revision,analysis_job_id,user_items,expected_revision,request_id` | 새 채택본 revision=1, expected_revision=0. 생성 호출 없음 |
| `PUT /api/v1/sessions/{sid}/reflections/{id}` | 위와 같은 필드 | 최신 reflection revision과 일치할 때 새 저장 revision 추가 |
| `GET /api/v1/sessions/{sid}/reflections/{id}` | 없음 | 저장한 사용자 본문·범주·관련 대화 참조와 stale/expired 상태 |
| `GET /api/v1/jobs/{id}` | 없음 | queued/running/succeeded/failed/cancelled/needs_reconciliation·결과 참조 |
| `GET /api/v1/sessions/{sid}/sources/{source_id}` | 없음 | bundle의 허용 원문과 별도 parent_context. source 유효기한 확인 |

`mode`: one_to_one(정확히1명), group(2~3명). 기존 두 관점 동일 질문 compare는 legacy adapter로 유지한다.
새 mode가 기존 compare의 all-or-nothing round 동작을 바꾸지 않는다.
초기 의견500자·질문1,000자·현재 의견 제안2,000자는 code point 길이이며 초과 입력을 자르지 않는다.
그룹/성찰을 지원하지 않는 구형 서버는 capability를 false로 반환하고 프론트가 미지원 상태를 표시한다.

### 공통 job 응답

```json
{
  "job_id": "J1",
  "state": "queued",
  "resource_id": "room-1",
  "resource_revision": 3,
  "last_committed_seq": 2,
  "result_ref": null,
  "error": null
}
```

성공 결과에는 사용한 analysis/opinion/context revision이 필수다.
실패는 `error:{code,message,retryable:false,details}`와 필요한 최신 revision/미처리 범위만 반환한다.
원시 모델 응답·prompt·장부·내부 파일 경로는 반환하지 않는다.

## I-03. Explore 비교

입력은 사용자 초기 의견 원문 구간과 선택한 perspective의 검증 core/조건/이유다.
한 요청은 한 관점에 대한 comparison이며 다른 사용자의 의견·대화를 넣지 않는다.
사용자 의견은 댓글 지지 집합과 별도 저장한다.

모델의 출력 항목:

| 필드 | 조건 |
| --- | --- |
| `relation` | agreement/difference/additional_condition/unclear |
| `user_span_ids` | 초기 의견 revision의 실제 구간. 없는 사용자 주장을 만들어내지 않음 |
| `perspective_claim_ids` | 해당 bundle/관점의 허용 주장과 필수 전제 |
| `explanation` | 위 구간의 관계만 설명하는 짧은 제안. 새로운 댓글 사실·일반화 금지 |
| `consideration_question` | null 또는 두 입력의 명시된 범위에서 만든 질문. 정답·입장 변경 요구 금지 |

비교 항목은0~6개, explanation은 항목당 최대300자, consideration_question은 최대240자다.
항목 수를 채우기 위해 일치·차이를 만들어내지 않는다. 한도는 schema와 출력 예산에 결합한다.
host는 모든 ID·revision·소유권·필수 조건 연결을 검사한다. 설명의 의미적 충실성은 고정 사례로 별도 평가한다.
일치가 확인되지 않았다고 difference로 처리하지 않는다. 사용자 의견이 비어 있으면 추론 없이
comparison_unavailable를 반환하고 관점 탐색 자체는 허용한다.
입력 의견 수정은 새 비교를 요구한다. 이전 비교를 새 의견의 결과처럼 표시하지 않는다.
같은 의견·bundle·관점·contract/prompt/model의 완료 결과 재열람은 호출하지 않는다.

## I-04. 1:1와 그룹 Controller

### Agent 응답 계약

기존 허용 claim 선택·host 렌더링을 재사용한다. 답변은 발화자 자신의 core/이유/조건과 인용으로 구성한다.
모델에는 선택 대상 claim·역할·필수 전제·제한된 대화 문맥을 보내며 원문999개나 전체 인용 목록을 매 턴 보내지 않는다.
그룹의 다른 발언과 사용자 입력은 질문을 이해하는 문맥이며 새로운 사실 근거가 아니다.
`reply_to_message_id`와 응답 대상을 표시하되 근거가 없으면 해당 쟁점에 대해 보류한다.
즉흥적인 정책 합의·새 해결책을 발명해 토론을 매끄럽게 만들지 않는다.
초기 host 표현은 응답 대상 인용과 자기 point를 연결하는 정해진 문구를 쓴다. 예: “이 쟁점에 관해 이 관점은 …”.
자연스러움·반복 읽기 부담은 제품 검증 대상이다. 자유 서술·생성 번역이나 별도 LLM 수정기를 이미 제공한다고 약속하지 않는다.

Agent catalog가 큰 경우 query payload는 core와 질문 역할에 맞는 최대8개 논거 claim 및 필수 전제 closure를 사용한다.
검색은 embedding/역할로 후보를 찾으며 논거를 새로 요약하지 않는다. context가 closure를 담지 못하면 capacity hold다.
claim corpus 전체를 담지 않은 경우 응답의 `evidence_scope=retrieved_subset`을 명시한다.
근거를 찾지 못하면 `not_in_context`이며 “이 관점에는 이유가 없다”로 일반화하지 않는다.
기존 전체 allowlist의 `not_in_evidence`와 구별하는 새 adapter가 필요하다.
현재 runtime의 grounded/partial 의미와 새 retrieval 범위를 섞지 않는다.

게시 메시지:
`message_id,room_id,seq,round_id,author_kind,agent_id,reply_to_message_id,body/points,
citations,required_premises,evidence_scope,answerability,analysis_revision,created_at`.
모델이 message/source ID를 새로 만들지 않는다. 필수 전제는 host가 closure로 붙인다.

### 그룹 실행 순서

1. 실제 가용 Agent2~3개와 opening question·analysis revision·방문 순서를 room plan에 고정한다.
2. opening round에서 각 Agent가 한 번씩 자신의 입장/명시 이유를 답한다.
3. reply round에서 각 Agent가 같은 순서로 앞서 게시된 다른 Agent의 쟁점에 한 번 응답한다.
4. 모든 턴은 게시된 메시지의 seq cutoff만 본다. 앞으로 나올 메시지나 실패한 초안을 보지 않는다.
5. opening+reply 완료 후 자동으로 awaiting_user다. 사용자 질문은 참여 Agent당 최대1답변을 예약한다.
6. 사용자 next_round도 명시적으로 한 round만 실행한다. 총 Agent 발화18개·room 금액 한도 중 먼저 도달하면 종료한다.

방문 순서는 model이 정하지 않는다. 초기에는 선택 순서를 고정하고 반복 사용성 편향은 측정한다.
실제 Agent가2개면2개로 실행하고 부족한3번째를 합성하지 않는다.

### 상태 전이

```text
idle --start--> running --round complete--> awaiting_user
running --pause--> pausing --current call settled/published--> paused
paused --resume--> running (남은 cursor부터)
paused/awaiting_user --question or next_round--> running
idle/paused/awaiting_user --close--> closed
running/pausing --close--> closing --call settled, late output withheld--> closed
any active --model/validation failure--> error
any active --uncertain charge--> needs_reconciliation
running --turn/budget limit--> exhausted
error --acknowledge_error, charge known--> paused
error/exhausted --close--> closed
```

pause는 진행 중 HTTP/model 호출을 없었던 것으로 만들지 않는다. 현재 턴을 정산·검사·게시한 뒤 다음 dispatch를 멈춘다.
사용자가 입력창에 개입하면 프론트는 pause 요청→paused 확인→질문 전송 순으로 처리한다.
pausing 중 질문은409 room_not_ready이며 자동 유료 재시도하지 않는다.

`room_revision`은 제어/게시마다 증가한다. dispatch에는 별도 `generation_epoch`와 cursor를 고정한다.
pause는 epoch를 바꾸지 않아 현재 턴을 안전하게 마칠 수 있다. close/새 사용자 턴은 epoch를 바꾸며
이전 epoch의 늦은 응답은 정산만 하고 게시하지 않는다. source 만료도 게시를 막는다.

### 부분 실패

신규 그룹은 발화 하나를 원자적으로 게시한다. 이전 게시 턴은 유지하고 실패 round는 partial로 표시한다.
끝나지 않은 round를 성공으로 표시하거나 전체 round를 자동 재실행하지 않는다.
미완료 job은 원본 응답·정산 여부·마지막 게시 seq를 보고 복구한다.
known failed job을 acknowledge_error로 확인한 뒤 별도 사용자 질문을 시작할 수 있다. 이 동작은 실패한 원래 호출을 재전송하지 않는다.
needs_reconciliation은 이 제어로 해제하지 못한다. host가 기존 장부의 근거를 대조한 뒤 복구/취소 상태를 결정한다.
기존 legacy compare는 모든 선택 Agent 성공 후 round 게시·실패 시 이력 rollback을 유지한다.

## I-05. Reflect

입력은 initial_revision, 현재 의견 원문, 명시적 context_message_ids와 analysis revision이다.
현재 의견 원문은 비용 없는 PUT으로 저장한 current_revision에서 읽는다. 분석 endpoint에서 문구를 몰래 수정/저장하지 않는다.
context message IDs는 최대24개다. 한도를 넘으면 사용자가 문맥을 선택하도록 capacity 오류를 반환하고 몰래 생략하지 않는다.
context는 같은 session의 게시 완료 메시지만 허용한다. 다른 room의 메시지는 같은 소유 session이고 사용자가 선택한 경우만 가능하다.
실패 초안·다른 사용자·초기 의견 이후의 미래 메시지를 참조하지 않는다.
분석 시 입력 메시지 ID/seq/hash 목록을 동결하며 이후 대화가 늘어도 이전 분석을 덮어쓰지 않는다.

모델 출력은 `stayed/changed/newly_learned/worth_more_thought` 네 배열이다.
항목은 `item_id,initial_span_ids,current_span_ids,related_message_ids,explanation`을 갖는다.
범주별0~4항목·설명 최대240자이며, user_items 저장에도 유한 길이와 실제 참조 ID 검사를 적용한다.
changed에는 실제 비교 가능한 전/후 구간이 필요하다. 새로 배운 점은 현재 사용자 글에 근거가 있어야 한다.
열린 질문은 현재 글의 미결정/추가 고려 구간에 연결하며 없는 고민을 만들어 넣지 않는다.
어느 범주든 빈 배열이 가능하고 의견 유지도 정상 완료다.

관련 대화는 이해를 돕는 연결이지 의견 변화의 인과 증명이 아니다.
모델이 “이 Agent가 생각을 바꿨다”라고 쓰면 사용자가 명시한 근거가 없는 한 검증 실패 사례로 기록한다.
host는 ID·문자 구간·revision·소유권을 검사한다. 의미적 분류와 설명은 별도 평가하며 자동 정답 점수를 만들지 않는다.

분석 job은 사용자 초안과 AI 제안을 분리 저장한다. 저장 endpoint는 current_revision의 원문과 user_items를 사용자가 채택한 내용으로 기록한다.
AI 제안을 그대로 저장하도록 강요하지 않는다. 저장 자체는 새 추론이 없다.
초기/현재 의견 수정 또는 context 변경 후 재분석은 새 revision/job이며 이전 결과는 historical/stale로 남는다.
analysis_job_id는 null(수동 정리) 또는 소유 session의 성공한 분석 job이다. 후자는 initial/current revision이 정확히 일치해야 한다.
사용자가 분석 후 글을 바꾸면 새 current_revision을 저장하고 AI 재분석 또는 analysis_job_id=null의 수동 저장을 선택할 수 있다.
이전 분석을 새 글의 분석으로 붙이면409 analysis_revision_conflict다. user_items의 구간은 저장할 revision의 실제 구간이어야 한다.
reflection 수정은 기존 row를 덮어쓰지 않고 새 revision을 삽입한다. 사용자의 편집·유지·수동 정리에 AI 비용을 강제하지 않는다.
source 만료 후에도 정책상 유효한 사용자 자체 저장본과 만료된 source 인용의 표시를 구별한다.

## I-06. 저장·원자성·재시작

새 앱 상태용 SQLite는 기존 지출 장부와 분리한다. 값은 bound parameter로 저장하고 FK/unique 조건을 적용한다.
MVP worker는 하나이며 기존 process/plan lock을 유지한다. lease timeout만 보고 진행 중 호출을 다른 worker가 재전송하지 않는다.

| 테이블 | 핵심 키/데이터 | 제약 |
| --- | --- | --- |
| analysis_registry | analysis_id,revision,bundle_sha,path,status,expires_at | (analysis_id,revision) unique, artifact 불변 |
| app_sessions | session_id,token_hash,analysis_id,bundle_revision,expires_at | token_hash unique |
| opinions | session_id,kind,revision,text,sha256 | (session_id,kind,revision) PK, 이전 원문 수정 불가 |
| rooms | room_id,session_id,mode,participants,state,revision,epoch,cursor,last_seq,turn_count,plan_sha | 참여자가 해당 analysis의 실제 Agent |
| messages | message_id,room_id,seq,round_id,agent_id,reply_to,payload,sha256 | (room_id,seq) unique, 같은 room의 reply 참조 |
| jobs | job_id,session_id,room_id,operation,request_id,request_sha,state,worker_instance,epoch,result_ref | (session_id,operation,request_id) unique |
| reflections | reflection_id,session_id,initial_revision,current_revision,context_hash,analysis_job_id,user_items,revision | (reflection_id,revision) PK, 정확한 입력 revision과 소유권 |

게시 순서는 다음과 같다.

1. 앱 transaction: job 입력/epoch/cursor를 durable하게 등록한다.
2. 기존 공유 장부에 요청 상한을 예약하고 provider를 호출한다.
3. 원시 영수증·응답을 checkpoint에 먼저 보존하고 실제 비용을 정산한다.
4. host 검증·source 유효성·epoch를 확인한다.
5. 앱 transaction 하나로 message/result 저장, seq/revision/cursor 증가, job 완료를 기록한다.

두 DB가 하나의 transaction이라고 가정하지 않는다. 정산 후 게시 전 crash는 같은 응답을 재결합해서 복구한다.
이미 게시된 seq/request_id는 unique 제약으로 중복 게시를 막는다. 비용을 알 수 없는 호출은
needs_reconciliation으로 남겨 전체 새 유료 dispatch를 막고, 처리 증거 없이 reserved를 지우지 않는다.
프로세스 재시작은 원래 plan·checkpoint·장부·앱 job을 대조하며 새 session/room으로 비용 한도를 초기화하지 않는다.

## I-07. 화면과 오류 계약

| Figma 동작/상태 | API/클라이언트 동작 |
| --- | --- |
| Before Use 저장 후 탐색 | session 생성, 초기 의견 revision 보존 |
| 관점 카드 팝업 | comparison job 조회. 준비/실패/비교불가 상태를 기존 팝업에 표시 |
| New chat/1:1/Group | 가용 participant 선택, room 생성 후 명시적으로 start |
| Live discussion·pause·사용자 개입 | room seq poll·control·paused 확인 후 질문 |
| Evidence badge | 인용 source 조회, 부모는 별도 문맥으로 표시 |
| Reflect·Analyze | current 의견의 비용 없는 PUT 후 opinion/context revision 동결→reflection job |
| 관련 대화 | 해당 room/message seq로 이동, 없는/만료된 자료는 상태 표시 |
| Save my reflection | 해당 의견 revision의 AI 채택본 또는 수동 정리 저장, 모델 호출 없음 |

400 invalid_input / 401 session_expired / 404 resource_missing / 409 revision_conflict,
request_id_conflict,room_not_ready,source_expired / 422 no_eligible_agent,context_capacity /
429 session_capacity / 503 budget_exhausted,reconcile_required,provider_unavailable를 구별한다.
이 code들은 개발 계약이다. 화면은 사용자가 할 수 있는 다음 동작을 쉬운 말로 표시하며 schema/모델 내부값을 노출하지 않는다.
평범한 재열람·poll·중복 클릭은 유료 호출을 만들지 않아야 한다.
