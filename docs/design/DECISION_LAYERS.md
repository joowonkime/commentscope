# Decision 계층과 모델 호출 상세 설계

설계 `commentscope-detailed-design-20261106-v8`, DEC-007, TASK-016/005.
연결: REQ-001~010, [제품 명세](../MVP_SPEC.md), [Factory 계약](FACTORY.md), [실행 계약](EXECUTION.md).
대조 코드 `227e3c9d1b8345f392a6dfe6aaba471290e44575`, 공식 자료 확인일 2026-11-05.

상태: **호출 책임과 비교 절차의 설계본**. 첫 Jev-only 진단용 transport와 J4-U/L 관측/host 비교는 구현했다.
후속 opt-in Factory 연결·미사용 전이·G1→G2→G3의 현재 계약은 [audit 연결](JEV_AUDIT_INTEGRATION.md)을 따른다.
J4-L/K의 opt-in Factory 연결은 구현했다. source fidelity/owner/core/fact 검사는 유지한다.
역할별 전체 라우터·O/K/C 전체 교체와 production 모델 배정은 미구현/미채택이다.
기본 경로는 기존 GPT-5.2 deployment와 split5를 유지한다. 실패한 split6를 승인하지 않는다.
이 문서는 기존 source S1/S2 교체나 전체 파이프라인 재작성을 채택하지 않는다.
역할 하나가 반드시 모델 요청 하나를 뜻하지 않는다. 같은 원문을 읽더라도 다른 판단은 별도로 구별한다.

## D-01. 현재 호출과 변경할 경계

기본 [Factory 실행기](../../experiments/openrouter_factory_pipeline.py)는 `plan.deployment` 하나를
추출·의미 판정·runtime에 사용한다. 새 opt-in은 `argument_audit_protocol`과 `decisions_deployment`를 고정해
전제 관측만 별도 typed 경로로 보낸다. 전체 role router를 구현한 것은 아니다. [PipelineWork](../../src/commentscope/factory/pipeline_work.py)의
stage 문자열은 작업 이름이며 모델 역할별 라우팅을 구현하지 않는다.
[제품 Broker](../../tools/serve_mvp.py)도 비교·대화·성찰을 한 deployment로 전달한다.
embedding과 사실 NLI는 별도 로컬 부품이다. bundle의 `model`은 **사실 classifier identity**이므로
이를 생성 모델 이름이나 모든 모델의 공통 이름으로 덮어쓰지 않는다.

합성12개 G1의 완료 영수증을 새 추론 없이 집계했다. 해당 실행의 Python source hash는 `e297b2f`와 일치한다.
현재 대조 코드 `227e3c9`에서 새 G1을 실행한 결과가 아니다. 실패한 실행의 비용 기준선이며 서비스 단가가 아니다.
15개 후보 중 Agent1개/3응답으로 G1 품질은 실패했다. 실제24/96/999개 완료 비용으로 일반화하지 않는다.

| 현재 호출군 | 유료 호출 | 실청구 USD | 주요 stage |
| --- | ---: | ---: | --- |
| 원문 제안 생성 | 12 | 0.05022675 | extract |
| 원문/후보 문맥 관측 | 34 | 0.05731250 | source-context, source-world, candidate-world |
| 후보 표현·관계·집계 전 검토 | 142 | 0.42590590 | nomination-raw, raw-candidate-route, raw-own-evidence, equivalence, qualification-*, assertion-counterexample, membership-initial/expanded-raw |
| core 유형·범위와 재검토 | 4 | 0.00693175 | core, core-fidelity |
| 출처별 논거·귀속·검토 | 58 | 0.20858390 | argument-node-metadata, argument-position-alignment, argument-owner, argument-audit |
| Agent 실제 응답 | 3 | 0.01041425 | runtime |
| 합계 | 253 | 0.75937505 | 로컬 embedding2개는 유료 호출에서 제외 |

이 실행의 `argument-dependencies` 원격 호출은0이었다. 일반 입력에서도0회라는 뜻은 아니다.
`argument-audit`만24회/$0.12701290이었다. 우선 수정 범위는 이 논거 검토의 입력·출력과 host 비교다.
다른142개 관계 판정까지 한 번에 Jev로 교체하지 않는다.

## D-02. 논리 계층과 책임

아래 ID는 새 호출 registry의 설계 ID다. 현재 실행기가 지원하는 플래그나 새 API는 아니다.
모든 계층은 source/target/contract hash를 유지하고 `unassessed`와 `uncertain`을 실패·반대로 바꾸지 않는다.

| ID / 책임 | 필요한 입력 | 출력·host 확인 | 배정 후보 / 금지한 승격 |
| --- | --- | --- | --- |
| H0 원문 등록 | snapshot·원문·부모·기한 | canonical ID, hash, 정확한 구간, 중복 | 코드. 원문 변경·부모를 별도 지지로 집계 금지 |
| R0 검색 | 등록 원문/후보·고정 embedding | 유사한 후보 ID·미검색 목록 | 기존 embedding. 유사도를 지지·동치로 승인 금지 |
| GEN-1 명제 제안 | 원문 전체·부모 참조·원문 구간 ID | 명제·필수 조건·근거·complete/partial/unresolved | 기존 생성 LLM. source 단위 제안이며 군집 합격 아님 |
| J1 원문 관측 | 원문·정확한 대상 구간·자기 입장 | fact/value/prediction/uncertain, 귀속·기능·세계·범위 | GPT baseline; Jev는 논거 진단 후 별도 비교. 이전 유형을 정답으로 입력하지 않음 |
| J2 후보 표현 | 최종 후보 본문·고정 구간, 계약상 필요한 origin 참조 | 유형·세계·조건·필수 상세·self-contained | 기존 판정 baseline. origin에서 새 세계·이유를 후보에 전파하거나 지지/사실 참을 승인하지 않음 |
| J3 의미 관계 | 두 실제 주장 또는 원문 전체+최종 주장 | 방향별 동치/포함/반대/지지/조건부/불확실과 근거 | baseline 유지. 검색 점수·제안 작성자의 자기 승인으로 대체 금지 |
| GEN-2 논거 제안 | 지지 원문·해당 작성자 입장·지원한 후보 | 개인 이유·조건·사실 전제·소유자·의존 제안 | 기존 경로. 이유를 모든 군집 구성원에게 전파 금지 |
| J4 논거 검토 | D-03의 과제별 원문·대상·구간 후보 | 관측한 유형/귀속/관계, 누락/불확실 상태 | **첫 Jev 비교 범위**. 모델의 단일 yes를 Agent 자격으로 승격 금지 |
| F0 근거 기반 사실 검사 | 동결 claim·선택한 외부 근거·기한 | supported/refuted/conflicting/insufficient | 기존 고정 NLI. Jev의 원문 함의를 외부 사실 검증으로 대체 금지 |
| H1 Agent 조립 | 검토된 지지·논거·의존 closure·사실 상태 | 허용 claim/출처/보류·bundle | 코드. 미검증 필수 전제 삭제·사실의 가치 재분류로 Agent 구제 금지 |
| GEN-3 제품 응답 | 자기 bundle·질문/의견·해당 이력 | claim/message 참조를 가진 비교·대화·성찰 | 기존 생성 LLM. Jev에 자유 문장·Agent 성격 생성 맡기지 않음 |
| H2 실행/제품 제어 | plan·room·job·장부·실행 기한 | 다음 단계·중복 방지·중단·저장/게시 | 코드. 모델이 예산·승인·발화 수를 변경할 수 없음 |

기존 F-02의 S1/S2·C1·E1/E2·M1/M2·A1/A2는 **통합 후보 계약**이고 위 계층은 판단 책임이다.
J1이 모든 기존 관측을 대체하거나 J4가 새 A1/A2 전체 교체를 뜻하지 않는다.
이번 첫 구현은 기존 `argument-audit`의 선택적 대체 경계에 한정한다.

## D-03. 논거 검토의 세부 계약

### 문제와 의미 정의

관측 실패는 두 종류다. 정상 가치 이유가 dependency=no로 거부돼 Agent 전체가 보류됐고,
명시 계약 후보는 정상 이유를 승인했지만 필요한 사실 전제의 누락도 승인했다.
설명 문구 추가만으로 해결됐다고 판단하지 않는다. [실패 기록](FACTORY_DELIVERY.md)을 유지한다.

- `personal_ground`: 이 작성자가 이 입장을 택한 이유. 사실·가치·예측 모두 가능하다.
- `local_factual_prerequisite`: 이 원문 논거/추론 자체가 성립하는 데 필요한 같은 작성자의 사실 전제.
- `core_factual_prerequisite`: 공통 core 주장 자체가 요구하는 사실 전제. 개인 이유의 합집합이 아니다.
- `essential_condition`: 작성자가 입장을 적용하는 조건. 조건의 존재와 조건이 현실에서 참인지는 별개다.
- parent/reference/quotation: 해석 문맥이다. 다른 작성자의 사실·이유를 자기 전제로 이동시키지 않는다.

### 과제별 허용 입력

| 과제 ID | 반드시 읽을 대상 | 관측과 host의 비교 |
| --- | --- | --- |
| J4-U 유형·귀속·기능 | 원문 전체, 대상 literal unit, 고정 OWNER_POSITION | 이전 kind/role을 숨기고 실제 관측값을 받는다. 선언값과 일치 여부는 host가 계산 |
| J4-O 입장 연결 | 원문 문맥, OWNER_POSITION, 실제 후보 주장 본문 | 같은 입장/다른 입장/불확실, 조건·양태·세계 보존. 기존 owner 검사와 대체 관계를 명시 |
| J4-L 원문 내부 전제 | 원문 전체, 대상 unit, 같은 원문의 premise 구간 후보 | 단순 fidelity 대신 관측한 전제 관계를 받는다. A1의 requires는 blind 관측 입력에서 숨김 |
| J4-K core 필수 전제 | 원문 전체, 실제 core 본문·조건, 해당 source의 unit 후보 | source 개인 이유와 core 필수 사실 관계를 각각 관측. core 본문 없이 평가할 수 없음 |
| J4-C 누락·완전성 | 원문 전체, 모든 literal unit과 원문 구간 목록 | 중요한 이유/조건/사실이 표현되지 않았는지, 참조 미해결 여부를 관측. core 관계를 요구하면 그 본문도 제공 |

현행 split5는 `LINK_TARGETS`를 source 관측에서 제거하면서 `core_requires_for`의 fidelity를 요구한다.
원문 유형 판단과 후보 연결을 분리한 의도는 유지하되, core 본문이 필요한 J4-K를 source-only 검사에 맡기지 않는다.
후보 본문을 원문 유형의 정답 힌트로 전파하지 않는다. 새 adapter에서 J4-U/L과 J4-O/K의 논리 입력을 분리한다.
이 분리는 추가 온라인 감사 호출을 자동으로 붙이는 지시가 아니다. 대체할 기존 호출과 실제 요청 수를 먼저 고정한다.

### 관계 관측과 최종 판단

host가 같은 원문의 unit ID와 evidence 구간을 후보로 고정한다. 관측의 정규화 형식은 다음이다.

```text
task_id, decision_id, source_hash, target_hash
edge = (target_unit_or_core_id, premise_unit_id,
        relation: necessary_fact | personal_ground | condition | none | uncertain)
coverage = complete | omitted_content | unresolved
status = assessed | uncertain | unassessed
```

이 형식은 내부 설계이며 Jev가 새 문자열·근거·ID를 생성한다는 뜻이 아니다.
Jev는 고정한 unit pair의 `choice` 또는 개별 명제의 `noul`로 관계를 선택하고 host가 ID와 원문 구간을 복원한다.
Jev가 제공하지 않는 설명문을 모델의 rationale로 만들지 않는다. host guard/basis 코드와 raw 선택·확률을 구별한다.
생성 LLM 비교군도 동일 관계/정의를 JSON으로 반환한다. 기대 답·이전 모델 답·이전 requires는 두 입력에서 숨긴다.
단일 `dependency_fidelity=yes`는 관측한 관계가 선언과 일치한다는 증거를 대신하지 않는다.

DC-02/03/04처럼 원문·대상은 같고 선언한 edge만 바뀌면, blind 관측의 입력도 같아야 한다.
동일 plan/decision/model의 실제 관측1개를 공유하고 host가 정상·누락·오연결 선언을 각각 비교한다.
`observation_request_hash`와 `declaration_hash` 및 결합한 `verdict_hash`는 따로 남긴다.
관측 요청에는 평가 case ID·기대값·변형 requires를 넣지 않는다. host 평가 ID를 provider task로 복제해 중복 과금하지 않는다.
세 선언의 결과는 host 비교3건이며 독립 모델 관측3건으로 정확도를 집계하지 않는다.
다른 원문/대상·언어·조건의 미사용 전이로 의미 관측 자체가 맞는지도 별도 확인한다.

host는 아래를 검사한 뒤 기존 audit verdict로 결합한다.

1. 요청한 모든 task/pair에 정확히1개 결과, 알 수 없는 ID·중복·다른 source의 구간 없음.
2. 관측한 necessary_fact 집합과 선언한 requires/core_requires_for의 방향·범위 일치.
3. 해당 premise의 독립 유형·귀속 관측, literal 근거·조건과 의존 DAG의 무결성.
4. 요구된 pair 또는 중요한 원문 구간이 미평가/누락이면 빈 전제 목록을 승인하지 않음.
5. source fidelity, owner 비교, coverage, 주요 사실·Agent 승인 규칙을 모두 유지.

빈 사실 전제가 허용되는 정상 가치 이유도 그대로 검증한다. 모든 because를 필수 사실로 바꾸지 않는다.
모델이 빈 관계 집합을 잘못 관측하는 의미 오류까지 코드만으로 알아낼 수 있는 것은 아니다.
구조 검사와 실제 정상/부정 비교를 구별하며 현재의 Agent 전체 보류 규칙을 이번 설계로 완화하지 않는다.

## D-04. 모델 배정과 실행 계획

| role key | 현재 상태 | 비교할 후보 | 운용 조건 |
| --- | --- | --- | --- |
| source_generator | GPT-5.2 단일 deployment 사용 | 이번 변경에서 추가하지 않음 | 실제 plan의 provider/가격/출력·reasoning 설정 보존 |
| source_observer | 같은 GPT-5.2 사용 | 이번 첫 비교에서는 추가하지 않음 | 논거 component 이후 개별 과제별로 판단 |
| candidate_observer | 같은 GPT-5.2 사용 | 이번 첫 비교에서는 추가하지 않음 | 후보 단독 관측이며 source 지지를 승인하지 않음 |
| relation_judge | 같은 GPT-5.2 사용 | J4 이후 별도 결정 | 동치/지지의 모든 기존 검토를 일괄 Jev 교체하지 않음 |
| argument_proposer | 같은 GPT-5.2의 metadata/alignment/dependency 제안 | 이번 첫 비교에서는 추가하지 않음 | 검토에 이전 제안 유형·관계의 정답을 누설하지 않음 |
| argument_judge | split5/GPT-5.2, 현재 G1 미통과 | `typesafe/jev-1.14`와 같은 질문의 GPT 비교군 | 첫 비교는 J4-U/L, O/K/C도 입력 경계를 명시하고 기존 기준과 함께 검증 |
| fact_checker | 고정 local evidence NLI | 이번 변경에서 추가하지 않음 | 기존 model/revision/weights/runtime hash와 fact benchmark 유지 |
| interaction_generator | 같은 GPT-5.2로 제품 개발 확인 | 이번 변경에서 추가하지 않음 | 자기 bundle·사용자 데이터 경계 유지 |
| retrieval / host | 고정 embedding / 코드 | 없음 | semantic approval 권한 없음 |

GPT-5.2는 품질 합격 모델로 확정한 것이 아니라 현재 실행의 비교 기준이다.
Jev 채택 전 기본 역할 값은 바뀌지 않는다. `latest` alias나 provider 자동 변경으로 비교 조건을 바꾸지 않는다.
상용 Jev와 [과거 로컬 OpenJev2B 비교](../OPENJEV_COMPARISON.md)는 서로 다른 모델·실험이다.

현재 동결 baseline의 구체적인 값은 다음과 같다. 이는 과거 plan의 설정이며 최신 판매 가격이나 새 실행 권한이 아니다.

```text
transport_version = openrouter-chat-completions-0.1
model = openai/gpt-5.2
provider.only = [openai]
context = 400000
call_seconds = 180
temperature = null
reasoning.effort = low
reasoning_output_tokens = 1024
schema_policy = openai-strict-schema-20261104-v1
provider.max_price = {prompt: 1.75, completion: 14, request: 0}
```

Jev 후보의 model은 `typesafe/jev-1.14`, provider는 TypeSafe, transport는 Decisions로 한정한다.
본문 가격표와 실제 endpoint metadata를 함께 확인한다. 미확정 timeout·질문 한도·유효 문맥·확률 정책을
임의 기본값으로 채워 실행하지 않는다. 역할별 배정은 이 두 profile 중 무엇이 채택됐는지 명시해야 한다.

첫 registry의 대상은 현재의 `free/raw` 경로다. 현행 stage를 아래처럼 등록하고 다른 mode는 명시적 계약을 추가하기 전 새 router에서 실행하지 않는다.
기존 mode·plan의 과거 재생 경로는 유지한다.

| 현행 stage | decision / role |
| --- | --- |
| extract, extract-additional | GEN-1 / source_generator |
| source-context, source-world | J1 / source_observer |
| candidate-world, raw-candidate-route, qualification-inventory, core, core-fidelity | J2 / candidate_observer |
| nomination-raw, membership-initial-raw, membership-expanded-raw, raw-own-evidence | J3 지지/긍정 검토 / relation_judge |
| equivalence, qualification-detail, qualification-ownership, assertion-counterexample | J3 방향별 동치/범위 검토 / relation_judge |
| argument-node-metadata, argument-position-alignment, argument-dependencies | GEN-2 유형/입장/전제 제안 / argument_proposer |
| argument-owner | J4-O / argument_judge |
| argument-audit | J4-U/L/K/C의 구체적인 task 분기 / argument_judge |
| embed-sources, embed-candidates / facts-* | R0 / F0 로컬 고정 부품 |
| runtime, product-room, product-legacy, product-comparison, product-reflection | GEN-3 / interaction_generator |

한 stage가 여러 판단을 담으면 task별 decision ID를 새 adapter가 명시한다. 이름만 등록했다고 모든 출력이 Jev와 호환되는 것은 아니다.
문장·새 구간·반례를 생성하는 schema는 생성 능력이 있는 baseline에 남긴다. 고정 선택지로 변환한 J4 과제만 첫 Jev 비교에 허용한다.

새 역할별 실행 계획에는 아래 필드가 필요하다. 이는 기존 `plan.json`에 이미 지원되는 schema가 아니다.

```text
plan: spec_version, design_version, code_hashes, snapshot/evidence hashes,
      spend_scope_id, shared_policy_hash, deadline, execution_authorization,
      mode=baseline|component_compare|qualified_run, adoption_status
deployments[deployment_id]: transport, model/version, allowed_provider,
      context_and_question_limits, pricing_bounds, schema/capability,
      reasoning/output_limits_if_applicable, timeout, retry_policy
routes[decision_id]: logical_input_contract, deployment_id, task_limits,
      question/option/schema_versions, threshold_policy_hash,
      replacement_stage_ids, failure_policy, fallback=null
call: decision_id, stage_id, task_aliases, logical_input_hash,
      effective_wire_request_hash, deployment_hash, plan_hash,
      normalized_result_hash, raw_receipt, usage/cost/settlement
```

route는 각 decision ID를 정확히 지정한다. stage 문자열의 일부나 프롬프트 내용으로 모델을 추측하지 않는다.
등록되지 않은 stage·허용 기능이 다른 transport·미채택 배정·입력 부족은 dispatch 전에 거부한다.
hash가 다른 배정·schema·질문·선택지 순서·threshold의 완료 결과를 기존 checkpoint로 재사용하지 않는다.
과거 단일 deployment 계획은 기존 validator로 읽고 새 registry 계획은 별도 버전으로 검증한다.
기존 bundle의 사실 classifier identity는 유지하고 생성/판정 모델 provenance는 별도로 기록한다.

## D-05. Jev transport와 확률 정책

OpenRouter의 Jev는 [Decisions API](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request)의
`POST /api/alpha/decisions`에서 `model/state/questions`를 받는다.
`/api/v1/systemone`도 같은 OpenRouter 계정으로 과금되지만 첫 후보 adapter는 Decisions 한 경로로 고정한다.
[공식 연동 안내](https://openrouter.ai/docs/guides/community/jev)에 따라 TypeSafe 별도 계정을 요구하지 않는다.
현재 Chat Completions client에 모델명만 바꿔 전달하는 방식은 지원하지 않는다.

첫 adapter는 text-only, Choice/Noul, 고정 provider/버전만 지원한다. Box·이미지·임의 Score는 범위 밖이다.
질문은 한 의미 관계씩 분리하고 요청 수와 논리 질문 수를 각각 기록한다.
같은 원문을 공유하는 질문을 묶을 수 있지만 원문이나 필수 문맥을 잘라 가격/문맥에 맞추지 않는다.
필요한 local pair를 줄이면 제외 pair의 `unassessed`를 보존하고 전제 없음으로 승인하지 않는다.
원문 내 unit 수/질문 수/질문 byte·token/최대 물리 요청 수는 비교 plan에 고정한다.
첫 개발 profile은 동시성1·자동재시도0·fallback0, 기존4통제만 대상으로 한다.
한 통제당 최대 baseline1회+Jev1회, 전체 최대8개 물리 요청이다. 같은 원문과 과제 안의 원자 질문만 함께 보낼 수 있다.
동일 blind 관측은 위 규칙으로 재사용한다. 고정 입력의 고유 요청 수를 prepare에서 계산하므로 최대8회가 실제8회 청구를 뜻하지 않는다.
baseline의180초와 Jev의유한 timeout, question 수·출력 한도·문맥 제한은 adapter 측정 후 plan에 수치로 고정하며 미정이면 실행하지 않는다.

확률 처리 정책:

- `choice`의 선택값·옵션별 확률을 저장한다. `noul`은 yes 확률이며 별도 confidence가 없을 수 있다.
- 유한한0~1, 정확한 option keys, 정규화 분포와 cardinality를 확인하고 이상 응답은 보류한다.
- Choice의 confidence는 분포의 집중도다. 정답 확률이나 독립 두 번째 증거로 간주하지 않는다.
- threshold는 모델·문제·선택지 집합별 버전이 필요하다. 기본 숫자0.5/0.8/0.9를 전 과제에 적용하지 않는다.
- 개발 세트에서 오승인/오거부/보류를 분리해 정책을 고정하고 미사용 전이 세트에 같은 정책을 적용한다.
- 오승인0과 정상 사례 보존을 함께 만족하는 정책이 없으면 비교 후보를 채택하지 않는다.
- 선택지 순서를 바꾼 사전 고정 비교에서 불안정하면 그 과제의 배정을 보류한다. 결과를 본 뒤 좋은 순서만 선택하지 않는다.

이는 [공식 confidence 설명](https://docs.typesafe.ai/confidence)의 구분을 프로젝트에 적용한 설계다.
한국어/영어는 각각 확인한다. TypeSafe는 영어 이외 언어의 정확도가 같지 않음을 [명시한다](https://docs.typesafe.ai/models).
수량·날짜·예산 계산은 코드에서 수행하고 의미 연결의 판정과 구별한다.

## D-06. 실패와 추가 호출 정책

| 상태 | 처리 | 자동 추가 유료 호출 |
| --- | --- | --- |
| required_input_missing / unknown_route | source/target·route 누락을 host 오류로 기록 | 0 |
| context_capacity / task_capacity | 원문·미처리 task를 보존하고 보류 | 0; 조용한 truncation 없음 |
| semantic_rejected | 관련 이유·전제·후보의 거부와 원문 근거 보존 | 0 |
| semantic_uncertain / unassessed | 보류, 지지 수/Agent 자격으로 승격하지 않음 | 0 |
| schema_invalid / missing_answer | raw 응답·known usage를 먼저 정산한 뒤 실패 | 0 |
| transport_unknown / missing_cost | 기존 보수 차감·reconciliation, 모든 새 paid dispatch 보류 | 0 |
| price/provider/version_changed | 처리한 청구 보존, 다음 호출 중단 | 0 |
| budget_exhausted / deadline_expired | 다음 요청 전에 중단, 완료 결과 열람만 허용 | 0 |
| complete_same_plan | 동일 bound checkpoint에서 읽기 | 0 |

Jev 저신뢰 결과를 자동 GPT 재검사로 보내는 fallback은 최초 배정에 없다.
나중에 필요하면 fallback 조건·최대1회·두 모델 합산 비용·별도 채택 증거를 plan에 고정해야 한다.
두 모델 중 하나가 yes이면 승인하는 OR 결합이나 같은 요청을 될 때까지 반복하는 수정 루프는 채택하지 않는다.
서로 다른 모델의 일치도 독립 사람 정답 검토를 대신하지 않는다.

## D-07. 비용·문맥·정산

모든 deployment는 기존 동일 공유 장부에서 예약→호출→raw 영수증→정산→결과 검증 순서를 따른다.
현재 `PaidBudget`은 chat payload와 `max_tokens`를 검증한다. Decisions를 지원한다고 간주해 우회 호출하지 않는다.
공통 예약·정산 책임을 보존하는 별도 typed envelope/adapter의 오프라인 검증이 선행돼야 한다.
한 물리 요청의 다중 질문은 장부에서 한 청구로 정산하고 각 논리 결과와 동일 영수증을 연결한다.
질문별 계산 비용은 분배 추정치로 구별하고 이를 합쳐 실제 청구를 중복 집계하지 않는다.

2026-11-05 [Jev 1.14 표시 가격](https://openrouter.ai/typesafe/jev-1.14)은 입력100만token당$0.042, 출력$0이다.
이는 조회 시점 참고값이다. 실제 실행 plan은 provider·request/tier/cache/image 등의 모든 해당 상한을 재확인한다.
입력 총2,000token/request×1,000request라면 해당 입력비용은$0.084다. 생성·다른 판정·fallback을 포함한 서비스 원가가 아니다.

```text
physical_call_reserve = full_billable_input_context * maximum_input_price
                     + bounded_output * maximum_output_price
                     + maximum_request_fee
comparison_upper_bound = sum(all scheduled physical_call_reserve)
actual_total = sum(unique settled receipt usage.cost)
```

단위 변환은 코드로 한다. 작은 예상 입력을 이유로 전체 문맥 예약이나 cache-write/장문 최대가격 보호를 낮추지 않는다.
[TypeSafe 기본 한도](https://docs.typesafe.ai/models)는 request64k/question32k token이며 long context는 별도 모드다.
OpenRouter catalog의262,144token 최대치와 기본값을 혼동하지 않는다. OpenRouter 경유의 실제 모드·한도·조건을
endpoint 설정과 동결 입력에 대해 확인하고, 불명확하면 paid prepare를 보류한다. 원문을 잘라 맞추지 않는다.

개발 비교 비용과 최초 영상 분석·재열람·질문·그룹·성찰의 서비스 비용을 따로 기록한다.
새 모델/역할/서버가 새$5를 받거나 과거 확정·보수 차감을 지우는 소유자가 될 수 없다.
이전7시간/$5 cycle은2026-11-05T03:15:51Z에만료됐고 GPT-5.2 deployment로 동결돼 있다.
과거 잔여액을 근거로 Jev 배정을 추가하거나 기한을 연장하지 않는다. 현재 유료 실행 보류를 유지한다.
새 실제 실행에는 구체적 코드·입력·deployment map·최악 예약액·예상 비용·기한과 해당 실행 권한이 필요하다.

## D-08. 정상·부정 사례와 채택 단계

다음은 작성된 계약 사례이며 모델 통과 결과가 아니다. 기존4통제의 입력·기대는 실패 후 변경하지 않는다.

| 사례 | 원문/선언의 차이 | 필요한 동작 |
| --- | --- | --- |
| DC-01 정상 가치 이유 | 안전이 중요해서 의무화 찬성, 사실 전제 없음 | 가치 이유 보존, 필수 사실을 발명하지 않음 |
| DC-02 정상 사실 연결 | 같은 원문의 사실에서 결론을 도출, 올바른 premise 연결 | 연결 관측 일치 |
| DC-03 누락 전제 | DC-02의 원문은 같고 필요한 requires만 비어 있음 | 누락을 발견해 보류/거부, 단일 yes로 통과 불가 |
| DC-04 잘못된 전제 | 다른 집단에 대한 사실을 연결 | 잘못된 edge 거부 |
| DC-05 이유 없는 입장 | 지지 입장만 존재 | 빈 이유 허용, 이유/전제 생성 금지 |
| DC-06 개인 사실 이유 | 한 작성자의 사정으로 정책 선호 | 자기 이유만 연결, 군집 전체 core의 필수 사실로 확대 금지 |
| DC-07 부모 이유 | 답글은 동의만, 사실/이유는 부모에 존재 | 원문 지지 해석과 이유 전이를 구분 |
| DC-08 인용·반대 | 타인의 찬성과 작성자의 반대 | 타인 입장을 자기 지지/전제로 승인 금지 |
| DC-09 필수 조건 | 특정 조건일 때만 찬성 | 조건을 유지, 조건의 현실 성립을 별도 사실로 발명 금지 |
| DC-10 미표현/불확실 전제 | 중요한 내용이 inventory에 없거나 유형이 미해결 | none/complete로 채우지 않고 보류 |
| DC-11 새 주제·한국어/영어 | 정상/부정 경계를 새 주제·언어로 옮김 | 같은 동결 정책으로 전이 확인 |
| DC-12 순서·중복·모델 변경 | 옵션 순서 변화/누락 결과/다른 deployment | 사전 동결 강건성 평가, 구조 실패 또는 새 계획 요구 |

구현/검증은 네 checkpoint로 나눈다.

1. **계약과 fixture, 비용0:** DC-01~04 원본 실패를 보존하고 나머지 사례의 입력·기대·원문 근거를 고정한다.
   개발/전이 분할과 threshold 선택 규칙을 모델 출력 전에 기록한다. 정답 라벨은 provider payload에 넣지 않는다.
2. **adapter·host 회귀, 비용0:** 명시적 decision route, mock Decisions 응답의 완전성/분포/ID,
   DAG·kind·core/개인 범위 비교, 공통 장부·checkpoint·기한·부분 실패를 검증한다.
   원래 split5 결과 재생과 모델 배정 변경 후 응답 재사용 거부도 유지한다.
3. **작은 실제 비교, 별도 동결 권한:** 먼저 기존4통제를 같은 질문 의미/원문/대상으로 비교한다.
   baseline도 계약이 바뀌면 새 응답이 필요하다. 실패한3개 과거 답을 새 baseline으로 재표시하지 않는다.
   같은 plan 안의 동일 blind 관측은 공유하되 서로 다른 선언과의 비교 결과를 구별하고, 물리 요청·고유 의미 관측·host 비교 건수를 따로 보고한다.
   baseline의 알려진 실패는 비교 결과로 보존한다. 후보의 첫 중대 오승인에서 후보 실행/확대를 중단하고 baseline 재시도로 구제하지 않는다.
   정상 오거부·부정 오승인·보류·실제 요청 수/비용·지연을 전부 보고한다.
   통과 후 고정 미사용 전이와 옵션 순서 사례를 평가한다. 결과를 보고 기대값/정책을 낮추지 않는다.
4. **fresh G1→실제 표본:** 선택한 role map 전체를 동결해12원문에서 모든 Agent·각3질문을 검토한다.
   같은 설정의 G2/G3/G4는 기존 r5로 진행한다. 혼합 재생·부분 비교·CI를 fresh gate로 승계하지 않는다.

각 checkpoint의 산출물이 다음의 입력이다. 문서 작성·mock 통과·작은 실제 비교·전체 MVP 완료를 구별한다.
Jev가 기준을 통과하지 못하면 기본 배정을 유지하고 실패와 비용을 보존한다.
새 전체 역할 구조/모델을 반복 제안하는 대신 해당 component의 입력·관측 실패를 분석한다.

## D-09. 구현 위치와 아직 열린 결정

| 변경 위치 | 첫 구현 범위 | 유지할 기존 책임 |
| --- | --- | --- |
| argument_observations / source_arguments | J4별 허용 입력·관측 출력·기존 audit adapter | split5 재생, source/owner/coverage 거부와 보류 |
| pipeline_stages / pipeline_work | 등록된 decision ID와 대체 stage binding | 기존 처리 scope·검색/병합·원문·후보 보존 |
| providers / checkpoint / budget | Decisions transport와 공통 청구 envelope, route provenance | 공유 장부·기한·가격·자원·실패/보수 차감 |
| 실행 prepare/validate | 역할별 deployment map을 새 버전 opt-in으로 동결 | 과거 단일 모델 plan 불변, 기존 기준 검증 |
| product Broker / bundle | 후속 role map 연결과 모델별 provenance | NLI classifier identity, 자기 근거·Controller·사용자 데이터 경계 |

첫 구현은 논거 component의 비용0 계약/adapter다. 제품 Broker나 다른 전체 판정기로 확대하지 않는다.
열린 값은 Jev의 과제별 정확도, 실제 gateway 문맥 조건, threshold 수치, 물리 묶음 크기,
역할별 실제 완료 비용과 서비스 단가다. 값이 확정되기 전 production 배정이나 대량 유료 실행으로 승격하지 않는다.
DEC-007은 `proposed`이며 TASK-016은 문서/참조 검증 범위다. TASK-005는 실제 품질 완료까지 계속 미완료다.


## D-10. 사용자 승인 첫 Jev 진단의 실행 범위

사용자가 첫 Jev 검증을 실제 실행하라고 요청했다. 이번 범위는 **Jev 단독 개발 진단**이다.
D-08의 GPT paired 비교·전이·전체 G1이나 production 배정의 완료가 아니다.
기존4통제의원문·대상·기대를유지하고,정상가치이유와사실추론의고유blind관측최대2개만실행한다.
동일한사실관측을정상/누락/오연결선언에각각host비교한다.유료GPTbaseline을추가하지않는다.
첫진단은고정선택지의argmax·uncertain을개발기대와비교하고모든확률을보존한다.
calibration/production threshold는미설정이므로Agent승인에사용하지않는다.
후보오승인/스키마·과금불명에서새유료호출을중단하며자동재시도/fallback은0이다.

이번별도trial은최대신규$0.10,실제prepare후15분·물리호출2개·각30초로제한한다.
기존cycle파일/기한/deployment를수정하지않고원래SHA의**동일통화소유자·총$5상한·기존차감**을공유한다.
새사용자요청은이trial의시간/모델만허용하며새$5나전체실행권한을만들지않는다.
별도동결authorization/plan에원래owner,시작차감,신규한도,scope/deployment/입력/코드hash와종료시각을기록한다.
전체문맥×가격의최악예약합이신규한도·원래scope잔여·공유계정/key잔액모두에들어야한다.
typed transport도기존SpendLedger·bounded worker·checkpoint·host resource guard를사용하고,raw영수증정산후의미를검증한다.
기존chat worker는기본동작을유지하고명시적typed request만rawpayload를provider에전달한다.
키는worker환경에서만읽고plan/출력에저장하지않는다.

## D-11. 첫 실제 진단 결과와 한계

`experiments.jev_argument_controls`에서 고정2개 원문 관측을 실제 TypeSafe `jev-1.14-20261014`로 실행했다.
단독 개발 진단이며 GPT paired 비교·미사용 전이·한국어·O/K/C·Factory/Agent 통합 결과가 아니다.

| 통제 | 관측/host 결과 | 기대와 일치 |
| --- | --- | --- |
| DC-01 정상 가치 이유 | value/reason, 필요한 사실 전제 없음 → 유지 | 예 |
| DC-02 정상 사실 연결 | fact/position, 필요한 사실 전제 U1 → 유지 | 예 |
| DC-03 전제 누락 | 같은 관측 U1과 빈 선언 비교 → missing_factual_prerequisite 차단 | 예 |
| DC-04 다른 집단의 사실 연결 | U1 관측과 U2 선언 비교 → 누락/오연결 차단 | 예 |

실제 모델 요청2개, 고유 원문 관측2개, Choice 질문17개, 선언 비교4개다.
단일 사실 관측을3선언에 공유했으므로 독립적인 의미 사례4개에서100%라고 보고하지 않는다.
첫 요청 입력1,467token/$0.000061614, 둘째2,040token/$0.000085680, 총$0.000147294가 청구됐다.
나중에 조회한 API 사용액 증분도 같은 금액과 일치했다. 최악 예약합$0.022020096, 신규한도$0.10 이내다.
완료 결과 재열람에서 ledger 호출 수·차감이 동일해 추가 요청/비용0임을 확인했다. 예약/미확정0이다.

이는 **Jev+새 관측 계약+host 비교**의 개발 사례 확인이다. 과거 GPT split6와 입력/출력 계약이 다르므로
Jev 모델만의 정확도/절감 효과로 분리하지 않는다. 확률 calibration/production threshold는 설정하지 않았다.
기본 split5·GPT Factory·기존 Agent 보류 규칙과 r5는 유지한다. 새 G1 합격이나 999개 원가를 주장하지 않는다.
다음은 기존 audit adapter의 오프라인 연결과 미사용 전이/선택지 순서의 동결 비교다.
