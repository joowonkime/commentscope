# Factory 상세 설계

설계 `commentscope-detailed-design-20261106-v10`, DEC-001/006, REQ-001/002/003/008.
전체 구조는 **구현 후보 계약**이다. S1/S2의 typed 검토·source record는 첫 opt-in 구현이며,
나머지 후보/관계/논거 교체는 미구현이다. 이전 기준 코드는 [기준선](BASELINE.md)에 있다.
기존 r5 합격 기준은 변경하지 않는다. source 해석의 재사용과 지지 승인은 별개다.

## F-01. 데이터 소유권과 공통 형식

공통 header: `schema_version`, `snapshot_sha256`, `producer_contract`, `request_sha256`, `record_sha256`.
schema/prompt/model/provider/설정은 run manifest에 고정하고 record에서 참조한다.
`record_sha256`은 자기 hash 필드를 제외한 canonical JSON의 기존 `digest` 규칙을 사용한다.
현재 source binding의 `source_sha256`은 id/text/parent/video_context가 포함된 source packet의 digest다.
본문 UTF-8 hash가 필요하면 별도 `text_sha256`을 쓴다. 두 hash를 혼용하지 않는다.

### 엔터티 계약

| 엔터티 | 필수 데이터 | 불변식 |
| --- | --- | --- |
| Source | `source_id`, `canonical_id`, `text`, `text_sha256`, `parent_context`, `video_context`, `expires_at` | 원문/부모/영상 문맥 분리. 중복 alias는 독립 투표 아님 |
| Segment | `segment_id`, `source_id`, `start`, `end`, `text`, `origin` | host가 원문으로 생성. `[start,end)`는 Unicode code point 기준. UI의 UTF-16 offset은 서버 구간 ID로 변환 |
| SourceProposal | `proposal_id`, `source_id`, `text`, `evidence_ids`, `essential_condition_ids`, `completion` | 모델의 출처 해석 제안. 자기 원문 구간만 own evidence, 부모는 reference만 가능 |
| SourceReview | `proposal_id`, `speech_act`, `authorship`, `kind`, `epistemic`, `world`, `scope_links`, `reference_links`, `fidelity` | 원문 전체와 제안을 별도 요청에서 비교. semantic gold/사실 인증 아님 |
| Candidate | `candidate_id`, `text`, `nomination_refs`, `aliases`, `descriptor_id` | 현재 동결 문구와 provenance. nominee도 지지는 별도 판정 |
| CandidateDescriptor | `candidate_id`, `text_sha256`, `kind`, `qualification_spans`, `self_contained`, `status` | 후보 문구 자체만 해석. 다른 원문의 이유/세계/조건을 숨은 정의로 가져오지 않음 |
| Relation | `source_id`, `source_sha256`, `candidate_id`, `candidate_sha256`, `relation`, `authorship`, `scope_match`, `own_evidence_ids`, `primary_request`, `review_ref` | source→현재 최종 문구의 직접 판정. 이전 문구의 표를 단순 합산하지 않음 |
| SourceArgument | `argument_id`, `source_id`, `own_span_ids`, `target_id`, `role`, `kind`, `requires`, `link_review_ref`, `completeness` | 이유/조건/양보/추가 제안을 구분하고 현재 target에 대한 관계를 검토 |
| FactRecord | `claim_id`, `document_ids/hashes`, `scope`, `verdict`, `model_revision`, `expiry` | 주요 사실/필수 사실만 검사. 댓글 지지와 외부 사실 확인을 분리 |
| Perspective | `perspective_id`, `core_candidate_id`, `support_ids`, `argument_ids`, `rare/hold`, `assessed_counts` | 관점과 Agent 적격성 분리. 미평가/조건부/불확실을 숨기지 않음 |
| AgentSpec | `agent_id`, `perspective_id`, `core_claim_id`, `allowed_claims`, `requires_graph`, `source_refs`, `fact_refs`, `limitations` | 사실·의미·출처 검증 전에는 실행 가능한 공개 Agent로 승격하지 않음 |

ID는 host가 계약 버전·source/target hash·선택 구간으로 계산한다. 모델에는 task별 짧은 alias를 제공하고
host가 canonical ID로 복원한다. 모델이 반환한 임의 ID/문장/인용을 연결하지 않는다.

`speech_act`: assertion/request/criticism/question/reported_view/expressed_uncertainty/unclear.
`epistemic`: stated/possible/predicted/conditional/imagined/undecided/unclear.
`world`: real_world/fictional_world/hypothetical_world/mixed_or_unclear.
source의 `authorship`: asserted/explicitly_endorsed/reported/uncertain.
relation의 `authorship`: asserted_or_endorsed/non_asserted/unclear이며 임의의 문자열 cast로 승격하지 않는다.
`kind`는 기존 fact/value/prediction/uncertain을 유지한다. 요구·권고는 발화 기능이 request인 value일 수 있다.
개인 경험은 그 개인의 범위에 남기며 현재 관측을 묘사한다는 이유만으로 value로 바꾸지 않는다.
`fidelity`는 reference/attribution/speech_act/logical_scope/quantities_time/world 각각 preserved/changed/unclear다.
작성자의 미결정 상태가 명확한 경우와 모델이 해석하지 못한 경우를 구별한다.

## F-02. 요청 계약과 대체 경계

모든 요청은 `contract_version/task_aliases/input_hashes/schema/output_limit`을 고정한다.
생성 LLM에 자유로운 설명·자기보고 confidence 점수·중복 prose 상태는 요청하지 않는다. source proposal의 충실한 명제 text만 필요한 생성 필드다.
모든 판정은 구조화된 선택값·구간/대상 ID로 받으며 host는 ID 완전성·범위·중복을 검사한다.
Decisions의 고유 확률·confidence는 raw 관측으로 보존하며 최종 승인의 대체물로 사용하지 않는다.
모델 배정과 transport·오류·비용은 [Decision 계층](DECISION_LAYERS.md)을 따른다.

| 계약 | 입력 | 출력 | 별도로 유지할 검토 |
| --- | --- | --- | --- |
| S1 source proposal | 원문 전체·부모·영상 topic 참조·own segment IDs | source별 최대16명제, evidence/condition IDs, complete/partial/unresolved | S2 |
| S2 source review | 같은 원문 전체·S1제안 | 각 제안의 발화/귀속/양태/세계/참조·범위·충실성 | 같은 요청 안에서 S1와 S2를 생성하지 않음 |
| C1 candidate descriptor | 최종 후보 문구와 host 생성 target segments만 | 유형·필수 범위 구간·self_contained/unclear | M1/M2/E1/E2는 descriptor를 증거로 쓰지 않고 목표 원문을 직접 읽음 |
| E1 equivalent proposal | 두 후보 문구·명시적 범위 | equivalent/a_narrower/b_narrower/opposed/different/uncertain | E2가 양방향 함의·반례를 별도 요청에서 검사 |
| E2 equivalent review | 두 후보 원문·E1 제안 | 두 방향 범위 보존, same-world, difference_found/none/unclear | 양방향 통과만 실제 동치 승인 |
| M1 source relation | 원문 전체·부모·최종 후보 문구·구간 | supported/conditional/opposed/unrelated/uncertain/missing_context, own evidence, 귀속·범위 | supported 제안만 M2 |
| M2 positive review | 원문 전체·목표 문구·M1 선택 구간 | 귀속/조건/범위/양태/세계/반대·인용 보존, 독립 target_kind, 최종 approved/rejected/unclear | 원문 전체를 다시 읽음. S2나 C1을 독립 증거로 대체하지 않음 |
| A1 argument links | 원문 전체·검토된 own 제안·이 source가 지지한 targets | target별 reason/essential_condition/prerequisite/concession/additional_position/core_restatement와 의존 관계 | A2 |
| A2 argument review | 원문 전체·target·A1 연결·필수 전제 | 연결/소유권/유형/필수 전제 완전성 pass/fail/unclear | 실패 필수 전제를 삭제해 구제하지 않음 |

S2가 기존 source-context/world와 node-level 유형/귀속 관측을 맡는다.
C1이 candidate-world/route/inventory/core의 후보 단독 표현을 맡는다.
E1/E2가 기존 여러 양방향 qualifier/반례 요청을 두 계약으로, A1/A2가 node별 alignment/owner/audit를
source-target 단위로 대체하는 후보 설계다. 기존 개별 호출을 유지한 채 이 호출을 추가하는 방식은 채택하지 않는다.

후보 단독 의미와 source가 그 후보를 지지하는지는 합치지 않는다. C1이 잘못된 정보라면 M2는
목표 문구 자체와 원문을 대조해 막아야 한다. 이 오류 독립성은 [검증 사례](EXECUTION.md#x-04-계약-사례)로 검사한다.
M2/A2는 별도 요청이지 독립 사람 gold가 아니다. 검토 모델이 같은 오류를 공유할 위험은 그대로 측정한다.

### 유한 출력과 검증 조건

| 대상 | 초기 cardinality/값 제약 |
| --- | --- |
| S1 | proposal0~16, text1~600자, own evidence1~8, essential condition0~8 |
| S2 | task1~8제안, 제안마다 정확히1결정, scope link0~8·link당 own segment1~8, reference0~4·antecedent1~4 |
| C1 | qualification span0~16, status clear/unclear, 모든 구간은 target 문구에 실제 존재 |
| E2 | 정확히2방향의 보존 판단. 어느 쪽이든 changed/unclear면 equivalent 승인 불가 |
| M1/M2 | source-target1쌍/요청, supported의 own evidence1~8. 필수 관측/target_kind 누락은 실패 |
| A1/A2 | source당 target1~8, 새 argument link0~16, 직접 requires0~8. 초과는 partial/용량 보류 |

출력 토큰 한도는 schema의 최악 출력과 실제 제공자의 reasoning 여유분을 함께 고려해 plan에 고정한다.
글자 수만으로 native token 수를 같다고 간주하지 않는다. 제공자 길이 종료는 자동 재시도하지 않는다.
S2의 kind와 C1의 kind, M2의 독립 target_kind가 충돌하거나 핵심 유형이 불명확하면 후보를 보류한다.
유형 충돌을 다수결·value 선택으로 해소해 사실 검사를 건너뛰지 않는다. 출처의 더 넓은 원문 유형과
그 안의 최소 명제 유형은 구별하며, 비교할 S2 record는 실제 core 명제에 연결된 record여야 한다.

## F-03. 처리 순서

### 1. 입력 등록

snapshot hash·기한·canonical 중복·부모 연결을 검증한다. 전체 canonical scope와 고정 평가 분모를 유지한다.
segment/문장 구조는 기존 parser로 먼저 계산한다. 의미 라벨은 평가 입력에서 가져오지 않는다.
영문/한글, 짧은 반대·조건부·다중 주장도 입력에 남긴다.

### 2. 원문 해석

S1→host 구조 검사→S2→admission 순으로 실행한다.
S2의 changed/unclear는 해당 명제를 보류하고 원문·실패를 남긴다. S2 실패를 삭제하거나 명제를 사람이 고쳐 승인하지 않는다.
명확한 질문·미결정도 상태로 보존한다. 모든 원문을 억지로 확정 stance로 변환하지 않는다.
claim 수 용량 때문에 partial일 때만 남은 구간의 continuation을 최대1회 계획에 포함할 수 있다.
이는 실패 JSON/전송을 재시도하는 것이 아니다. continuation·추가검토 비용을 계획에 포함하고 이후 partial도 드러낸다.
원문 자체가 context에 들어가지 않으면 일부를 잘라 분석하지 않고 capacity hold로 남긴다.

### 3. 후보 등록과 설명

충실한 명제의 정규화 문구를 후보로 만들고 정확히 같은 문구는 aliases/provenance를 합친다.
NFC/공백 정규화만 허용하며 부정·수량·조건·시점은 제거하지 않는다.
C1은 문구별 한 번 요청한다. self_contained=false/unclear인 후보는 donor 문맥으로 몰래 완성하지 않고 보류한다.
새 문구가 필요하면 새 후보 버전이며 그 문구에 대한 source 판정을 다시 해야 한다.

### 4. 실제 지지와 후보 통합

nomination edge도 M1/M2로 직접 판정한다. 검토 전 nomination 수로 주요 관점이나 Agent를 만들지 않는다.
검토된 지지가 있는 후보를 embedding으로 가까운3씩 추천한다. 유사도는 우선순위일 뿐이다.
E1 equivalent + E2 양방향 승인인 pair만 동치 edge다.

현재 complete-link 조건은 유지한다. 그룹 병합을 검토할 때 누락된 모든 교차 pair를 지연 요청하고
전부 승인돼야 병합한다. 기존 top3에 없던 edge를 추론으로 승인하지 않는다.
계획의 pair/금액 한도에 닿으면 병합을 보류하고 후보들을 남긴다. 충분한 비교 없이 큰 그룹으로 합치지 않는다.
대표 문구는 승인 그룹의 안정 ID순 기존 후보 하나다. 그룹 ID는 버전과 정렬된 후보 ID들의 digest다.
대표 변경·합병 후 모든 표시 지지는 **그 최종 대표 문구**에 대한 M1/M2 기록으로 재검증한다.
정확한 source/최종 text/계약/모델이 같은 실행 내 판정은 재사용할 수 있다.

complete-link는 최악 O(K²)이며 큰 의미 군집이 분절될 수 있다. 이 위험은 숨기지 않는다.
representative-star나 새 공통 문구 생성으로 바꾸는 방안은 별도 알고리즘/평가 변경이며 이 설계에서 묵시적으로 채택하지 않는다.

### 5. 전체 댓글 연결

각 source에 최종 후보 top3와 모든 nomination을 연결한다. 기존 조건에 따라 추가3을 한 번 검색한다.
동일 edge 중복 요청은 제거하고 최초 실패 edge를 확장 재시도로 넣지 않는다.
일치 후보가 없다고 원문을 무의미로 삭제하지 않는다. 검색 안 된 관계는 unassessed다.
전수 source×candidate 모델 판정을 기본으로 삼지 않지만 전체 canonical 분모·판정 범위를 함께 표시한다.

```text
for each scheduled (source, frozen_target):
    p = M1(full_original, parent_reference, frozen_target)
    if p.relation != supported: keep p without a support vote
    else:
        r = M2(full_original, frozen_target, proposed_own_spans)
        count only if attribution/scope/condition/world checks all pass
deduplicate by (canonical_source_id, final_target_hash)
```

M1에서 conditional인 관계를 pure target의 supported로 바꾸지 않는다.
조건을 명시한 별도 target에는 같은 source가 supported일 수 있다.

### 6. 논거와 주요 사실

유효 지지≥3 후보를 Agent 준비 대상으로 삼는다. 동일 source가 여러 후보를 지지하면 S1/S2는 공유하지만
각 target에 대한 A1/A2 연결은 구별한다. 한 source 내부 target은 최대8개씩 다루고 전체 원문을 매번 유지한다.
전체 target·own proposal을 다 처리하지 못하면 completeness=partial이며 누락을 기록한다.

논거는 원문 span으로 복원한다. 개인의 이유/경험을 core 지지자 전원의 이유로 부르지 않는다.
reason이 없으면 빈 목록이며 core_restatement·양보·추가 요구로 이유를 채우지 않는다.
core·필수 사실 전제와 노출할 논거의 사실 의존성을 compiler 전에 동결한다.
개인 이유·원문 내부 사실 전제·core 필수 사실 전제의 구분과 각 검토의 실제 입력은
[J4 논거 계약](DECISION_LAYERS.md#d-03-논거-검토의-세부-계약)을 따른다. core 본문이 필요한 검사를 source-only 입력에 맡기지 않는다.
기존 packet/NLI로 주요 사실을 검사하고 미확인·반박·충돌한 필수 전제를 가진 후보는 보류한다.
검사 실패 후 그 전제를 삭제하거나 유형을 value로 바꾸지 않는다.

### 7. Agent 조립

host가 core·출처별 논거·지지 집합·의존 DAG·사실 상태·제한을 조립한다. Agent 소개·성격을 별도 LLM으로 생성하지 않는다.
같은 literal/정규화 주장에 여러 source가 있으면 제공자 집합을 보존한다. 서로 다른 이유는 embedding 유사도만으로 합치지 않는다.
모든 allowed claim의 자기 출처와 필수 전제 closure가 유효해야 한다. dangling ID·의존 cycle은 구조 실패다.
자격이 없는 관점도 rare/held/uncertain과 원문 링크를 남긴다. 서로 다른 Agent 최소2개는 최종 r5 필요조건이다.

## F-04. 관계와 논거의 예시

모든 예시는 합성이다.

| 원문 | target | 판정/연결 |
| --- | --- | --- |
| “주4일제에 찬성한다. 회복할 시간이 필요하다.” | 주4일제 도입 찬성 | supported; 회복 이유는 이 source의 reason |
| “주4일제에 찬성한다. 가족과 시간을 보내고 싶다.” | 같은 target | supported; 가족 이유를 첫 source의 이유로 전파하지 않음 |
| “임금이 유지되는 경우에만 찬성한다.” | 무조건 도입 찬성 | conditional, 확정 지지에 미포함 |
| 같은 원문 | 임금 유지 조건의 도입 찬성 | supported 가능, 두 번 실제 대조 |
| “친구는 찬성하지만 나는 반대한다.” | 도입 찬성 | 친구의 인용은 작성자 지지가 아님 |
| “비용은 걱정되지만 도입에는 찬성한다.” | 도입 찬성 | supported; 비용 우려는 concession, 찬성 이유가 아님 |
| “도입도 좋지만 미지급 초과근무부터 해결하자.” | 도입 찬성 | 추가 요구를 필수 조건으로 자동 승격하지 않음 |
| “찬성인지 아직 모르겠다.” | 도입 찬성 | expressed_uncertainty, supported 아님 |

관계 record 예시(읽기용; hash는 실제 요청에서 host 계산):

```json
{
  "schema_version": "factory-semantics-0.1",
  "source_id": "S3",
  "candidate_id": "P-salary",
  "relation": "supported",
  "authorship": "asserted_or_endorsed",
  "scope_match": "full",
  "own_evidence_ids": ["S3:E1"],
  "parent_reference_ids": [],
  "primary_request": "request-sha256",
  "review_ref": "review-record-sha256"
}
```

실제 record에는 F-01의 공통 header와 정확한 source/target hash가 모두 필요하다. 예시 placeholder를 승인된 artifact로 읽지 않는다.

## F-05. 용량·실패와 다음 단계 승인

| 상황 | 처리 | 하지 않는 것 |
| --- | --- | --- |
| schema/ID/중복/구간 오류 | 원본 응답·과금 보존, task 실패 | 자동 JSON 복구·재호출 |
| length/빈 content/전송 불명 | 새 유료 dispatch 중단, 장부/영수증 확인 | 출력 예산만 바꿔 동일 요청 즉시 재전송 |
| source/parent/target hash 변경 | 해당 결과 stale, 새 계획 필요 | 이전 vote·fact·Agent 재사용 |
| 검토 rejected/unclear | edge/명제 보류, 원문·사유 유지 | 다른 성공 수로 중대 오류 상쇄 |
| capacity/비용 부족 | 미처리 항목과 분모 보존 | 잘린 원문·임의 표본으로 완료 처리 |
| source 기한 만료 | 실행/게시 거부 | 새 snapshot을 기존 평가 분모에 끼워 넣기 |

전체 stage는 `pending → running → completed/held/failed`다. completed는 처리 완료이고 의미 품질 합격이 아니다.
처리되지 않은 source/edge/argument와 보류를 독립 집계한다.

## F-06. 코드 반영과 호환성

기존 `source_interpretation`, `compact_claims`, `pipeline_work`, `pipeline_stages`와 `grounded_inputs`를 출발점으로 쓴다.
`factory-semantics-0.1`용 validator/adapter와 opt-in protocol을 새로 구현한다.
기존 qualified/observed record를 꾸며 새 검토가 있었던 것처럼 만들지 않는다.
의미 검사 일부를 대체하면 evaluator가 새 proof kind를 읽도록 버전 지원을 추가하되, r5 지표·오류 조건은 유지한다.
옛 artifact는 원래 validator로 읽고 소급 합격시키지 않는다.

TASK-003의 첫 범위는 F-01/S1/S2 host binding과 부정 사례다. 이어 C1/E1/E2, M1/M2, A1/A2,
compiler adapter를 순서대로 연결한다. 역할별 구현 파일을 미리 빈 틀로 만들지 않는다.
새 기본 경로 승격은 구조·비용 비교와 동일 설정 fresh 게이트 이후다.

### 첫 구현 단위의 경계

S1은 기존 `compact_claims.TRACED_PROPOSALS`를 재사용한다. S2는 기존 source 검토에 독립 `authorship/kind`
관측을 추가한 별도 protocol을 사용한다. legacy 요청/응답은 그대로 읽는다.
`source_review_protocol`은 `review_interpretations=True`와 traced S1일 때만 명시적으로 선택할 수 있다.
새 검토의 누락 필드를 legacy 값이나 추출자의 제안으로 채우지 않는다.

source record는 `factory-semantics-0.1` header와 원문·traced extraction·typed review·제안별 보류를 결합한다.
header의 request_sha256은 마지막 S1 요청이며 continuation lineage와 각 S2 요청은 원본 record로 보존한다.
record_sha256은 자신을 제외한 전체 host 결합의 digest다. 검증에는 현재 snapshot hash와 현재 source를 함께 제공한다.
원문 record는 지지·사실·품질 승인 값을 항상 false로 유지한다. source 수준 kind 관측은 core 유형 승인과 다르다.

이 단계는 기존 문맥/world/후속 논거 검사를 대체하지 않고 새 기본 경로도 아니다.
독립 지지·논거·사실 검사를 유지한 합성2Agent/6응답 경로까지 연결을 확인한다.
TASK-004는 이 데이터 계약의 모델 진단이며 절감 채택이 아니다. 실제 대체는 TASK-013, 전체 실청구 비교는 TASK-014다.

### 첫 구현의 사용 위치

`source_interpretation.TYPED_REVIEW`는 `source-interpretation-review-20261105-v2`다.
기존 `REVIEW` v1의 요청·응답은 유지하며 새 protocol의 독립 kind/authorship을 누락하면 보류한다.
직접 `nominate`를 호출할 때도 같은 protocol을 명시해야 하며 검토 버전을 혼합하지 않는다.

`minimal_pipeline.process`에 아래 세 옵션을 함께 주면 opt-in 소스 계약 경로를 선택한다.

```python
extraction_protocol=compact_claims.TRACED_PROPOSALS
review_interpretations=True
source_review_protocol=source_interpretation.TYPED_REVIEW
```

이 경로는 별도 `SOURCE_SEMANTICS_VERSION` artifact와 `source_records`를 저장한다.
`source_semantics.bind/collect`는 모델 호출 없는 adapter이며, `validate(record,
snapshot_sha256=..., source=...)`는 현재 snapshot/원문과 결합을 재확인한다.
extractor 실패 원문은 원래 `processing_ids/unextracted_source_ids`에 남기고 가짜 source record를 만들지 않는다.
추가 추출 이전 record와 모든 검토 요청은 그대로 보존한다.

오프라인 확인 명령은 `PYTHONPATH=src:tests:. python -m unittest test_source_semantics_contract`다.
이는 모의 응답의 계약·연결 검사이며 실제 모델 의미 품질·새 정식 gate·비용 절감 검증이 아니다.
기존 원격 실행기/기본 설정으로 이 실험 protocol을 자동 활성화하지 않는다.
