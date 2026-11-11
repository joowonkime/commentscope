# 구현 순서와 검증 및 비용 계획

연결: TASK-019~024, DEC-013/014. 설계 기준은 [검토 결론](MVP_DESIGN_REVIEW.md)과
[원문 증거 그래프 계약](SOURCE_EVIDENCE_GRAPH.md)이다.
**이번 산출물은 계획이다. 아래 미래 검사를 수행했거나 비용·시간·새 모델 배정을 승인한 것은 아니다.**

## 1. 어떤 순서로 진행할까

1. 기존 결과에서 원인·보존·이유의 평가 분모를 고정한다(TASK-020).
2. 기존 기본값을 유지하고 B1 graph protocol과 adapter만 구현한다(TASK-021).
3. 동결 A/B1/C component 비교와 미사용 전이로 채택 여부를 판단한다(TASK-022).
4. 선택한 표현을 고정한 뒤 검색 배분·전체999·3000 규모를 별도로 검증한다(TASK-023).
5. 화면 경쟁 조건·pending 작업 복구를 보강한다(TASK-024). TASK-020 뒤 무료 회귀는 병행 가능하다.
6. 기존 TASK-005→006→007의 정식 G1~G4, TASK-012의 실제 제품·사용자 검증을 완료한다.

TASK-017/018의 구현·실행 이력과 미완료 품질은 보존한다. 새 작업 때문에 완료로 올리지 않는다.
과거 S1/S2 전체교체 TASK-004/013/014도 자동 재개하지 않는다.

## 2. TASK-020 실패 감사와 고정 평가

기존17 논거 record/96unit,52 map 관계,34 Jev enum 보류,4 용량 영향 입력을 무료로 대조한다.
원문의 모든 실패를 한 개 원인으로 합치거나 중복 hold를 다른 댓글 손실로 세지 않는다.

원인 기록은 다음 필드를 갖는다.

```text
case_id, source_ref, candidate_ref, stage, first_blocking_event,
downstream_consequences[], classification: justified|avoidable|unknown,
evidence_refs[], reviewer_kind, competing_explanations[], cheapest_falsifying_test
```

실패 원인은 binding/transport/capacity/representation/ownership/scope/dependency/fact/retrieval로 나눈다.
한 source가 여러 후보에 관계하면 source 수·관계 수·unit 수를 따로 집계한다.
과거 응답으로 재구성한 결과에는 `replay`, 신규 요청 결과에는 `fresh`를 표시한다.

개발 표본은 **최대48 source window/256 source-target 관계**로 계약을 고정한다.
현재17 record를 포함한 알려진 사례와, 그 밖에서 사전 층화한 사례를 분리 보고한다.
층은 단순 입장·이유, 혼합/조건/예측, reply/인용/지칭, 불확실/비입장/noise다.
같은 root thread는 split을 넘나들지 않는다. 없는 층을 복제해 수를 채우지 않는다.
실제 선택 ID/hash/기대 의미/선정 규칙은 private manifest로 먼저 동결하며 공개 fixture는 합성이다.

별도 holdout은48 source window(무작위24+난례24)를 **구현/프롬프트 튜닝 전에** 보류한다.
가능하면 허용된 다른 영상에서 선정한다. 기존999 안에서 골랐다면 전체 discovery가 이미 읽었으므로
`annotation-blind same-corpus transfer`라고 표기하고 미사용 영상 일반화라 부르지 않는다.
결과를 보고 수정하면 해당 holdout은 개발 자료가 되며, 같은 표본의 반복 통과를 fresh 전이로 세지 않는다.

이 작은 표본은 원문 해석 **부품 진단**이다. 입력 풀 확대/전체 Agent 생성 검증을 대체하지 않는다.
나중 전체 발견은999 모두를 실제로 읽는다.

## 3. TASK-021 구현 경계와 테스트 순서

| 단계 | 변경 파일/책임 | 먼저 실패해야 할 검사 | 완료 증거 |
| --- | --- | --- | --- |
| 21a graph 형식 | 신규 `factory/source_evidence_graph.py`, closed protocol/types/validator | 혼합 의미·조건 공유·범위 변조·Unicode·오류 inventory·capacity | 순수 host 검사, 외부 호출0 |
| 21b proposer/observer | 신규 `factory/source_evidence_requests.py`, provider의 기존 guarded dispatch 재사용 | observer에 proposer label 노출,missing unit/fact0 누락,불완전 질문 승인 | request hash·입력 경계·의미 의무 대응 회귀 |
| 21c candidate 연결 | 신규 `factory/source_evidence_adapter.py`, `pipeline_work`/`pipeline_stages` opt-in | 부모 이유 차용,scope 약화,wrong candidate,필수edge 삭제 | 기존 strict admission/전체 eligible-support 목록 보존 |
| 21d review/Compiler | 기존 `source_arguments`, review,`minimal_agents`의 명시적 version dispatch | oldreceipt 재태깅,두protocol 혼합,선택unit/필수fact 미검사 | 기존 정상/부정 기대 유지·default 경로 불변 |
| 21e 비용/재개 | cost profiles/plan·request caps·artifact invalidation | unknown stage0달러 처리,기존checkpoint를 새protocol로 재사용 | 신규stage 미측정이면 paid preflight 거절 |

파일명은 구현 위치를 고정하기 위한 제안이며 빈 추상 class나 미사용 서버 계층을 만들지 않는다.
반드시 신규 protocol에 필요한 모듈만 추가한다. actual enum/shape는 SOURCE_EVIDENCE_GRAPH를 따른다.
기존 graph를 수정해 `parse(source)==graph` 검사를 우회하지 않는다.

의미 변경은 정상·부정 입력/기대 먼저 →최소 구현 →관련 검사 →Factory checker 순서다.
API 변경은 관련 product 검사와 실제 `/mvp` 브라우저 검사를 추가한다. 문서만 바꿀 때 Factory 전체를 반복하지 않는다.
CI는 기존 Ubuntu/Windows 전체 회귀를 유지한다. 기본값 변경은 TASK-022 증거가 있어야 한다.

## 4. TASK-022 동결 비교와 선택 규칙

| arm | 표현 | 생성 | 검증/검색/기준 |
| --- | --- | --- | --- |
| A | main3b4069a legacy+PR89 | 기존 GPT-5.2 역할 | 현행 설정 고정 |
| B1 | 새 graph,기존 strict admission | A와 동일한 생성 deployment | 기존 Jev M1/M2·fact 의무·검색 고정,구형 F4 호출만 대응 교체 |
| C | B1과 동일 graph/단순화된 호출 계약 | Sol 생성 역할 비교 | B1 reviewer/deployment/입력/상한 동일 |

모델의 실제 ID·provider·reasoning·가격·prompt/schema/wire hash는 실행 준비 때 확인하고 동결한다.
여기의 모델 이름은 현재 코드 역할과 비교 축이지 새 가격/가용성 보증이 아니다.
C에서 review까지 바꾸거나 M1을 제거하면 별도 구조 실험이므로 같은 arm 결과로 합치지 않는다.

source 단위 비교는 upstream candidate/map을 같은 입력으로 고정할 수 있지만,
이는 **부품 비교**이지 전체 fresh Factory가 아니다. 이전 응답이 새protocol에 재활용되는 경우는 없다.
같은 arm 안의 정확한 완료 checkpoint 재사용만 기존 규칙으로 허용한다.

필수 관측값:

- 사람이 원문에서 먼저 표기한 substantive proposition의 보존/누락: 조건·귀속·양태·시점 포함.
- true/false support, valid support retention, unassessed; candidate/희귀/조건부 층별 분리.
- 원문에 이유가 있는 source-target 관계 중 실제 자기 이유와 필수 closure가 살아남은 비율.
- 타입/귀속/조건/필수 사실의 최종 게시 경계 오류; 잘못된 출력과 올바른 보류를 구별.
- usable Agent 수·유효지지·이유 있는 Agent 수, 답변 가능한 질문의 유용한 답변과 올바른 abstain을 분리.
- 전체 stage별 호출/토큰/청구/보류 비용과 wall/provider/host/recovery 시간.

**추천 선택 규칙**은 다음과 같다. 기존 r5를 대체하는 새 합격선은 아니다.

1. 기존 음성 통제의 중대 왜곡·잘못된 지지·필수 조건/귀속 손실이 게시 경계를 통과하면 승격 보류.
2. 기존100관계 diagnostic precision0.95/valid support retention0.8과 formal 기준은 유지한다.
3. B1의 비교 표본에서 유효 proposition·reason 보존이 A보다 좋아지고, 유효 support 보존이 낮아지지 않아야 한다.
   대응 source별 회복/손실을 모두 공개 집계하고 소수 사례 차이만 있으면 미결정으로 둔다.
4. holdout에서도 개선 방향과 안전 의무가 유지되는지 확인한다. 작은 표본의 오류0을 일반 정확도100%로 주장하지 않는다.
5. C는 B1과 같은 안전·보존을 충족하고, 추가 유용성 또는 비용/시간 이점이 있을 때 선택한다.
   유용성 동률이면 총실청구,그다음 동일 source 전체 처리시간의 p95가 낮은 쪽을 택한다.
   이 시간은 그 source의 모든 요청·검토·closure·host 시간을 포함한다. 단건 provider p95 및 전체job wall time은 별도 보고한다.
6. 실패1건을 보고 paid 수정 반복하지 않는다. 재무/무결성 중단 사유가 아니면 나머지 동결 표본을
   원래 상한 안에서 마친 후 원인 묶음 단위로 한 번에 결정한다.

자의적 채택을 막기 위해 TASK-020 manifest에 분모·paired gain·손실 허용·동률 규칙을 수치로 넣는다.
추천 초기 규칙은 실제 이유가 있는 gold 관계 R≥20일 때 순 회복이 `max(3,ceil(0.10×R))` 이상,
전체 유효 support와 proposition 보존의 순손실0,표본에 있는 각 층에서 이유 보존 순손실0이다.
이유가 있는 관계가20 미만이면 component 관측은 보고하되 그 결과만으로 B1 개선을 채택하지 않는다.
C에도 같은 증가 기준을 적용하며 유용성 동률은 올바르게 보존한 source-target/이유 집합이 같은 경우다.
서로 다른 사례를 비슷한 개수로 성공한 결과는 동률로 합치지 않고 tradeoff/미결정으로 남긴다.
위 수치는 공학 비교 규칙이며 통계적 유의성 보장이나 기존60% 활용 목표를 바꾸는 문턱이 아니다.
변경이 필요하면 모델 결과를 보기 전 이유와 새 manifest를 기록한다.

검토자는 원문·부모 문맥을 보고, 모델명/arm명/이전 판정만 가린다.2명 팀원의 검토와 불일치 조정을 권장한다. 한 명 또는 AI 검토만 가능하면
그 provenance를 그대로 쓰며 independent human gold라고 보고하지 않는다. 외부 연락은 별도 지시 없이 하지 않는다.

## 5. TASK-023 검색과 전체 규모

B1을 비교하면서 검색 후보/순서까지 바꾸지 않는다. 표현 선택 후 다음 검색 대안을 동결 비교한다.

- 현행 후보당 최대16 source를 우선 배정하는 baseline.
- 후보마다 초기3개(서로 다른 thread 우선) →다음 round 최대3개씩 →기존 후보별 최대16의
  round-robin 후보. nominee는 검색 우선순위일 뿐 support vote가 아니다.
- 별도20% pair quota를 사전 정의한 저빈도/조건부/미선택 후보 탐색에 배정하는 후보.

위 숫자는 검색 실험 후보이며 승인된 기본값이 아니다. 현재 cap과 동일한 전체source/pair 예산에서
nominee·지지 도달·유효희귀관점/Agent·원가를 비교한다. 첫 두 후보는 별도 arm,세 번째는 그 뒤 단일factor다.
전부 한꺼번에 바꿔 효과를 해석하지 않는다. 예산 소진은 unassessed이며 반대/무의미가 아니다.
정확 문구 중복은 유지하며 의미 병합은 첫 구현에서 제외한다. 동치 아닌 후보를 합쳐 지지 수를 옮기지 않는다.

전체999 개발/정식 계획은 다음을 따로 고정한다.

- 전체 발견 N=999, 전체 후보 H, 넓은 membership 대상 S/P, Agent-eligible 후보 전체 지지 합집합 D.
- r5 활용의 고정분모755/목표453, 최소2 Agent/각3유효출처, G2 12/19·G3 45/74와 기존 사실·runtime.
- formal G1→G2→G3→G4의 동일 설정·admission. 새 development999 성공을 정식 gate로 승계하지 않음.
- S≤120인 개발 계획은453 gate에 적합하지 않다고 preflight에서 명시. 목표453인데S<453이면 **계획 부적합**.
- D개 source 전부의 필수 심층 검사 비용. 모든453개가D라고 가정하지도,임의3개만D로 줄이지도 않음.

3000개는 registry/retrieval만3000을 허용한다고 전체 처리 완료가 아니다.
별도 snapshot/진단 schema로 parser·embedding·후보/H·S/P/D·review·Compiler·저장·복구·제품 loading을
끝까지 검사한다. 기존 r5 fixture와 `comment_utilization`의1000 입력 상한은 version 분리 없이 변경하지 않는다.
TASK-023의3000 범위는 실행 계획과 무료 형식·부하 상한 검사다. **실제3000 전체 실행은 TASK-007의
고정999 합격 뒤 별도 plan/권한/예산으로 진행**하며,023 완료나 registry 검사로 완료 처리하지 않는다.

## 6. 비용과 시간

실제999의 확정 비용은 다음과 같다. 전체 원문 발굴 이후 상세120개/논거17개라는 제한 범위의 결과다.

| stage 묶음 | 성공호출 | 확정 USD |
| --- | ---: | ---: |
| 발견 |84|1.0970190|
| Jev M1 |2186|0.372667680|
| source/candidate context·world, M2 |586|1.1173055|
| 논거 metadata/alignment/owner/dependency/audit |286|1.29669660|
| core/fidelity |12|0.019406|
| embedding |42|0.00106206|
| runtime |3|0.00898100|

합계3199 성공/$3.913137840, terminal503 보수차감$0.042015750을 포함한 phase charge$3.955153590.
Jev는 비용9.52%다. 원본 provider elapsed 합계5116.007초 중 Jev1718.393초(33.59%)이며,
이 비율은 서비스 wall time 비율이 아니다. 원실행 요청 창은 약5시간50분이고 host 중단·복구가 포함됐다.
마지막 복구에서 신규 요청까지1181.155초가 걸렸다. 단가만이 아니라 packet 수·host 복원도 측정해야 한다.

비용 함수의 독립 변수는 `N=전체원문,H=후보,S=membership원문,P=검토쌍,D=심층원문,U=의미unit,
E=필수관계,F=사실검증,A=최종Agent,T=대화턴`이다.

```text
C_total = C_embed(N,H) + C_discover(N,lengths) + C_context(S,H)
        + C_M1(P,physical_packets) + C_M2(positive_edges)
        + C_graph(D,U,E) + C_fact(F) + C_compile_review(A) + C_runtime(T)
C_bound(request) = pinned price_bound(full wire payload, billable input including
  typed question expansion, total generated/reasoning tokens, request fees,
  other provider-priced terms)
charged = confirmed + conservative
admit only if charged + active_reservations + C_bound(next) <= every applicable cap
estimate_remaining = 1.25 × sum(remaining_workload × validated_stage_profile)
```

1.25는 공학 여유이며 통계적 보장 상한이 아니다. 미측정 stage는 `null`이고0달러로 처리하지 않는다.
기존 transport/deployment의 가격 계산이 정본이다. reasoning이 generated token에 포함되는 제공자는 중복 계산하지 않는다.
최대 금전 안전은 예약 상한이 보장하고, 예상 완료 가능성은 profile로 별도 검토한다.
최대unit/edge/packet/token 출력과 fact 검증까지 포함하지 않은 plan은 full run으로 실행하지 않는다.
보존이 개선되면 D/F/A가 늘어 비용이 오를 수 있다. 이유를 버려 싸진 결과는 최적화 성공이 아니다.

3000 견적은 다음3개 **시나리오 템플릿**에서 N/H/S/P/D/U/F를 각각 채운다. 아직 가격 견적은 없다.

| 시나리오 | 의미 | 보고 제한 |
| --- | --- | --- |
| N3000,S120,P1536 유지 | 입력만 넓힌 제한 발견 | 전체 활용/정식 품질·서비스 단가로 보고 금지 |
| N3000,여러 후보/희귀·조건부를 검토하도록 S/P 확대 | 실제 발굴형 제품 준비 | 측정된 D/U/F를 포함해야 원가 산출 가능 |
| 기존N999/755 정식coverage |453 유효활용과 eligible-support 전체 심층검사 |3000 서비스와 별도 범위/가격 |

첫 A/B1/C 부품 비교 **합계5달러 이내를 제안**한다. 새 권한이나 실제 예약이 아니다.
TASK-020은 표본과 의무·예비 packet/token 상한을 고정하고, TASK-021은 실제 wire 구성/예약 상한을 검증한다.
새 stage의 실측 profile은 아직 없으므로 TASK-022 첫 단계에 **제한된 부품 측정**을 둔다.
이는 full-run admission이 아니다. 각 요청의 보수 wire 가격 상한·전체 packet/token 상한과
별도 scoped 권한으로만 측정하며 같은5달러 예산 안에 포함한다. 기존 full-run의 unknown-profile 거절은 유지한다.
모든 신규 stage profile을 얻거나 보수적인 완료 가능성을 검토하지 못하면 전체 비교/확대는 보류한다.
측정 표본·질문·비용도 결과에 포함하고 그 결과로 control 기대값이나 모델 prompt를 수정하지 않는다.
전체 비교 전 모든 arm의 wire·단계별 가격·남은 비용 preflight를 다시 동결한다.
상한에 맞지 않으면 범위를 몰래 줄이지 않고 manifest를 실행 전 수정·재동결하거나 실행 보류한다.
holdout·전체999·formal gates·제품 사용은 이후 측정된 profile로 각자 한도를 배정한다.
같은 비교 예산을 arm마다5달러씩 새로 만들지 않는다.

마지막 재무 관측(2026-11-11 02:35UTC)은 key한도150/사용14.401930440, 보수 운영장부50의
잔여29.322154210이다. 이는 현재 잔액을 새로 조회한 값이 아니다. 만료된15달러 단계의 남은 금액은
실행 권한이 아니며 모든 과거 보수차감을 계승한다. 새 paid plan에는 현재 잔액·기한·scope 확인이 필요하다.

실행 중 가격/모델/입력/hash 변경,미측정 비용,예약부족,hostguard,기한/자료만료,물리cap,미확정과금은
기존 중단 조건이다. 재시도0. 호출수를 줄이는 transport batching과 병렬화는 별도 비교하며
장부/응답 순서/중복 요청/전체token비용을 보존한다.

시간은 준비·검색·provider 대기·host 검증·저장·복구·사용자 대기를 구분한다.
처음부터 분산 worker를 만들지 않는다. exact completed checkpoint 읽기와 새dispatch를 구별하고
semantic validation을 건너뛰지 않은 상태에서 host replay 비용을 측정한다.
온라인은 저장 bundle을 읽으므로 질문마다 Factory를 반복하지 않는다.

## 7. TASK-024와 실제 제품 완료

기존 `experiments/mvp_browser_check.cjs`를 재사용해 실제 `/mvp` 화면을 deterministic provider로 검사한다.
무료 browser 테스트를 CI에 연결하되 live key가 필요 없게 한다. Python API/legacy DOM smoke도 유지한다.

| 검증할 경로 | 기대 |
| --- | --- |
| A방 GET을 지연한 뒤B방 선택 | B화면이A응답으로 바뀌지 않음 |
| 전송 중 다른 방 선택/새 질문 입력 | 처음 선택한 방·본문으로1회 전달,새 초안 보존 |
| 비교/성찰 queued·running 중 새로고침·같은행동 재클릭 | 같은 의도 job 이어보기,provider 신규 dispatch 중복0 |
| 오류 후 acknowledge·다른 과업 이동 | 기존 작업 보존,자동 유료 retry0,다음 행동 표시 |
| 일시 네트워크 실패·뒤로가기·재접속 | 유효 session을 만료로 삭제하지 않음 |
| Agent 부족·근거 부족·자료 만료 | 능력을 정직하게 표시,가짜 관점/근거 없이 다른 행동 가능 |
| 대화 전에Reflect·의견유지·편집·저장·재열람 | 없는 대화/변화 창작 없음,사용자 저장본 복원 |

pending intent의 키는 session/operation/analysis revision/opinion revision/정규화하지 않은 정확args hash와
지속 request ID를 포함한다. 동일 의도 queued/running은 기존 job을 반환하고 terminal 실패는
자동 재시도하지 않는다. 새 revision·다른본문은 새 의도다. UI의 선택 상태와 요청 대상은 분리한다.

실제 준비된 bundle에서2개 이상 관점이 **자기 출처의 실질 이유를 설명할 수 있는지** 확인한다.
이는 최소2/3출처 기준을 낮추지 않고 stance-only Agent의 유용성 구멍을 막기 위한 release 검사 제안이다.
나머지 stance-only/보류 결과도 누락 없이 보고한다. 이유 하나를 모든 source의 공통 이유로 확장하지 않는다.

첫 사용자 관찰은 초행5명,과업만 제시하고 정해진 클릭 경로·질문은 주지 않는 방식을 권한다.
공식 TA 필수 인원은 아니다. Explore→스스로 궁금한 질문/근거 확인→Reflect·저장에 대해
완료/부분/막힘·도움·이유 이해·근거 연결·복구·대기·중복 호출을 전부 기록한다.
수정 후 새로운 초행2명으로 관련 과업을 재확인하는 것도 제안이다. 참가자 모집/연락은 자동 수행하지 않는다.
실제 core task를 막는 재현 가능한 blocker는 완료로 처리하지 않는다. 작은 관찰을 시장 경쟁력 증명으로 쓰지 않는다.

## 8. 작업 DAG와 완료 조건

| TASK | 선행 | 산출물/변경 범위 | Done / Hold |
| --- | --- | --- | --- |
|019 설계 감사|002,016|현재/제안/과거 지도,계약,비교·비용·TA 계획|문서/참조 검증. 의미 품질 채택 아님|
|020 실패/평가 고정|019|private manifest,공개 합성 controls,obligation mapping,예비 비용/packet 상한|평가 기대·분모·출처/상한 고정; 실제wire/profile preflight는021/022|
|021 B1 opt-in|020|graph/request/adapter/validation/cost 경로|무료회귀·Factory 통과,legacy보존; 새유료/기본값변경 없음|
|022 A/B1/C 비교|021|동결 결과·전이·accept/reject/inconclusive DEC·실청구|등록 비교와 결론 기록 시 실험 완료. 실패/미결정은 알고리즘승격hold,모든arm부적합이면후속livehold|
|023 검색/규모|022|독립검색비교·전체999 계획·3000 계획/무료상한검사|실제3000은007이후 별도계획;120cap으로453완료금지|
|024 제품 복구|020|실제mvp 브라우저 회귀·UI/intent연결·CI|위경쟁/오류 회귀 통과; 실제사용자 검증은TASK012|
|005→006→007|022,023 이후 동일설정|기존G1→G2/G3→G4|기존r5/fact/runtime원계약 그대로|
|012 전체 제품|007,011,024|실제bundle·원가·초행사용|핵심3과업 유용성/복구,지속접근,미결blocker없음|

모든 구현 PR은 TASK/DEC,변경 계약,회귀 결과,미실행 live 범위를 포함한다.
CI 통과·문서 병합만으로 DEC-013 의미 채택이나 r5 완료를 표시하지 않는다.

## 9. 재개·마이그레이션·롤백

1. AGENTS →MVP_SPEC →SPEC_WORKFLOW →`PYTHONPATH=src:tests:. python tools/check_mvp_spec.py --resume`.
2. TASK-020부터 시작하고 이번 설계·새 실패 원본을 확인한다. 하위 모델은 자신의 요청을 code/test 변경에 한정한다.
3. `source_evidence_protocol`이 없는 기존 plan은legacy. 신규값은명시적opt-in,unknown은거절한다.
4. 신규artifact root/plan/hash/version으로 격리한다. 기존실험·원문·receipt·ledger를 덮지 않는다.
5. 비교 합격 후에만 새 bundle을 게시한다. 기존session은자신의analysis revision을 계속사용한다.
6. 롤백은legacy protocol/이전bundle선택이다. 이미 지출한비용·새실패기록·사용자저장작업을되돌리지않는다.
7. context compact 뒤 같은 resume를 실행한다. 진행중 executor가없으면 RUNNING이라고기록하지않는다.

새 실패가 나오면 개별prompt수정 전에 obligation/case class로 묶어 영향·대안을 기록한다.
이 설계는 모든 오류를 미리 없앤다는 약속이 아니라, **같은 원인을 반복 수정하며 비용을 쓰는 루프를
유한한 비교와 명시적인 채택/보류 결정으로 바꾸는 기준**이다.
