# 원문 증거 그래프와 후보 연결 계약

이 문서는 v1/v2 계약 이력이다. 현재 opt-in 구현의 v3 계약은
[원문 대조 감사](SOURCE_FIDELITY_AUDIT.md)를 따른다. 아래 주석 완전 일치와 단일 양태 축을
현재 v3 계약으로 사용하지 않는다. 과거 응답·실험은 당시 protocol에 묶인 채 보존한다.

계약 후보: `source-evidence-graph-20261112-v2` / DEC-013 / TASK-020~022.
상태: **B1 opt-in 첫 구현·합성 회귀, 실제 의미 채택은 미완료**. [첫 구현 범위](SOURCE_EVIDENCE_IMPLEMENTATION.md)를 함께 읽는다.
[검토 결론](MVP_DESIGN_REVIEW.md)의 F4만 교체한다.
현재 `explicit_discourse`의 parser graph와 새로운 graph는 서로 다른 artifact다.
이 문서의 필드를 과거 응답에 추가해 새 검증을 받은 것처럼 사용하지 않는다.

v2는 실제 v1 비교에서 재현한 정상 상태 코드 처리 결함만 수정한다.
`represented/context_only/nonpropositional`은 진단 상태이며 `issue_codes`에 있어도 차단 오류가 아니다.
명시적 fail/unknown/unassessed,실제 issue code,누락·미해결 Issue,타입/scope/edge 불일치는 계속 보류한다.
동일 규칙을 source observation과 candidate certificate에 적용한다. source 전체 완전성,
필수 사실·최소 지지·Compiler 조건은 유지한다. v1 artifact/plan은 v2 증거로 읽지 않는다.
v1의 실제 결과는 별도 보존하며 이 코드 수정만으로 실제 Agent 증가를 입증하지 않는다.
scope/양태의 정확 비교 계약 자체는 아직 수정·채택하지 않았다.

## 1. B1의 변경 범위

현재 한 문장에 가치·예측·이유가 섞여 있어도 parser가 만든 node 경계는 고정이다.
B1은 전체 원문을 유지한 채, 모델이 **의미상 필요한 원문 구간과 관계를 제안**할 수 있게 한다.
모델은 새 주장을 창작하거나 원문을 paraphrase로 교체하지 않는다. 형식 검증은 host가,
의미상 분리·귀속·조건·필수 전제 검증은 원문을 읽는 독립 관측 경로가 맡는다.

첫 비교에서 기존 source completeness, 모든 eligible 후보의 전체 supporting source 처리,
선택 unit/필수 dependency closure, 사실·최소 지지 기준을 유지한다.
기존 두 alignment hold projection 외에 unresolved unit을 삭제해 source를 살리는 정책은 넣지 않는다.
**Issue의 세분화는 원인 기록을 위한 것이며 자동 admission 완화 권한이 아니다.**

## 2. 공통 타입과 불변 규칙

모든 record는 아래 명시된 필드만 허용한다. optional 필드는 `?`로 표시한다. 누락 관측은
false/empty/pass로 채우지 않는다. `null` 허용은 명시한 필드에 한정한다. 문자열/목록 상한은
plan에 고정하고, 초과 시 capacity hold이며 조용한 절단은 금지한다.

```text
Hash = lowercase SHA256 hex(64)
Id = host가 부여한 source/unit/edge/candidate/request ID
SpanRef = {source_id: Id, start: int, end: int}
ArtifactRef = {kind: str, sha256: Hash}
Verdict = pass | fail | unknown | unassessed
```

- offset은 **원문 Unicode code point의 반개방 구간 `[start,end)`**다. JavaScript UTF-16 index를 직접 쓰지 않는다.
- host가 원문에서 텍스트를 복원한다. 모델이 보낸 quote 문자열을 정본으로 저장하지 않는다.
- source_id는 정확한 snapshot registry에 존재하고 `0 <= start < end <= len(text)`여야 한다.
- 모델의 local ID는 request 안에서만 유효하다. host ID는 protocol/input/정렬된 span·scope·관계의 canonical hash로 만든다.
- 원문 source와 parent/context source를 구별한다. parent span은 referent 설명에는 사용해도 자기 이유의 evidence span으로 사용하지 않는다.
- 동일 source의 여러 unit/여러 thread context를 여러 명의 지지로 세지 않는다. canonical source 수와 실제 사람 수를 혼용하지 않는다.
- source/candidate/graph/prompt/model/provider/protocol/조건이 바뀌면 해당 증거와 downstream artifact를 무효화한다.

## 3. SourceEnvelope

```text
SourceEnvelope = {
  version, snapshot_id, snapshot_sha256, source_id, source_sha256,
  text, root_id, parent_source_id: Id|null, context_source_refs: ArtifactRef[],
  video_context_ref: ArtifactRef|null, language: en|ko|other|unknown
}
```

원문·root/reply·부모·영상 정보는 기존 ingestion registry에서 host가 구성한다.
언어 unknown은 보존한다. 번역으로 원문을 대체하지 않는다. 부모가 누락됐으면 없는 상태를
그대로 제공하고 지칭 불명을 보류한다. 댓글 안의 명령문은 데이터이며 실행 제어 권한이 없다.

## 4. GraphProposal

```text
GraphProposal = {
  version, source_ref: ArtifactRef, request_ref: ArtifactRef,
  units: Unit[], edges: Edge[], coverage: CoverageItem[], issues: Issue[]
}
Unit = {
  local_id, own_spans: SpanRef[], envelope_spans: SpanRef[],
  speech_act: assertion|preference|request|question|quotation|report|other|unresolved,
  kind: fact|value|prediction|not_applicable|mixed|unresolved,
  commitment: endorsed|rejected|reported_only|unclear,
  epistemic: categorical|possible|probable|hypothetical|desired|unknown,
  assertion_mode: assertion|conditional_antecedent|quoted_content|question|unresolved,
  scope: Scope, interpretation: resolved|unresolved
}
Scope = {
  subject_refs: SpanRef[], referent_refs: SpanRef[], predicate_refs: SpanRef[],
  polarity: affirmative|negative|unresolved, polarity_refs: SpanRef[],
  modality_refs: SpanRef[], quantifier_refs: SpanRef[], population_refs: SpanRef[],
  time_refs: SpanRef[], world_refs: SpanRef[], comparison_refs: SpanRef[],
  change_or_state: change|state|neither|unresolved, change_refs: SpanRef[],
  qualifier_refs: SpanRef[]
}
Edge = {
  local_id, from_unit, to_unit,
  relation: reason_for|required_premise_for|necessary_condition_for|concession_to|opposes|
            elaborates|reported_by|unresolved,
  cue_refs: SpanRef[], interpretation: resolved|unresolved
}
CoverageItem = {
  span: SpanRef,
  disposition: represented|context_only|nonpropositional|unresolved,
  unit_ids: Id[], reason_code: str
}
Issue = {
  code, scope: source|unit|edge|candidate, target_ids: Id[],
  obligation: binding|interpretation|ownership|scope|coverage|dependency|capacity,
  evidence_refs: SpanRef[], status: unresolved|resolved
}
```

`version`은 공통 protocol ID에 `/proposal`을 붙인 값이다. type/commitment/scope는 전부 **제안**이며 승인 값이 아니다.
중첩 조건은 condition unit과 방향 있는 edge로 표현한다. condition의 fact형 문구가 조건문 안에
있다는 이유만으로 실제 세계의 사실 주장으로 승격하지 않는다. 반대로 경험적 근거를 value로
바꿔 사실 검증을 회피하지 않는다. `mixed`는 분리할 내용이 있음을 뜻하며 `possible`은 작성자의
불확실한 예측이다. 이 둘과 해석기의 `unresolved`를 구별한다.
not_applicable은 판정 가능한 명제를 주장하지 않는 question/context unit에만 허용한다.
자기 assertion의 fact/value/prediction 판단을 피하는 값으로 사용할 수 없다. 반문이 실제 주장을
담는지는 별도 해석 의무이며 question으로 분류했다는 이유만으로 중요 내용을 제외하지 않는다.

`own_spans`는 해당 source 안에서만 선택하고, 여러 span 및 unit 간 겹침을 허용한다.
공유 조건·주어를 억지로 복제된 새 주장으로 세지 않는다. `envelope_spans`는 해당 unit을
이해할 최소 **완전한 원문 문맥**이며 full SourceEnvelope도 모든 판정에 함께 제공한다.
`referent_refs`만 parent/context를 가리킬 수 있다. 다른 scope 필드는 자기 원문 span이다.

CoverageItem은 source 전체 `[0,len(text))`를 겹치지 않는 순서로 분할한다(공백 포함).
이는 host가 확인할 **문자 범위 완전성**일 뿐 의미 완전성 증명이 아니다. `context_only`나
`nonpropositional`로 중요한 문장을 숨겼는지는 observer가 다시 검토한다.
조건/전제 edge의 순환은 unresolved로 보류한다. 단순한 논거의 상호 참조도 DAG로 임의 변환하지 않는다.

첫 구현용 상한: source당32 units,64 edges,64 coverage partitions,unit당8 own spans.
상한 초과는 원문 단위 `capacity_held`로 기록한다. 원문 길이·provider context·출력 token 상한은
실행 plan에서 별도로 measure한다.600자 뒤 절단,조건 제거,용량 때문에 타입 변경은 하지 않는다.
이 숫자는 제품 품질 문턱이 아니라 versioned 공학 상한이며 실제 분포를 TASK-020에서 확인한다.
envelope_spans는 unit당16,각 scope ref 목록16,missing_units32,issues64,unit별 issue_codes16을 상한으로 둔다.
모든 reason/issue code는 등록된 protocol code이고 길이64 이내다. 자유 설명을 필수 판정으로 사용하지 않는다.
certificate의 각 unit-ID 목록은32,dependency edge64,source당 candidate batch8이다.
plan에는 source별 전체 candidate 수,전체 batch/physical packet 수,input/output/reasoning token 상한,
source/context 길이 상한과 출력 schema의 모든 배열 상한을 빠짐없이 고정한다.
필드/호출 상한이 빠졌으면 Session/provider 생성 전에 거절한다. output token 제한만으로 완전한 응답을 보장한다고 가정하지 않는다.

## 5. 독립 SourceObservation

```text
SourceObservation = {
  version, source_ref, unit_inventory_sha256, request_ref,
  unit_observations: [{unit_id, typing: UnitSemanticFields,
    boundary_fidelity: Verdict, qualifiers_complete: Verdict, issue_codes: str[]}],
  observed_edges: Edge[],
  coverage_observations: [{coverage_index, no_substantive_omission: Verdict,
    missing_refs: SpanRef[], issue_codes: str[]}],
  missing_units: [{own_spans: SpanRef[], obligation: str}],
  scope_coverage: Verdict, ownership_coverage: Verdict, dependency_coverage: Verdict,
  source_language: en|ko|other|unknown,
  issues: Issue[]
}
```

`UnitSemanticFields`는 Unit의 speech_act/kind/commitment/epistemic/assertion_mode/scope/interpretation이다.
모든 Verdict는 pass=해당 보존/완전성 의무 충족, fail=위반이다. unknown/unassessed는 승인하지 않는다.
예를 들어 no_substantive_omission=pass만 누락 없음이며, boundary_fidelity=pass만 경계 보존이다.
observer 입력은 **전체 원문·부모 문맥·host가 복원한 unit 구간과 coverage 경계**다.
proposer의 type/commitment/edge/coverage disposition·이전 합격 verdict·candidate 목록은 숨긴다.
unit 경계를 공유하므로 완전한 blind extraction이나 통계적 독립으로 표현하지 않는다.

observer는 제안 edge에 yes/no만 답하지 않고, 원문에서 관계·필수 조건·누락 명제를 관측한다.
선언 fact0개여도 dependency/누락 검사를 수행한다. 미지정 타깃이나 없는 unit으로 관계를
연결해야 하는 경우 `missing_units`를 반환하고 source를 보류한다. host가 자동으로 제안에 추가하지 않는다.

host 검사는 정확한 inventory·응답 질문 전체성·span 범위·관측 매칭과 비교를 담당한다.
의미 일치를 문자열/embedding 유사도로 대신 승인하지 않는다. 서로 다른 관측은 disagreement hold다.
관측이 맞다고 해서 원문 속 경험적 주장이 사실임을 뜻하지 않는다.
원문 언어도 observer가 별도로 관측한다. unknown은 기존 언어 보류로 연결하며 ASCII 여부로 추정하지 않는다.
host는 unit ID로 관측을 결합하고, 각 enum 및 정렬·중복검사한 scope span 집합을 정확 비교한다.
edge는 `(from,to,relation,sorted cue_refs)`로 canonical 비교하고 local edge ID 차이만 무시한다.
proposal/observer의 다른 unit 경계나 scope 선택은 자동 동치로 합치지 않는다. 해당 불일치/보존 손실도 측정한다.
문자열 normalization이나 추가 숨은 모델 호출로 차이를 해소하지 않는다.
empty ref 목록은 해당 표현이 없다고 관측한 경우이고, 미관측/불명은 Issue와 unknown/unresolved로 남긴다.

## 6. VerifiedGraph와 CandidateCertificate

```text
VerifiedGraph = {
  version, proposal_ref, observation_ref, source_ref,
  binding_checks: {check_id: Verdict}, obligation_results: {obligation_id: Verdict},
  status: complete|unresolved|invalid|capacity_held, issues: Issue[]
}
CandidateCertificate = {
  version, source_ref, graph_ref, candidate_ref, membership_m1_ref, membership_m2_ref,
  request_ref, position_unit_ids: Id[],
  alignment: supports_core|equivalent|conditional|opposed|unrelated|uncertain,
  reason_unit_ids: Id[], concession_unit_ids: Id[], essential_condition_unit_ids: Id[],
  dependency_edges: Edge[], core_required_fact_unit_ids: Id[],
  full_original_coverage: Verdict, ownership: Verdict, scope_preserved: Verdict,
  status: eligible_for_existing_checks|held, issue_codes: str[]
}
```

각 artifact의 version은 공통 protocol ID 뒤에 `/envelope`, `/proposal`, `/observation`,
`/verified`, `/candidate-certificate`를 각각 붙인다. plan의 protocol ID와 혼용하지 않는다.
VerifiedGraph.binding_checks의 필수 key는 `source_hash,span_bounds,coverage_partition,unit_inventory,
edge_inventory,protocol,request_binding,receipt_binding`이다. obligation_results의 필수 key는
`boundary_fidelity,typing,ownership,scope_preservation,substantive_coverage,dependency_coverage`다.
키 누락/추가/빈 map은 invalid이고, complete는 모든 필수 값 pass 및 미해결 blocking Issue0일 때만 가능하다.
protocol code의 전체 enum과 필수 질문 목록은 TASK-020의 의무 대응표에서 먼저 닫고,021은 그 표를 구현한다.
CandidateCertificate는 후보의 최종 문구·graph·원문 전체를 읽는 별도 판정에서 만든다.
M1/M2의 앞선 supported 결론을 자기검증 근거로 사용하지 않는다. 원래 bind 참조는 host가 붙인다.
source별 최대8 candidate의 finite batch로 구성하며 각 candidate의 전체 질문·결과가 필요하다.
초과 후보는 정렬한 다음 batch로 나눈다. 비용은 모든 batch를 포함하며 후보를 조용히 제외하지 않는다.

후보의 주체/시간/조건/부정/대상집단/세계/수량/변화를 source position과 방향을 구별해 비교한다.
다른 이유에서 후보에 빠진 조건을 빌려 완전한 입장으로 만들지 않는다. 원래 M1/M2가 미완료면
새 certificate만으로 map support를 추가하지 않는다. 문구 변경은 candidate identity와 관련 판정을 무효화한다.

edge 방향은 `from_unit=근거·전제·조건`, `to_unit=해당 결론`이다. host는 core에 연결된 position을
시작점으로 삼아 **들어오는** required_premise_for/necessary_condition_for edge를 역방향으로
추적해 필수 closure를 만든다. reason 게시 때 그 reason의 필수 closure도 같은 방식으로 검사한다.
reason_for/concession_to/elaborates만으로 필수성을 추측하지 않으며 독립 dependency 관측을 요구한다.
미해결 필수 edge나 원문 coverage unknown을 edge 없음으로 취급하지 않는다.
기존 core-required failure는 계속 해당 source/candidate를 막는다.
`core_required_fact_unit_ids`는 공통 core 자체의 필수 사실 근거다. 특정 이유의 local premise는
그 unit의 required_premise_for edge로 남기고 모든 source/공통 core의 전제로 union하지 않는다.
factual core의 자기 factual restatement는 직접 core basis로 유지한다.
reason/concession/condition 목록은 모델이 편한 일부를 고르는 게시 shortlist가 아니다.
검증 graph에서 해당 candidate에 귀속된 전체 관련 inventory와 대조하고, 누락/귀속 불명은 기존 completeness로 보류한다.

**B1은 `VerifiedGraph.status=complete`와 기존 completeness 의무를 요구한다.**
기존 두 alignment hold projection만 원 계약 그대로 적용한다. local Issue를 이유로
source-wide hold를 제거하는 정책은 B2이며 이 protocol에는 포함하지 않는다.
기존 Compiler의 optional reason omission은 유지하지만 미완료 source admission을 우회하지 않는다.

### 조건과 게시 텍스트의 변환

`assertion_mode=conditional_antecedent`는 기존 `scope_annotation_only`에 대응한다.
조건 내용의 kind가 fact여도 그 조건이 현실에서 참이라고 주장하거나 검증된 fact로 게시하지 않는다.
assertion/quoted_content/question은 각 원문 commitment와 함께 검사하며, unresolved는 보류한다.

Graph의 여러 own_spans를 이어 붙여 원문에 없는 문장을 만들지 않는다. B1에서 게시할 수 있는
claim.text는 **하나의 연속된 원문 assertion 구간**이며, 필수 조건/귀속/지칭 문맥은 기존
scope·required-premise·citation 계약으로 빠짐없이 동반해야 한다. host가 선택한 fragment가
단독으로 더 강한 주장이 되는지 candidate/runtime fidelity 검토를 거친다.

연속 구간+기존 scope/인용 경로로 의미를 손실 없이 전달할 수 없으면 `unrepresentable_hold`다.
전체 envelope를 단일 fact/value로 다시 분류하거나, 조건을 삭제하거나, generated paraphrase를
literal claim처럼 게시하지 않는다. fragment-aware runtime 확장은 별도 DEC이며 B1 밖이다.
중첩 조건을 기존 flat scope로 옮겨 의미를 보장할 수 없으면 첫 구현은 같은 unrepresentable_hold로 보류한다.
B1의 표현 개선이 이 lowering 한계 때문에 실제 게시 개선으로 이어지는지도 비교 지표에 포함한다.

## 7. 판정 의무의 이전

새 경로는 아래 기존 의미 의무에 대응하는 호출만 교체한다. 각 graph는 legacy/new 중 하나의
protocol로 고정한다. 과거 응답과 새 응답 중 유리한 것만 골라 합치지 않는다.

| 의무 | 현재 | B1 담당 | 계속 거절할 사례 |
| --- | --- | --- | --- |
| 원문·구간·부모 | registry/parser | SourceEnvelope+host spans | 다른 source 구간,offset 변조,부모 이유 차용 |
| 단위 type/귀속/세계/시간 | node metadata | proposal+SourceObservation | mixed 강제fact/value,reported를endorsed로 변경 |
| 원문 전체 의미 보전 | source completeness/audit | coverage+missing_units+기존 의무 대응 | 중요한 내용을 nonpropositional로 숨김 |
| source-position과 후보 | alignment/owned position | CandidateCertificate | poor-only→everyone,may→will,서로 다른 행동 |
| 이유·조건 소유권 | owner/discourse | observed_edges+certificate | 조건을 단순 이유로 약화,A의 이유를B로 이동 |
| 필수 사실/전제 완전성 | dependencies/coverage/audit | 원문 관측+후보 closure | fact0이므로 검사 생략,필요 premise 누락 |
| 개별 fidelity·fact 검사 | 기존 review/fact records | 기존 의무를 유지하는 version adapter | 숫자 창작,경험적 주장을 value로 바꿔 검증 회피 |
| 적격·인용·runtime | minimal_agents/grounded_inputs/runtime | 명시적 신규 version adapter | 필수 closure 삭제,가짜 Agent 추가 |

새 graph가 old record의 version/hash/receipt를 흉내 내 old validator를 통과하는 방식은 금지한다.
`source_arguments`/review/Compiler 입구에 명시적 protocol dispatch를 추가하고 unknown을 거절한다.
같은 의미 의무를 old scalar와 new graph 호출로 항상 이중 실행하지 않는다.
첫 비교에서는 서로 다른 arm으로 비용·결과를 분리한다.

## 8. 오류와 재해석

| 상태 | 처리 |
| --- | --- |
| invalid binding/schema/unknown ID | artifact 무효,source 보류. 의미 재시도로 숨기지 않음 |
| capacity_held | 원문 전체 보존,상한/transport 변경은 별도 revision. 절단 금지 |
| proposer/observer disagreement,mixed/unresolved | proposal·관측·Issue 보존,B1 보류 |
| 필수 condition/ownership/coverage unknown | 관련 후보 승인 금지,무관하다는 증거 없이 local 구제 금지 |
| provider503/과금불명/자원보호 | X의 기존 중단·회계·복구,semantic repair로 취급 금지 |
| fact support unavailable | 기존 필수 closure 보류,기존 optional omission만 적용 |

B1의 **자동 재해석0회,모델 재시도0회**로 표현 변경의 효과부터 측정한다.
나중 repair를 비교한다면 별도 한도·구체적 Issue·새 graph revision·전체 재검증 비용이 필요하다.
기존 artifact를 덮거나 사람이 결과에 맞게 원문을 다시 쓰지 않는다.

## 9. 합성 예시와 필수 회귀

아래 예시는 실제 댓글이 아니다.

| 원문 | 기대 | 거절할 결과 |
| --- | --- | --- |
| “I favor P because fairness matters.” | value 입장과 자기 value 이유 | 다른 사람 이유·경험으로 변경 |
| “If costs stay below 10, I support P.” | 공유 조건과 조건부 입장 | 무조건P,10 삭제/변경 |
| “P may reduce attendance, so I oppose P.” | 변화 prediction과 반대·이유 edge | attendance is low로 변경 |
| “My friend favors P, but I oppose it.” | 보고된 친구 입장과 자기 반대 분리 | 자기P찬성으로 집계 |
| root에 이유,reply“That is unfair.” | 지칭 해소만 parent 참조,reply 자신의value | root 이유를 reply의 것으로 인용 |
| “I want P, which would protect artists.” | desire 세계와 조건부 예측 | 실제로 보호한다는 fact로 승격 |
| “P is good. Also, what about Q?” | 두 unit,질문은 질문 | Q를P의 이유로 만들기,미해결 unit을 임의 제거해 B1 합격 |
| “P works only because F is true.” | F의 필요성을 closure에 유지 | F가 선언되지 않았다는 이유로 검사 생략 |

nested 조건,수량/근사,이중부정,인용,가정세계,policy bundle,정정,동일source중복,
empty/fact0,Unicode offset,32초과unit,edge순환,oldreceipt 재사용,missing observation도 확인한다.
negative를 보류하는 능력과 대응 valid positive를 보존하는 능력을 함께 검사한다.

첫 구현의 host record는 `artifact_kind`와 원래 source/envelope,request hash,output을 보존하는 wrapper를 쓴다.
위 타입 표는 논리 필드 계약이다. 실제 생성 schema와 host wrapper의 정확한 필드는
`source_evidence_graph`/`source_evidence_requests`의 request/bind/validate 함수가 함께 고정한다.
snapshot/root/parent/video 식별은 immutable envelope의 원래 source와 snapshot hash에 보존하며
graph가 기존 registry의 별도 사본을 새 사실로 생성하지 않는다.
