# 원문의 조건·이유와 논리적 필요성 구분

TASK-022 / DEC-013·016·018 / REQ-001·002·003·008·010.
사용자 계속 진행 지시에 따른 일반 표현 계약 수정이다. 단일 댓글을 통과시키는 규칙이나 gate 완화가 아니다.

## 관측과 참고 주석의 오류

v3의 실제16요청은0.2058115달러,모든 영수증/형식 유효,왜곡8개 보류/등록 문제7개 탐지였다.
사전 normal8개 중3개만 complete였지만,이 수치를 모델 정확도로 해석하지 않는다.
coding-agent 참고 주석에 비용 감소를 change=neither로,현재 반대를 world=desired로 표기한 오류,
평범한 사실 이유를 required_premise_for로 추가한 오류가 있었다. 지시/선호 speech act도 모호했다.
원 조건을 necessary로 표기한 사례는 아래 schema 문제와 겹친다.
이는 모델 실패와 별도로 확인한 참고 자료/계약 문제다. 원16응답·3/8 결과·비용을 수정하거나 재채점해 성공으로 바꾸지 않는다.

## v4 조건 관계

코드 계약은 `source-evidence-graph-20261112-v4`다.

| 관계 | 뜻 | 보존하는 동작 |
| --- | --- | --- |
| condition_for | 원문이 해당 주장을 어떤 조건/상황 아래에서 하는지 | 일반 if 등을 그 연산자와 함께 보존. 필요조건이나 충족된 사실로 승격하지 않음 |
| necessary_condition_for | 원문이 명시한 필요한 전제/선행조건 | 실제 필요성까지 보존. 모든 if를 이 관계로 바꾸지 않음 |
| reason_for | 작성자가 제시한 이유 | 이유가 fact여도 자동으로 논리적 필요 전제가 되지 않음 |
| required_premise_for | 해당 근거가 실제로 의존하는 필수 사실 전제 | 개인 전제를 전체 core의 공통 전제로 승격하지 않음 |

v3는 conditional_antecedent에 necessary_condition_for만 강제해 평범한 조건을 필요성으로 과해석해야 했다.
v4는 condition_for/necessary_condition_for 중 하나를 요구한다. host가 if/only if 등의 단어를 분류하지 않는다.
proposer가 원문에 맞는 관계를 제안하고 auditor가 원문에 없는 필요성을 추가했는지 확인한다.

두 조건 관계 모두 관련 inventory·closure·certificate의 필수 보존 조건·runtime scope에 포함된다.
기존 wire 필드 essential_condition_unit_ids의 essential은 **의미 보존에 필수**라는 뜻이며 논리적 necessary가 아니다.
edge ID 누락/unknown·불완전 전체 source·중첩 조건/표현 불가 보류·필수 사실·지지3개·Compiler는 유지한다.
조건 단위는 scope annotation이며 조건 충족 사실을 게시하지 않는다. 값/예측으로 재분류해 fact 검사를 피하지 않는다.

## 재검증과 비용 경계

새 개발 통제는 다른 문장의8가족16요청을 사전 등록하고,주체/술어·양태·세계·변화와 조건 관계를 명시적으로 주석한다.
이전 응답을 본 뒤 개선한 개발 자료이므로 독립 전이/독립 사람 gold라고 부르지 않는다.
새로운 실제 응답을 받기 전에 자료·기대 탐지 항목·기준을 동결한다.
정상 보존≥5/8·등록 왜곡 탐지≥5/8·왜곡 false approval0·16개 모두 유효 영수증 기준은 유지한다.
누락/unknown은 pass가 아니며,같은 실패 사례에 맞춰 유료 반복 수정하지 않는다.

v3 receipt/profile을 v4 증거로 재사용하지 않는다. 기존 실행은 readonly 완료 상태로 둔다.
새 실행은 원 누적150달러 **동일 money owner·동일 최종 기한**을 참조하는 supplement로 등록한다.
0.2058115달러를 차감한 채 시작하며 owner/잔액/기한을 초기화하지 않는다.
통제 통과 후 실제3출처 profiling과 전체19출처의 F4/필수 사실/Compiler/runtime을 진행한다.
개발48 paired/전이/r5/3000규모·사용자 유용성은 별도이며,이 수정만으로 개선을 주장하지 않는다.
