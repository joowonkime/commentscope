# 데이터 계약 v0.1

이 문서는 wire format과 검증 규칙의 구현 명세입니다. 2단계에서 DatasetSnapshot/Comment 검증과 normalization을 구현했습니다.
Eligibility 이후의 전체 Factory 계약과 RunManifest는 후속 구현 명세입니다.
2026-10-10부터 추출 실험 전용 `claims-0.2` JSON Schema/validator는 `src/commentscope/contracts/claims.py`에 제공합니다.
기존 snapshot-0.1이나 아래 전체 Factory 명세를 자동으로 0.2로 바꾸는 것은 아닙니다.
합성 예시는 [snapshot](examples/synthetic-snapshot.json)과 [Factory trace](examples/synthetic-factory-trace.json)에 있습니다.

## 후보 검색과 방향성 검사 진단 계약

`candidate-search-0.1`은 동일 claim/vector의 same_mode, cross_mode, hybrid 검색을 분리합니다.
hybrid는 embedding8+추가 lexical4, source 중복 제외, 유형 제한 없음이며 의미 승인 결과가 아닙니다.
입력은 이 진단에서512claims 이하입니다. 실제 실행은 기존64개 댓글의123claims를 재사용합니다.

`grounded-core-0.2`의 verify는 원문과 target의 digest, NLI 원시 점수, relational audit,
차단 사유와 allowed를 반환합니다. NLI threshold0.8과 scope/time/modality/conditions/polarity/presuppositions
전부 preserved 및 support=supported가 필요합니다. evidence_quote는 원문의 정확한 substring이어야 합니다.
인용 검사는 구조 검증이며 모델의 의미 판정을 독립적으로 보증하지 않습니다.
0.1 실패를 보존하고0.2에 `qualification-witnesses-0.1`을 추가했습니다. 영어 future/present-progressive/past
명시 표지의 위치, 조건 operator/antecedent 원문을 저장합니다. 조건 operator 목록 변화나 제한된 단순 문장의
명시 시점 변화는 모델 통과와 무관하게 차단합니다. 표지를 못 찾았다는 것은 의미 보존 승인이 아닙니다.

discover는 원문→추출 claim 검사를 먼저 수행하고, 제안1개+입력 claim2개를 고정 비교합니다.
각 core를 원문 및 claim에 별도로 검증하고 첫 통과 후보를 선택합니다. 제안 우선이지 최단 문자열 우선이 아닙니다.
core_groups의 cross_mode=true는 `common-core-assembly-0.2`로 기록하며 기존 false 경로는0.1을 유지합니다.
기본 Factory/artifact loader에는 이 진단을 연결하지 않습니다.

`grounded-core-diagnostic-0.2`는 입력·fixture·코드·모델·프롬프트 hash, 실행 정책,
quality_gate_passed=false를 저장합니다. probe는 exact target 평가와 관점 연결 평가를 분리하고,
integration은 최소3source/결정64개 한도로만 조립합니다. verify는 cache miss에 RuntimeError를 내며
모델 호출 없이 고정 입력과 결과를 재계산합니다. 완료 artifact를 덮어쓰지 않습니다.
`--reuse-run`은 원시 request/result의 digest와 입력/모델/runtime/prompt/추론 코드의 일치를 검증하며
host 판정 결과는 복사하지 않습니다. reuse origin manifest hash가 실행 설정에 포함됩니다.

`grounded-core-new-sample-0.1`은 이전64개와 full1000 배정 source를 제외한 고정 hash-order12개에서
source-only 추출과 원문 충실성 검사를 수행합니다. 평가 계획의 source ID는 selection과 대조하지만
기대 판정은 inference payload에 포함하지 않습니다. 원문/추출/판정/코드 hash를 보존하고 readonly replay합니다.
별도 표본이지 독립 gold나 완전히 미사용 corpus는 아닙니다. 이 artifact는 service 입력이나 profile이 아닙니다.

## 추출 실험 계약 claims-0.2 (2026-10-10)

로컬 모델의 출력은 `{eligibility, claims}`입니다. 각 claim의 필수 키:

| 필드 | 의미 |
| --- | --- |
| `issue`, `claim` | 구체적인 쟁점과 원문에 충실한 주장. 개인/가능성/조건을 문장에도 보존 |
| `quote` | 해당 주장을 지지하는 target 댓글의 정확한 substring |
| `stance_target`, `stance` | 평가 대상과 그에 대한 입장. 대안 정책 지지를 UBI 지지로 자동 해석하지 않음 |
| `reason`, `reason_quote` | 별도로 명시된 이유와 원문 근거; 없으면 둘 다 null |
| `condition`, `condition_quote` | 명시된 if/when/only-if 조건과 근거; 없으면 둘 다 null |
| `scope` | personal / general / unclear |
| `modality` | asserted / possible / conditional / unclear |

- `argument_or_experience`만 비어 있지 않은 claims를 허용. 나머지는 빈 배열. v0.2 실험은 최대6개; 장문/과다 주장 처리는 전체 파이프라인에서 별도 설계 필요.
- support/oppose/conditional/mixed에는 stance_target 필수. 명시적 정책 선호가 없는 기술적 주장/경험은 neutral과 null target을 기본으로 함.
- 모델은 source ID를 출력하지 않음. 호스트의 `bind_source()`가 실제 target ID와 schema/source/claim 기반 deterministic claim ID를 부여.
- claim ID는 실험용 내용 기반 ID이며 전체 Factory의 run-scoped ID 구현을 대체하지 않음. 동일 claim 표현이 달라지면 ID도 달라짐.
- 구조·enum·target substring·reason/condition 쌍·eligibility 불변조건 실패는 오류 목록으로 반환. 원시 모델 결과를 조용히 고치거나 실패를 0 claims로 대체하지 않음.
- 검증 성공은 `semantic_review_status=pending`. quote가 존재해도 claim/이유/조건을 실제로 함의하는지, 누락된 주장이 없는지는 별도 검수.
- 초기 probe-0.1 결과는 그대로 보관. 0.2로 재사용하려면 원본을 새 prompt/schema로 재추출하며 무표시 변환하지 않음.
- 전체 Factory envelope, eligibility 사유/언어/confidence, 재시도·문맥 해석은 아직 완성된 계약 구현이 아님.

## 소표본 후보/검수 artifact claim-candidates-0.1 (2026-10-11)

- `factory/claim_clusters.py`가 claims-0.2 추출 JSON과 snapshot의 hash·target·parent 문맥·종료 상태를 재검증합니다. 기존 `bound_claims`/계약 성공 표시는 신뢰하지 않습니다.
- 이 형식은 전체 Factory run 계약을 대체하지 않는 개발 진단용입니다. 최대 60개 선택 원문/300개 claim이며 source별 blocked/duplicate_alias/included를 모두 기록합니다.
- embedding input text/claim ID 순서/모델 revision/벡터, threshold, 후보 소속을 저장합니다. 후보마다 서로 다른 canonical source 수를 세고, 모든 입력 claim을 정확히 한 후보에 배정합니다.
- 같은 원문의 여러 claim이 다른 후보에 속할 수 있습니다. 지지 원문 수를 후보 사이에서 합산해 전체 사람 수처럼 해석하지 않습니다.
- `candidate_needs_review`는 unique sources >=3일 때의 후보 표시일 뿐 승인 아님. 작은 묶음은 `rare_unreviewed`로 보존합니다. 모든 결과의 accepted_perspectives는 0입니다.
- AI 검수 JSON은 `candidate_report_sha256`, `reviewer=assistant`, `human_approved=false`, `findings`를 요구합니다. 원문/모델 결과가 승인 권한을 갖지 않습니다.
- finding은 cluster_id, status, evidence_claim_ids를 가집니다. 상태는 propose_for_user_review/split_needed/reject/uncertain/rare. 전체 묶음 제안은 모든 member와 3개 이상 unique sources, common_claim을 요구합니다.
- 선택적 proposed_groups는 split_needed에서만 허용. 자식 ID·공통 주장·증거·상태를 기록하고 부모 claim 전체를 중복/누락 없이 나누어야 합니다. 자식 제안도 승인 아님. 이는 split의 검증 가능한 **제안**이며 실행된 lineage 변경은 아닙니다.
- 인용이 실제로 주장을 뒷받침하는지는 사람의 의미 검토 대상입니다. AI 검수 제안만으로 PerspectiveSpec이나 agent를 생성하지 않습니다.

## 대표 주장 실험: 미승인 draft (2026-10-11)

- `perspective-draft-0.1`의 groups는 members, common(text/evidence), details(kind/text/evidence)를 갖고, excluded는 member_id/reason을 갖습니다. 원문 내 인용·그룹 내 근거·전체 member의 정확히 한 번 배정을 검사합니다.
- `perspective-assignment-0.2` wire 형식은 assignments의 필수 member key마다 group_id/exclusion_reason을 요구합니다. groups는 group_id/common/details를 가지며 details는 kind/text/member_ids를 가집니다.
- v2에서 모델은 인용을 재작성하지 않습니다. `canonicalize`가 실제 target 전체를 연결하여 0.1 공통 형식으로 명시적으로 변환합니다. 사용하지 않는 group, group 누락, 그룹 밖 detail 인용, 제외 사유 누락은 오류입니다. raw와 canonical output을 따로 보존합니다.
- host의 bind가 실제 claim/source ID를 붙입니다. unique sources>=3이라도 needs_semantic_review이며 나머지는 rare_needs_review입니다. 두 경우 모두 accepted_perspectives=0.
- reasons/conditions/variations의 근거는 일부 source에만 해당할 수 있습니다. 공통 문장은 모든 배정 source의 지원이 필요하지만, 이 의미 요건은 문자열 validator로 보장되지 않습니다.
- `source-statement-audit-0.1`은 각 문장과 각 인용 source의 pair마다 verdict/reason을 요구합니다. 검사 누락·잘림·잘못된 응답은 audit_failed. 모두 supported여도 needs_human_review, 나머지는 revise_before_human_approval입니다. 이는 모델의 진단 추천이지 실제 사람의 승인 상태가 아닙니다.
- `source-statement-audit-pairwise-0.2`는 같은 verdict 계약을 사용하되 요청마다 정확히 한 pair와 해당 TARGET만 전달합니다. 다른 원문/문장·이전 판단·assistant 검수는 요청에 포함하지 않습니다.
- pairwise의 `statement-placeholder-0.1`은 `M`+숫자 ID만 나열한 문장(공백/일부 구두점 포함)을 `id_only_placeholder`로 차단합니다. 일반적인 의미 없음 판별기는 아니며 draft 생성 계약이나 batch에는 적용되지 않습니다.
- `pair_results`는 쌍별 raw/output/errors/seconds와 `verdict_origin=local_model|deterministic_lint`, `lint_errors`를 보존합니다. 규칙 차단은 unsupported/raw=null/모델 호출0이며, 모델이 판정했다고 표시하지 않습니다.
- 한 pair 실패 시 다른 pair 검사는 계속하되 전체 추천은 audit_failed입니다. 실패 pair를 성공 output에 채우지 않습니다. `model_calls`는 실패한 시도도 포함하며 `lint_blocked_pairs`와 구분합니다.
- 비교 결과는 동일 draft hash와 pair 집합 및 이전 verdict 누락 여부를 확인한 뒤 `previous_output`으로 따로 붙입니다. 비교 판단은 모델 입력이 아니며 변화 자체를 정확도 개선으로 해석하지 않습니다.
- 한 쌍씩 검사해도 의미 오판이 남으므로 후속 semantic review를 생략하지 않습니다. `human_approved=false`와 accepted_perspectives=0을 유지합니다.
- audit의 `--prompt-revision v1|v2`는 지시문만 선택합니다. `prompt_version`/`system_prompt`/`prompt_sha256`를 저장하고 pair payload, verdict schema, lint, 승인 권한은 유지합니다. 기본값은 v1입니다.
- `comparison_metadata_changes`는 이전/현재 mode, lint, model/revision, runtime, request settings, prompt hash의 차이를 기록합니다. 서버 설정의 독립 검증이나 정확도 보장이 아닙니다.
- draft의 `--revision v3`는 생성 prompt-0.3이며 wire 형식은 여전히 perspective-assignment-0.2입니다. v2와 동일 입력·스키마·validator·binding 사용; prompt revision을 wire 계약 변경으로 해석하지 않습니다. 기본 생성 revision은 v2입니다.

## 개발 전용 source-frame 진단 (0.1)

- `experiments/source_frame_probe.py`는 source-frame-diagnostic-0.1 artifact를 생성합니다. claims-0.2나 PerspectiveSpec의 교체 계약이 아닙니다.
- 모델 출력은 assertion_type(prediction/need/possible_benefit/description/question/mixed/unclear), certainty(asserted/hedged/unclear), reason_quote/condition_quote(null 또는 실제 TARGET 부분 문자열)뿐입니다. 원문/claim/source ID는 호스트가 연결합니다.
- 새 요청에는 TARGET 하나만 제공하고 과거 claim·그룹·평가 기대값은 주지 않습니다. 자유로운 대표 문장 생성은 하지 않습니다.
- 필드/enum/원문 인용/종료 상태 실패를 보존합니다. 성공도 semantic_review_status=pending, human_approved=false, accepted_perspectives=0. label이나 인용 일치로 자동 승인/분할하지 않습니다.
- 기존 embedding의 model/revision/claim 순서/입력 텍스트와 벡터 유효성을 재검증합니다. 같은 선택 subset의 원문 및 기존 claim 벡터를 0.25/0.35/0.45에서 비교하며 원래 전체 corpus의 군집을 대체하지 않습니다.
- 최대12개, source당1개 claim, 원문2,000자 제한. multi-claim 추출·문맥 해소·전체 corpus 평가가 아닌 bounded diagnostic입니다. 기존 snapshot 만료를 상속합니다.

## 원문 선택형 개발 artifact extractive-keypoints-0.1

- `factory/extractive_keypoints.py`의 별도 실험 계약이며 승인된 PerspectiveSpec이 아닙니다. snapshot/extraction/candidate SHA256과 expires_at을 상속하고 입력 출처/후보 partition을 재검증합니다.
- `anchors[member_id]`: source_member_id, source_comment_id, start=0, end, text. 호스트가 원문 전체에서 고정하며 모델이 변경하지 않습니다. 최대12개 source, source당1개 claim, 원문1..500자.
- 모델 출력은 정확히 `{relation: supports|contradicts|not_established|unclear}`. 추가 필드/불완전 생성/호출 실패는 errors 및 relation=null로 보존. 모델 판단 입력은 SOURCE, REPRESENTATIVE 두 원문뿐입니다.
- `pairs[source->anchor]`: source, anchor, relation, origin, raw, output, errors, seconds, human_approved=false. origin은 local_model 또는 identity_text_only이며 후자는 동일 원문 비교로 모델 호출하지 않습니다. 모든 N²쌍이 필요합니다.
- `assembly.groups`: id, anchor_id, representative, member_ids, unique_source_count, evidence_pair_ids, status=needs_human_review. 모든 member는 대표에 직접 supports를 가져야 하며 최소3개 서로 다른 source. 그룹 간 중복 없이, 미배정은 assembly.unassigned에 이유/지원 후보/실패 pair와 함께 남깁니다.
- accepted_perspectives=0, human_approved=false, independent_gold=false. 정확한 원문/출처와 관계 행렬을 저장해도 의미 정확도나 인간 승인을 뜻하지 않습니다. 실제 검수 의견은 결과 hash에 연결한 별도 비공개 artifact로 저장합니다.
- prompt 본문/hash, generation_schema, operator-supplied 모델/revision/runtime/요청 설정 및 pair checkpoint를 보존합니다. 기존 파일 덮어쓰기/자동 resume는 지원하지 않습니다.

## 로컬 관계 판정 비교 local-nli-comparison-0.1

- 기존 B 산출물의 snapshot/extraction/candidate hash, 원문/대표, 전체 pair matrix 및 재계산 assembly를 검증. 기존 원문/대표/배정 알고리즘이 바뀌면 거절합니다. snapshot 만료도 다시 확인합니다.
- 실행 전 manifest에 baseline/plan/synthetic suite/assembly code SHA256, expires_at, threshold=0.8을 저장. 공개 합성 suite와 비공개 실제 회귀 계획을 구분합니다. 기대 relation은 assistant 개발 기준이며 독립 gold가 아닙니다.
- NLI pair는 기존 source/anchor/relation/errors/origin 계약을 유지하되 origin=local_nli, raw=logits, scores={entailment,neutral,contradiction}, argmax_relation, input_tokens를 추가합니다. relation은 threshold 적용 결과이며 scores는 보정된 신뢰도가 아닙니다. 오류 시 relation=null.
- 평가 summary는 category별 total/matches/errors/supports/unclear/mismatch_ids를 따로 기록. 실패/보류를 정상 연결로 합산하지 않으며 동일 원문 pair는 의미 평가에서 제외. 실제 positive recall을 합성 사례 점수로 대체하지 않습니다.
- 출력 비교 JSON/HTML, 별도 NLI 재배정 JSON, 쌍별 checkpoint는 모두 원문 유래의 private artifact입니다. accepted_perspectives=0, human_approved=false, independent_gold=false. 모델 판단/검수 결과를 원문 수정이나 승인으로 변환하지 않습니다.

## 원문 계열 분류 source-facet-loop-0.1 / assistant-reviewed-source-facets-0.1

- 개발 한정 모델 출력: topic_match(boolean), assertion_type(need/prediction/possible_benefit/description/question/mixed/unclear), polarity(affirmed/negated/mixed/unclear), assertion_quote(exact substring|null). unclear 외에는 null 인용 금지. extra field/인용 변형/불완전 생성은 실패.
- polarity는 술어의 부정 여부이지 확신의 정도/정책 찬성이 아님. topic/type/polarity를 코드가 배정에 쓰지만 의미 정확성은 별도 검수가 필요. 모든 source는 원문 전체 source_cards 또는 명시적 unassigned로 보존하고 source/member 중복을 거절.
- group semantics=assertion_family_not_full_sentence_entailment. 계열별 공통 제목은 코드 label이고 생성된 완전한 공통 명제가 아님. 3개 이상은 proposal_needs_semantic_review, 미만은 rare_preserved. 주장별 이유·조건을 다른 source에 전파하지 않음.
- 검수 입력은 모델 출력 파일의 순서 있는 SHA256 배열에 연결. 모든 source에 정확히 한 entry(id/decision/reason_ko/reading_ko/cautions_ko)를 요구. confirm은 원래 계약 실패/숨은 수정을 허용하지 않음. correct는 topic/type/polarity만 명시적으로 바꾸고 호스트가 전체 원문 인용을 연결. abstain은 unclear로 보류.
- 검수 결과는 원래 model_result와 새 result(origin=assistant_review)를 같이 보존. raw model 평가 수치는 변경하지 않음. human_approved=false/independent_gold=false/accepted_perspectives=0. assistant 수정 후 자체 기대값 일치를 독립 정확도로 계산하지 않음.
- snapshot/hash/expiry/source 일치/중복 검증과 새 출력 경로를 사용. 실제 계획/판정/원문/HTML은 비공개 로컬 파일이며 원본 보관 만료 상속. 사람 승인된 PerspectiveSpec 계약을 대체하지 않음.

## 개발용 관점 에이전트 bundle / comparison (0.1)

- `development-perspective-bundle-0.1`은 정식 PerspectiveSpec이 아님. snapshot_sha256/reviewed_sha256/expires_at/dataset/agents/non_agents/limitations를 보존. source 원문·canonical source·검수 origin·assembly를 재검증하고 ask 때 bundle을 다시 계산해 전체 비교. build/ask 모두 명시적 --allow-unapproved 필요.
- profile은 agent_id/title/assertion_family/polarity/status=development_only_not_approved/evidence/constraints/human_approved=false. evidence는 evidence_id/source_comment_id/original_text/source_url/reviewer_reading_ko/cautions_ko/interpretation_origin/parent_context. 검수 해석은 원문 번역이나 새 증거가 아님. parent는 문맥만 제공하고 may_cite_as_support=false.
- `development-agent-comparison-0.1`: bundle/만료/hash/runtime/prompt/schema/code hash와 질문별rounds를 보존. 같은 질문을 각 AgentSession에 독립 전달하고 자기 state만 유지. 외부 source/다른 agent/희소·보류 source ID는 생성 스키마 및 validator에서 차단.
- 답변 grammar0.2: answerability grounded/partial은1..2개의{text,evidence_id} points, not_in_evidence는0개. text<=400자, missing_information<=240자(partial은비어있지않음). 질문은1..1000자, session<=6질문, 이전2회 자기대화만 전달. raw 답변/오류/시도/시간/usage는 보존.
- Auditor는 각 point와 해당 original 하나만 지지 근거로 검사하고 질문 관련성도 판단. supported/revise/unclear 및 짧은 reason을 반환. 모델 지지 판정은 독립 검증 아님. 구조 실패·모호·거절 시 최대1회 재생성, 최종 실패는 abstain 및 points=[]. 통과 상태는 model_audit_passed_development_only이며 human_approved/semantic_guarantee=false.
- 표시된 point에 호스트가 citation 전체를 연결. 실패 초안은 HTML 답변/후속 history에서 제외. 미검사 missing_information도 JSON에만 보관하고 UI에는 호스트의 일반적 부분 답변 표시만 사용. citation URL은 YouTube HTTPS allowlist, 모든 HTML 내용 escape.
- 모든 실행은 새 출력 경로/checkpoint로 저장. 실제 댓글 유래 artifact는 Git 제외/expiry 상속. 승인 관점0과 실행 개발 agent 수를 구분. 모델 ID는 운영자 선언이며 서버 실행 모델 자동 인증은 없음.

## 로컬 비교 UI HTTP 계약 (development, 0.1)

- `POST /api/session {}` → token + state. `POST /api/reset {}` → 기존 세션 폐기/새 token + state.
  token은 메모리에만 유지하고 URL/로그/연구 export에는 저장하지 않음. 진행 중인 세션 reset은409.
- `POST /api/ask {question, request_id}` →202 + state. 그 외 알 수 없는 필드는 거절.
  question 1..1000자, request_id 1..80 ASCII 영숫자/하이픈. 같은 ID·질문 재전송은 기존 상태, 다른 질문은409.
  동시 실행409, 질문/재시도 한도409, 변경된 원문409, 만료410. 무승인 진입은 CLI의 명시적 opt-in 필요.
- `GET /api/state` → bundle/runtime/rounds/job/remaining_questions/can_ask/human_approved=false/accepted_perspectives=0.
  job.status=idle|running|done|error. 실행 중 agent_id/stage=starting|generating|auditing/model_calls 표시.
  공개 turn에는 agent_id/status/reason/answerability/points(호스트 고정 citation)/human_approved/semantic_guarantee,
  generation_attempts/audit_requests만 제공. 원시 초안/감사 자유문/미검사 limit 제외.
- `GET /api/export.json|html`은 session token 필수이며 작업 완료 상태에서 내려받는 private 연구 파일.
  JSON은 기존 comparison-0.1 + web_code_sha256 확장 프로파일로 prompts/schema/runtime/모든 attempts 보존.
  HTML은 검사를 통과한 points 및 원문만 표시하며 거절 초안을 최종 답변으로 표시하지 않음.
- 모든 변경 요청은 정확한 same-origin 및 application/json, 최대8192bytes. 모든 경로 Host는 loopback hostname+실제port,
  상태/질문/reset/export의 token은 `X-Session-Token`. CORS 허용 없음, no-store, 외부 asset·inline script 차단.
- 서버 로그는 access body/token을 기록하지 않음. 연구 artifact는 manifest + request + agent checkpoint + round이며
  source 만료를 상속. 파일은 Git 제외, UI reset으로 삭제되지 않으며 자동 복원/만료 파일 자동 삭제는 없음.

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

공식 YouTube 수집에서 `text_original`은 API가 plainText로 반환한 `snippet.textDisplay`입니다.
작성자의 raw `textOriginal`과 동일함을 보장하지 않습니다. 수집 경로의 `sampling.description`에 이 provenance를 명시합니다.
댓글 언어는 자동 추정하지 않고 `und/unknown`으로 기록합니다. [수집 계약](YOUTUBE_COLLECTION.md)을 참고합니다.

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

## Automatic Factory와 잠정 에이전트

서비스 실행 시 수동 처리가 없는 별도 자동 경로입니다. 기존 assistant-reviewed artifact나 수동 승인을 입력으로 받지 않습니다.
기본 실행은 `automatic-factory-0.2`, bundle은 `automatic-perspective-bundle-0.1`을 사용합니다.
과거 `automatic-factory-0.1`도 재검증해 읽되0.2 실행으로 재표기하지 않습니다.

- 추출: `{status: claims|non_substantive|uncertain|context_dependent, claims: [{statement, mode, segment_ids}]}`.
  최대4개; claims 상태와 비어 있지 않은 배열이 일치해야 함. 중복/외부 segment ID 거절.
  코드가 정확한 `{start,end,text}` span과 source/claim ID를 부착. model은 offset/출처를 생성하지 않음.
- 0.2 추출에는 parent 텍스트를 전달하지 않음. `context_dependent`는 독립 명제가 없는 동의/참조이며 claims가 비어야 함.
  이것만으로 부모에 대한 동의/반대 edge를 확정하지 않으며 독립 근거 수에 포함하지 않음.
- 0.2 각 gate result에 `source_audit` 필수: `{verdict: supported|unsupported|unclear, reason}`의 request 결과.
  입력은 `PROPOSED_CLAIM`, `SOURCE_SPANS`뿐. 원문 검사 실패는 `source_audit_rejected`, common gate 미호출.
  source audit가 supported이며 뒤의 common gate도 통과해야 member를 배정. 동일 입력 cache 재사용.
- 의미 검사: `{unit_faithful, core_supported, compatible, reason}`. 각 판정은 supported/unsupported/unclear.
  모두 supported이고 형식/전송/완료 오류가 없어야 잠정 통과. 같은 모델의 판정은 독립 gold가 아님.
- run: snapshot hash/expiry/config/code/prompt/model 선언, 전체 selected record, claim unit, top-k 후보,
  실제 gate edge와 원시 응답/재시도, group, unresolved, 모든 원문의 disposition, coverage를 보존.
  selection은 canonical source ID hash 정렬의 앞 limit개. 대표성 있는 무작위 표본이라고 주장하지 않음.
- group: anchor/common_claim/member_ids/status. 모든 member의 직접 gate, anchor self gate,
  서로 다른 canonical 원문 ≥3, claim당 최대1개 group. 간접 연결은 지지로 간주하지 않음.
- profile: `status=auto_accepted_unvalidated`, 각 evidence에 `support_spans`, `allowed_claim`, full original/URL/parent.
  의미 검증 완료/사람 승인을 뜻하지 않음. `human_handling=false`, `human_approved=false`, `accepted_perspectives=0`.
  auto_agents와 정식 PerspectiveSpec 수를 구분. profile 생성은 저장된 group 전이와 source binding을 재계산해 검증.
- AgentSession: 자동 생성 입력에는 배정 span만 전달하며 profile/title/allowed_claim을 제외.
  원문 감사에 allowed_claim을 주지 않고, 별도 scope 감사에만 전달. 후자는 `audit_kind=scope_only`로 기록하며
  둘 다 supported여야 답변 공개. full original/parent는 citation context이고 다른 주장의 지지 근거가 아님.
  기존 검수 profile의 계약은 유지. 자동/검수 지원 origin을 UI와 export에서 구분.
- 0 agent도 유효한 bundle이며 UI는 질문을 차단하고 자동 보류를 표시. 이웃 부족은 검증된 rare가 아니라
  `insufficient_neighbors_unverified`. snapshot의 미선택/중복/비주장/실패/미배정 정보를 숨기지 않음.

### 실험적 호환성 guard: automatic-factory-0.3

- 명시적 `--experimental-frame-guard`에서만 사용. 실제 개발 회귀 실패로 기본 미채택입니다.
  config/검색/agent bundle 형식은 유지하고 report의 `frame_policy=claim-frame-0.2`와 gate별 `frame_guard`를 추가합니다.
- frame: `status=atomic|mixed|context_dependent|unclear`,
  `scope=self|individual_other|population|unclear`, `time=past|present|future|timeless|unclear`,
  `commitment=assertion|prediction|possibility|normative|wish|unclear`, `condition=none|explicit|unclear`,
  `condition_quotes`(최대3개, 각1..179자, 입력 span의 정확한 부분 문자열).
  explicit만 비어 있지 않은 인용을 허용합니다. schema 상한180자는 validator에서 경계 잘림 가능성으로 거절합니다.
- guard: version/input_digest/frames/condition_checks/blocked_reasons/allowed.
  frames는 anchor/member claim ID별 source/claim을 가지며 각 측은4개 components의 원시 요청 결과와
  조합 output/errors를 보존합니다. 평가 expected 라벨은 여기에 포함하지 않습니다.
- 조건 비교는 `verdict=equivalent|different|unclear`. 동일 공백 정규화 인용은 코드 비교, 그 외 별도 모델 요청.
  거절 시 `errors=[frame_incompatible], output=null, attempts=[]`; source/common gate 미호출입니다.
  통과 시0.2 source audit 및 common gate가 여전히 필수입니다.
- loader는0.1/0.2/0.3을 구분하고0.3의 policy를 gate0개인 경우도 확인합니다.
  입력 binding·component 조합·조건 판정·최종 allowed를 재계산하며 누락/변경 시 거절합니다.
  replay는 보존된 모델 출력의 구조 검증이지 모델 해석이 참이라는 증명이 아닙니다.
- `claim-frame-diagnostic-0.1`은 별도 offline 실험 artifact입니다. expected 라벨/합성 사례/기존 개발 member,
  baseline·fixture·reference·code·prompt hash 및 결과를 기록합니다. 독립 gold나 서비스 입력이 아닙니다.

### Offline NLI 비교 artifact

- `claim-support-diagnostic-0.1`은 Factory report나 agent bundle이 아닙니다. 서비스 입력/수동 승인 자료로 쓰지 않습니다.
  snapshot/baseline/reference/fixture/frame 보고서 hash, 원본에 재연결한 cases, 만료, 코드 hash,
  고정 모델 revision/threshold/runtime, 두 정책 및 다음 단계 조건을 inference 전에 manifest로 저장합니다.
- 각 case의 checks는 premise/hypothesis와 LocalNLI 원시 logits/scores/relation/errors/시간을 보존합니다.
  정책은 directional의3검사와 mutual_claims의5검사를 모두 통과해야 allowed이며 원문 실패를 다른 검사로 구제하지 않습니다.
  `expected`는 별도 offline 라벨이고 모델은 두 문자열만 받습니다. 결과에 따라 기준을 수정하지 않습니다.
- checkpoint는 입력 hash 파일명과 request/result/result_sha256을 가지며 exact-input cache만 재사용합니다.
  manifest/입력/결과 hash 변경 시 거절합니다. relation은 scores와 고정 threshold로 다시 계산하며 불일치 시 거절합니다.
  영어500자/512token 상한은 기존 provider를 따르고 길이 초과를 조용히 자르지 않습니다. 만료 후 추론/캐시 사용 금지.
- summary는 양성 유지/음성 차단/오류/각 실패 ID를 별도로 기록합니다. `next_stage_eligible`도 품질 승인을 뜻하지 않으며
  이번 실제 실행에서는 양 정책 모두 false입니다. 개인 댓글 포함 report/overview/checkpoint는 Git 제외입니다.

### 공통 주장 진단 계약

- `temporal-guard-0.2`: input_digest/parts(commitment,time)/lexical(overrides,witnesses)/output/errors.
  lexical witness의 정확한 offset/텍스트 및 component 조합을 재계산합니다. 기존 raw 모델 판단은 덮어쓰지 않습니다.
- `shared-core-0.3`: 두 unit 입력 digest, source fidelity 및 source/claim 시간 검사, 개인 행동 표지,
  proposal, 원래 claim2개+생성안1개 이하 candidates, candidate별 source/claim→core NLI/시간/조건 검사,
  selected_core/blocked_reasons. 생성안은250자 경계 미만이며 빈 문자열은 제안 없음입니다. 최대1회 형식 repair만 허용합니다.
- `shared-core-diagnostic-0.1`은 새 공통 주장 검색을 별도 offline protocol로 기록합니다.
  기존 reference 기대값은 inference에 전달하지 않습니다. 모든 중간 실행과 prototype version을 보존하고
  `next_stage_eligible=false`를 최종 품질 실패로 유지합니다. cache 재사용은 request/model/prompt/runtime/expiry/hash를 확인합니다.
- `common-core-assembly-0.1`: unit/candidate digest, 결정 예산, seed_limit, seed/attach decisions, groups, unassigned_ids.
  seed별 core는 고정하고 member마다 직접 지지를 요구합니다. 3개 distinct source 미만은 그룹을 승격하지 않습니다.
  greedy disjoint 배정/최대9member/10,000자이며 미배정은 검증된 희소 관점이 아닙니다. replay는 원시 cache로 결과와 전이를 재계산합니다.
- `shared-core-integration-0.1`은 `--diagnostic-only` 전용입니다. 최대64개 source를 처리한 source-only0.2 추출만 재사용합니다.
  inference 전 manifest에 protocol amendment, quality_gate_passed=false, 원본/code/model hash 및 예산을 기록합니다.
  조립 결과와 source-bound provisional profiles를 저장하되 기본 자동 bundle/정식 PerspectiveSpec으로 재표기하지 않습니다.
- 진단 profile은 기존 AgentSession의 auto_accepted_unvalidated 계약을 따르고 original span offset/3개 distinct source를
  검증합니다. source 만료/입력 hash 변경을 거절합니다. 실제 최신 진단은 profiles=[]이므로 실제 새 agent 질의는 실행되지 않았습니다.
  기존 앱 자동 loader는 새 진단 report를 승인된 입력으로 취급하지 않습니다. corpus/원시 결과는 계속 Git 제외입니다.

### 원문 선택 진단 계약

- `evidence-units-0.1`: 모델은 `status`와 최대4개 `first/last` sentence-ID 범위만 반환합니다.
  host가 원문에서 `statement`를 복사하고 `focus_spans`, 문맥용 `spans`, `topic_quote`,
  `source_digest`, source ID와 offset으로 계산한 claim ID를 저장합니다. 재결합 검증에서 다르면 거절합니다.
- eligibility는 전체 자기 댓글과 focus만 받습니다. `status=substantive` 및 원문에 있는 topic quote가 필요합니다.
  구조적 substring 검증은 미해결 지시 대상이나 의미 품질을 보장하지 않습니다.
- 짧은 댓글 전체 또는 긴 댓글의 focus/topic envelope와 인접 문장을 최대500자로 저장합니다.
  넘으면 보류하며 부분 절단하지 않습니다. 현재 긴 댓글에서 필요한 앞 문장이 빠지는 실패가 발견됐습니다.
  따라서 전체 댓글 eligibility와 최종 evidence의 의미 동등성을 완료 기능으로 취급하지 않습니다.
- `evidence-core-0.1`: 공통 후보의 독립성, 각 source→core NLI와 qualification 감사를 요구합니다.
  원문 표현 우선, 생성 제안은 최대1개이며 생성 문장은 근거가 아닙니다.
- `common-core-assembly-0.3`: `seed_order=source_density`, 서로 다른 두 source의 유사도 우선.
  기존 degree 순서와 최소3source·직접 가입·고정 core·예산 규칙은 동일합니다. 동적 순서도 replay합니다.
- `evidence-units-probe-0.1`: 고정 source_plan·fixtures/input/code hash·runtime·만료·실패를 기록합니다.
  `policy.schema_visible`와 대상 단계를 명시하며 schema 노출은 request cache 전에 수행합니다.
  raw prompt가 다른 결과를 재사용하지 않습니다. 기존 기본 transport나 Factory loader를 변경하지 않습니다.
- 진단 보고서는 정식 bundle이 아니며 `quality_gate_passed=false`, `independent_gold=false`입니다.
  모델 호출 없는 exact replay는 재현성 검사이지 의미 정확성 증명이 아닙니다.

### 주제 위치와 최종 근거 진단 계약

- `evidence-positions-0.1`는 기존 sentence-ID focus와 별도로 `topic`에 최대1개의 첫/끝 token ID를 받습니다.
  token은 Unicode 비공백 원문 구간이며 언어 분석 결과가 아닙니다. substring/offset/선택 occurrence를 host가 결정합니다.
  topic120자·statement450자·evidence500자 상한을 넘으면 보류합니다. 모델이 topic/statement 문자열을 작성할 수 없습니다.
- unit의 `topic_span`에는 first/last ID와 원문 start/end/text를 저장합니다. source digest, focus/context,
  topic occurrence를 재결합해 검증하며 변경 시 거절합니다. 구조적 정확성은 의미적 주제 타당성 보장이 아닙니다.
- `position_units`는 주제 위치 단계 산출물이고 `units`는 최종 근거 eligibility까지 통과한 부분집합입니다.
  final 요청은 FINAL_EVIDENCE/FOCUS/TOPIC만 받습니다. 이전 판정·전체 원문·다른 댓글은 입력에 포함하지 않습니다.
  최종 allowed는 모델의 fallible 판정이며 raw 결과/입력 digest/오류를 보존합니다. 진단 결과를 정식 agent bundle로 승인하지 않습니다.
- `evidence-positions-probe-0.1`는 기존 선택 범위 고정 개입, 만료/input/code hash, 모델/embedding revision,
  원문과 두 단계 units에 대한 source-level 검색 노출을 기록합니다. 미추출 source를 분모에서 빼지 않습니다.
  원시 cache를 통한 exact replay는 새 모델/embedding 호출 없이 수행합니다.

## Raw candidates 0.1 (진단 전용)

- registry: `sources[{source_id,text,source_digest,parent_id,indexable}]`, `aliases`, `selected_input_ids`.
  normalize_snapshot으로 재구성한 값과 일치해야 한다. 공백 원문도 보존, alias는 추가 표가 아니다.
- embedding cache: model/revision, 순서가 고정된 source IDs와 exact texts, vectors와 digest/runtime.
  길이·차원·유한값·0이 아닌 norm을 검사한다. 오류 source를 조용히 누락하지 않는다.
- candidates: 모든 canonical ID가 key, 최대12개 이웃과 cosine/lexical/route. 검색은 지지 판정이 아니다.
- queue: 원문 digest에 결합한 pair_id/source_ids, first_discovered_from/candidate_rank,
  available_unique_pairs/deferred_pairs/budget_exhausted. 양방향 동일 pair는 한 번만 검사 대기한다.
  `support_count=null`, `quality_gate_passed=false`, `agents=[]`. 미검사는 비지지가 아니다.
- source_packet: 두 댓글의 ID/digest/text만 전달. parent 본문을 답글에 덧붙이지 않는다.
- probe: snapshot 만료 및 input/code/model pin, evaluation-only reference pairs, 별도 단계 시간.
  plan/run/verify, 저장 vectors만 사용한 replay 일치. 원문 포함 산출물은 Git 제외와 만료 상속.
- [지지도 상태/분모/잠정 표시 등급/시간 목표 계약](RAW_RETRIEVAL_MVP.md)은 다음 집계 모듈의 설계이며
  현재 runtime 지지 판정 구현으로 읽지 않는다.

## Raw support 0.1 (진단 전용)

- pair trace: source-bound pair_id/input_digest, 단일 proposal, 독립 source checks, selected_core/status.
  두 source 모두 support일 때만 pair_supported_unvalidated. 없음/오류/미검사와 의미 거절을 구분한다.
- source decision: source_id/source_digest/core_digest,5상태 state/reason, NLI, audit, qualification_guard, evidence.
  인용의 모든 exact occurrence offset을 보존하며 동일 문자열 반복에서 모델이 특정 위치를 골랐다고 가정하지 않는다.
- ledger: 고정 core/registry digest, canonical source별 한 행, counts/support_count/completed_count,
  canonical_denominator, 잠정 tier/major_threshold. 미예약은 unchecked이며5상태 합은 N이다.
  중복/alias/foreign source/변경된 core/hash/support trace 누락은 거부한다.
- 모든 ledger는 quality_gate_passed=false/agents=[]/model_counts_unvalidated다.
  단위 테스트 통과와 모델 의미 정확도는 별개이며 지지 수를 사실·독립 사용자 수로 표시하지 않는다.
- raw-support-probe0.1은 별도 고정 회귀/실제64쌍, source-bound cache/replay, 제한된 확장 여부와 시간을 기록한다.
  자세한 입력 길이와 평가 계약은 [공통 주장·지지도 MVP](RAW_SUPPORT_MVP.md)를 따른다.

## Positional support 0.1 (진단 전용)

- pair alignment는 left/right 각각 최대1개 first/last ID 범위이며 L/R prefix가 다른 원문 ID 혼입을 막는다.
  bound span은 source_digest/start/end/first/last/text다. 값은 원문에서 매번 재구성한다.
- audit에는 assertion/eligibility/6속성/evidence 범위만 있고 supported나 자유 quote 필드는 없다.
  enum·ID 오류와 semantic disagreement를 구분한다. host가 5상태 결정을 만들고 original/evidence NLI와 guard를 보존한다.
- evidence가 없거나 독립성이 불명확한 판정은 support로 승격하지 않는다. 실제 의미 오판을 코드 검증으로 증명했다고 읽지 않는다.
- 기존 raw-support ledger와 호환된다고 간주하지 않는다. 이 버전은 pair/직접 판정 probe만 제공하며 agent/가입 확대0이다.
  [계약·사전 기준](POSITIONAL_SUPPORT.md)을 따른다.

## Extractive candidates 0.1 (비교 전용)

- inventory는 source ID/digest/segment ID/start/end/text와 candidate ID를 결합한다. 항상 원문 slice와 일치해야 한다.
  eligible=false와 deferred_reason은 길이/예산 상태이며 의미 비지지 판정이 아니다. 원문 registry는 변경하지 않는다.
- 선택은 source별 최대2개, 후보의 반대 source 최대 cosine 순서이며 동점은 candidate ID다.
  selected의 core는 원문 문자열 그대로이고 core_digest와 origins가 재결합돼야 한다. 문자열 중복만 병합한다.
- support_count=null/agents=[]/quality_gate_passed=false다. origins 개수와 cosine은 지지 수가 아니다.
  assess는 두 전체 원문 각각을 positional-support로 검사하며 출처 원문의 자동 지지도 금지한다.
- [추출형 평가·예산 계약](EXTRACTIVE_CANDIDATES.md). 모델 통과와 실제 원문 충실성은 별도 평가한다.

## Audit repeatability 0.1 (진단 전용)

- plan은 기존 exact 감사 request와 개발 기대/과거 출력, 입력·코드·모델·런타임 hash, 4arm/3반복/144회 예산을 고정한다.
- attempt는 arm/sequence/case/repeat/request_sha256/result/result_sha256/원본 response/host decision을 담고 전체 hash도 결합한다.
  동일 request도 별도 sequence로 저장하며 추론 응답 cache는 사용하지 않는다. 중단 실행 재개는 금지한다.
- report의 support는 NLI·guard를 제외한 provisional projection이다. ledger/agent 입력이 아니며 agents=[]/quality_gate_passed=false다.
  [반복성 평가 계약](AUDIT_REPEATABILITY.md)을 따른다. 일관성과 정확도는 별도 측정한다.

## Audit model comparison 0.1 (진단 전용)

- 40평가 행은 cohort/expected/request_id를 담고39고유 요청은 system/data/schema만 담는다. 라벨은 추론에 전달하지 않는다.
- 모델별 attempt는 model/sequence/request_sha256/result/result_sha256/원본 HTTP response/host decision과 전체 hash를 저장한다.
  양쪽 요청 순서와 payload를 고정하고 모델별 fresh39회씩 실행한다.
- report는 군별 정상 보존/부정 오승인·거절·보류/오류와 사전 진입 기준을 출력한다.
  candidate_eligible_for_full_pipeline_trial은 다음 시험 자격일 뿐 quality_gate_passed=false/agents=[]를 바꾸지 않는다.
  [모델 비교 계약](AUDIT_MODEL_COMPARISON.md)을 따른다.

## Source eligibility 0.1 (opt-in 비교 전용)

- request_for는 원문 전체의 위치 결합 SOURCE만 전달한다. target/평가 라벨/peer/parent는 입력하지 않는다.
- 단일 eligibility enum을 host가 eligible/excluded/context_dependent/uncertain/error로 해석한다.
  eligibility는 support_count나 source-target 충실성/agent 승인이 아니다. 미확정은 eligible이 아니다.
- identity는 exact 요청과 모델 식별정보/version을 결합한 재사용 키다. corpus 필터/실제 cache/ledger 연결은 없다.
- 3조건 probe는 각32개 source별 새 호출을 저장하고 원문별 label 변화와 군별 정상 보존/오승인/보류/오류를 보고한다.
  [평가·실행 계약](SOURCE_ELIGIBILITY.md)을 따른다. quality_gate_passed=false/agents=[]를 유지한다.

## Eligibility witness 0.1 비교 전용

- SOURCE 전체와 WORDS 배열을 주고 반열린 단어 범위로 candidate/endorsement/mention/antecedent를 받는다.
  공백 단위 분할은 원문 시작·끝 위치를 유지하며 host가 source digest·문자 위치·원문 slice를 결합한다.
- 구조 오류는 error, 위치상 유효하지만 관계 모순은 uncertain, 미해결 문맥은 context_dependent다.
  eligible은 해당 source의 한 주장 자격만 의미하며 support_count/agent 승인으로 사용하지 않는다.
- 입력4,000자/128tokens·candidate1·references4 한도이며 초과 시 자르지 않고 보류한다. 서비스 필터/cache 미연결이다.
- [고정 비교](ELIGIBILITY_WITNESS.md)는 기존 단일 enum과48원문씩 비교한다. required_text는 평가 전용이며 추론 입력이 아니다.
  quality_gate_passed=false/agents=[]를 유지한다.

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
