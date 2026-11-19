# DS-v1 API·저장·프론트 연결 계약

DEC-029 proposed. 이 문서의 신규 endpoint·DB v2·화면은 **미구현**이다.
기존 [PRODUCT_API](../PRODUCT_API.md)를 보존하고 opt-in capability로 추가한다.
[프로토콜](DEBATE_SYNTHESIS_PROTOCOL.md)의 의미를 프론트나 API 계층에서 다시 정하지 않는다.

## A-01. 공통 계약

- 기존 same-origin JSON·`X-Session-Token`·소유권·request_id·revision 규칙을 재사용한다.
- 소유 세션이 다른 ID는404. 세션 만료401,자료 수명 만료410을 구별한다.
- `expected_revision`은 대상 리소스의 현재 revision과 일치해야 한다. GET/상태 조회는 무료다.
- 비동기 변경은202와 `{job_id,state,room_id}`를 반환한다. 기존 `/api/v1/jobs/{id}`로 조회한다.
  job.result에는 `{resource_kind,resource_id,resource_revision}`를 넣어 해당 GET으로 이동한다.
- 같은 request_id/본문은 기존 결과,다른 본문은409 request_id_conflict.
  다른 request_id여도 같은 snapshot/protocol의 완료된 합의·Compiler 결과는 재사용한다.
- 클라이언트는 model/provider·금액/지지 문턱·verified/accept 결과·원문·출처 inventory를 제출하지 않는다.
- 새 capability가 없거나 false면 새 버튼을 사용 불가로 표시한다. 옛 group을 새 토론으로 위장하지 않는다.

## A-02. 새 endpoint

아래 `S=/api/v1/sessions/{sid}`, `D=/api/v1/debates/{did}`,
`Y=/api/v1/syntheses/{yid}`, `A=/api/v1/synthesis-agents/{aid}`다.

| 요청 | 본문/입력 | 결과·추론 |
| --- | --- | --- |
| POST S/debates | analysis_revision,participant_ids,question,initial_revision,request_id |201,idle debate+전용 room. 추론0 |
| GET D | 선택 after_seq | plan의 공개 부분·revision·상태·게시 메시지·진행/과업 충족·job/합의 목록. 추론0 |
| POST D/start | expected_revision,request_id |202,opening N+reply N job. 최대4N 모델 요청 |
| POST D/control | action,expected_revision,request_id |pause/resume/close/acknowledge_error. 새 합의/추론을 임의 시작하지 않음 |
| POST D/syntheses | expected_revision,request_id |202,고정 transcript snapshot의 초안·명시수락·검증 job. 최대2+2N 요청 |
| GET Y | 없음 | 공개 draft revision·검증된 수락/이유·shared·이견·보류·outcome·can_compile. 추론0 |
| POST Y/agents | expected_revision,request_id |201,유효 shared에서 불변 파생 Agent 생성. 기존 결과면200. 추론0 |
| GET A | 없음 | kind,revision,lineage,accepted_claims/조건,이견,근거·수명·가능 동작. 추론0 |
| POST A/rooms | agent_revision,initial_revision,request_id |201,통합 Agent 전용1:1 room. 추론0 |
| GET A/sources/{source_id} | 없음 | 해당 파생 Agent의 허용 lineage 원문·별도 parent. 추론0 |

새1:1 room은 기존 `GET /api/v1/rooms/{rid}`, `/start`, `/messages`, `/control` 및
job API를 사용한다. room의 `kind=synthesis_chat`을 확인해 별도 SynthesisRuntime으로 dispatch한다.
기존 `POST S/rooms`에 파생 ID를 넣어 댓글 profile처럼 만드는 우회는 허용하지 않는다.
조건·새 논거/외부근거 표시와 answerability·coverage는 기존 message 형식의 추가 필드다.

`POST D/syntheses`는 같은 cutoff/protocol당 한 산출물이다. 새 request_id가 재생성권이 아니다.
불완전 토론/시행 실패·보류에 재질문을 붙여 비용을 반복하지 않는다.
정산 확인 뒤 이미 저장된 응답의 무료 후처리는 별도 host 복구 경로로 처리한다.

### 요청 예시

```json
{
  "analysis_revision": "FROZEN_ANALYSIS_REVISION",
  "participant_ids": ["P1", "P2"],
  "question": "위험 수준에 따라 검토 의무를 다르게 둘 수 있을까요?",
  "initial_revision": 1,
  "request_id": "client-generated-unique-id"
}
```

실제 ID/hash는 서버 GET에서 받은 값이다. 위 상수는 설명용이며 실제 모델 실행 입력이 아니다.

### 합의 결과의 공개 모양

```json
{
  "synthesis_id": "Y_DEMO",
  "revision": 1,
  "outcome": "consensus_ready",
  "shared_claim_ids": ["C_DEMO"],
  "has_holds": true,
  "disagreement_ids": ["DI_DEMO"],
  "unassessed_point_ids": [],
  "can_compile": true,
  "agent_id": null,
  "quality_gate_passed": false,
  "semantic_reliability": "not_assessed"
}
```

실제 GET은 각 ID의 검증된 텍스트/조건·근거·수락 목록을 함께 제공한다.
held proposal 원시 텍스트·unpublished 초안·내부 prompt/경로·금융장부·세션 token은 공개하지 않는다.
has_holds가 있다고 독립 shared claim을 숨기거나 모든 후보를 승인하지 않는다.

## A-03. 상태·오류·동시성

| 상황 | 응답/동작 | 프론트에서 알릴 내용 |
| --- | --- | --- |
| 참가자1명/4명·중복·지원 안 되는 policy/kind |422 invalid_participants/unsupported_admission_policy | 실제 가용2~3관점 선택 |
| 다른 분석 revision/참가자 |409 analysis_revision_conflict | 현재 분석을 다시 확인 |
| 실행 중 중복 start/synthesis |동일 요청 재사용 또는409 resource_busy | 진행 중인 작업 표시,자동 두 번째 실행 금지 |
| target coverage 부족 |정상 job 완료+debate incomplete,can_synthesize=false | 어느 Agent/쟁점이 부족한지와 기존 기록 |
| 전원 유효 수락0 |no_consensus,can_compile=false | 합의 없음·명시 이견. 실행 오류로 표시하지 않음 |
| 검증 미결/누락 |verification_hold | 합의 여부를 판별하지 못한 이유 |
| 예산/기한/문맥 사전 부족 |409 generation_unavailable+reason | 기존 기록 유지,현재 새 생성 불가 |
| 생성 후 검증/전송 실패 |job failed 또는 needs_reconciliation | 이미 게시된 결과·정산 상태 유지,자동 재시도 없음 |
| parent/문헌 수명 만료 |새 생성/compile410 source_expired | 만료 상태와 허용된 저장 기록 |
| revision 충돌 |409 revision_conflict | GET으로 최신 상태 복원,명시 동작만 다시 요청 |
| close와 늦은 응답 경쟁 |닫힌 epoch면 게시 금지·비용 보존 | 닫힘 유지,메시지가 뒤늦게 다시 나타나지 않음 |

GET/poll/새로고침/뒤로가기는 추론을 시작하지 않는다. can_* 상태는 서버가 반환한다.
클라이언트가 UI 버튼 비활성만으로 실행/소유권/수명 정책을 대체하지 않는다.
유효한 기존 합의에서 무료 compile은 생성 기한이 지났어도 자료/소유권이 유효하면 가능하다.
닫기는 추가 모델 실행을 막으며 이미 유효한 보고서의 무료 열람/compile을 지우지 않는다.
세션 만료 후 장기 기록 복원은 현재 미구현인 별도 홈/인증 계약이다.

## A-04. 저장 모델과 migration

기존 SQLite와 하나의 Store/transaction을 유지한다. 개인 DB와 금융 DB는 합치지 않는다.
별도 벡터DB/브로커/외부 Agent 서비스는 v1에 추가하지 않는다.

| 저장 위치 | v2에서의 역할 |
| --- | --- |
| 기존 rooms | kind 누락은 legacy. 새 structured_debate는 mode=group,synthesis_chat은 mode=one_to_one |
| 기존 messages | 모든 게시 토론/통합 대화. seq·room FK·소유권·analysis_revision 유지 |
| 기존 jobs/requests | 새 operation·resource args를 추가해 같은 worker·idempotency·재시작 규칙 사용 |
| debates 신설 | id,room_id UNIQUE FK,protocol,plan_sha256,revision,state,data |
| syntheses 신설 | id,debate_id FK,cutoff_seq,protocol,transcript_sha256,revision,state,data; UNIQUE(debate_id,cutoff_seq,protocol) |
| ratifications 신설 | synthesis_id,agent_id,proposal_id,draft_sha256,data; PRIMARY KEY(synthesis_id,agent_id,proposal_id) |
| synthesis_agents 신설 | id,synthesis_id FK,session_id FK,revision,artifact_sha256,data; UNIQUE(synthesis_id,artifact_sha256) |

수락 과정은 별도 artifact이며 채팅 발화 수나 댓글 지지 수에 더하지 않는다.
상태/cursor는 transaction에서 저장하고 모델 호출 동안 DB transaction을 열어 두지 않는다.
응답 정산 뒤 plan/epoch/소유/기한을 다시 확인하고 게시+cursor를 원자적으로 반영한다.

### 시작·rollback

앱 시작 전 제품 DB를 백업하고 v1→v2를 한 transaction에서 적용한다.
기존 record를 재라벨/재생성하지 않으며 kind 누락을 legacy로 읽는다. 실패하면 rollback한다.
현재 옛 Store는 schema_version!=1을 거절하므로 **구버전 코드가 v2 DB를 읽는다고 약속하지 않는다.**
구버전으로 돌아가려면 중단·신규 기록 별도 보존 후 백업 복원이 필요하다.
version 숫자만1로 고쳐 위장하지 않는다. 금융장부를 새로 만들어 잔액을 복제하지 않는다.
동시에 여러 서버가 migration/작업을 시작하는 배포는 v1 범위 밖이며 단일 시작 권한을 유지한다.

### 기존 API와 Reflect 호환

기존 room의 start/control·legacy API·저장본 형식은 유지한다.
structured_debate room은 기존 room GET으로 읽을 수 있지만 기존 group mutation으로 실행하지 못한다.
새 Controller가 명시된 idempotency/epoch/phase를 관리한다.

새 토론도 기존 rooms/messages에 저장하므로 Reflect의 context_message_ids는 같은 소유권
검사를 재사용한다. serializer는 게시된 텍스트/원문 origin·대상·상태만 제공한다.
합의 초안/ratification 원시 자료는 Reflect가 사용자 의견처럼 채택하지 않는다.
통합 Agent 발언도 AI 제안이며,초기/현재 사용자 의견·원댓글 지지와 구별한다.
원문 사용기한 후 저장 발화/metadata 읽기는 기존 자료 정책의 허용 범위만 유지한다.
새 보고서/Agent가 원문 drawer나 문헌 사용기한을 연장하지 않는다.

## A-05. Figma와 프론트 연결

Figma 원본을 이번에 수정하지 않는다. 구현 담당자는 확정 화면/노드와 아래 동작의 대응표를
먼저 연결한다. 화면 스타일 선택이 backend의 합의·출처·실행 정책을 바꾸지 않는다.

| 사용자 동작/화면 | API와 표시해야 할 상태 |
| --- | --- |
| Explore 카드 선택 | 기존 analyses/관점 사용. 중복·가용 수·조건·실제 지지 출처를 표시 |
| Converse 토론 시작 | POST S/debates→D/start→job/GET D. 원질문·발언·명시 대응 대상을 표시 |
| 토론 진행 | phase/참가자 진행,pause/resume/close. 구현 세부 prompt/모델 설정은 노출하지 않음 |
| 합의 정리 | 명시 POST D/syntheses. 합의·조건·이견·미결정을 분리 |
| 통합 Agent 만들기 | can_compile일 때 Y/agents. 합의0이면 생성 버튼 대신 결과/원 관점 탐색 |
| 통합 Agent 카드/질문 | 새 kind와 'AI가 정리한 합의' 표시. A/rooms→기존1:1 동작. 부모/원문으로 이동 |
| Reflect | 같은 소유 게시 메시지 참조와 기존 수정/저장/reload |

원 Agent 카드는 제거하거나 통합 카드로 덮어쓰지 않는다.
원댓글 수·AI 수락 참가자 수·준비 문헌을 각각 다른 의미로 표시한다.
합의0/검증보류/실행실패를 모두 'Agent 생성 실패' 하나로 합치지 않는다.

기존 vanilla JS 화면은 작은 API client/renderer 모듈로 연결한다.
팀의 최종 프론트도 같은 API를 소비하며 backend/Factory를 브라우저에 복제하지 않는다.
SPA framework 교체·extension 필수화·임의 URL 분석·개인 기록 홈은 여기서 결정하지 않는다.
미구현 API의 mock은 합성 개발용으로 표시하고 실제 동작/품질처럼 시연하지 않는다.
