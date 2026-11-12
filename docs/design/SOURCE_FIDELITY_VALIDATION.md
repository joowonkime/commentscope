# v3 원문 감사의 고정 비교·비용 계획

TASK-022 / DEC-013·016·017 / REQ-001·002·003·008·010.
2026-11-12 사용자 진행 지시에 따른 **무료 자료·계획 동결**이다. 모델 응답/의미 품질 결과가 아니다.
구현은 [v3 계약](SOURCE_FIDELITY_AUDIT.md), 이전 실패/보수 과금은 [종료된 비교](SOURCE_EVIDENCE_TRIAL_RESULT.md)에 보존한다.

## 검증할 질문과 순서

1. 제안이 원문과 맞을 때 auditor가 과도하게 보류하는가? 왜곡됐을 때 그대로 동의하는가?
2. 같은 생성 모델에서 legacy와 v3의 출처별 입장·이유·조건 보존이 달라지는가?
3. 전체 eligible source를 처리했을 때 서로 다른 Agent와 자기 이유 답변을 만들 수 있는가?

생성모델 효과를 구조 효과와 섞지 않는다. 첫 v3 생성은 기존 `openai/gpt-5.2`,
auditor/후보 연결은 기존 `openai/gpt-6.1-sol`의 OpenAI 단일 endpoint/low reasoning을 유지한다.
Sol 생성 arm은 이번 첫 비교에 넣지 않는다. Jev M1·Sol M2와 발견 결과도 입력 이력으로 고정한다.
이 선택은 최적 모델의 확정이 아니며, 좋은 생성 모델만으로 해결되는지는 여전히 미검증이다.

## 1단계: 정상·왜곡 제안의 짝 비교

합성8가족/16요청: 부정, 가능성, 희망/실제, 귀속, 조건 누락, 이유 관계 누락,
fact0으로 숨긴 전제, 집단·수량·시점·변화의 범위 누락.
가족마다 같은 원문의 충실한 제안과 왜곡 제안을 함께 등록한다. 기대값/정상·왜곡 표시는 모델 입력에서 숨긴다.
전체 원문/제안/기존 v3 prompt/schema/output·reasoning 상한을 그대로 사용한다.
host가 이미 거절하는 잘못된 주소를 모델의 왜곡 탐지 성공으로 세지 않는다.

- 정상: 실제 model receipt를 결합한 전체 source의 `complete` 비율을 보고한다.
- 왜곡: auditor가 반환한 fail/누락과 host 보류를 분리한다. unknown은 보류지만 명확한 탐지 성공은 아니다.
- 왜곡이 `complete`가 되거나 정상 출처 통과가0이면 다음 유료 단계로 넘어가지 않는다.
- source 보류와 사전 등록한 문제의 탐지를 분리한다. 다른 항목의 fail만으로 해당 왜곡 탐지 성공을 세지 않는다.
- 실제16응답의 schema/영수증이 모두 유효하고, 왜곡 false approval0·정상 보존≥5/8·등록 문제 탐지≥5/8일 때만 제한 profiling 후보가 된다.
  나머지 unknown은 보류로 기록하며 정확한 탐지로 세지 않는다. 이 최소선은 r5/알고리즘 채택 기준을 바꾸지 않는다.
- 가족별/짝별 결과와 전체 분모를 기록한다. 원인 하나에 맞춰 prompt를 고치고 재실행하지 않는다.

이 소규모 통제는 다음 profiling을 허용하는 최소 안전 점검이다. 알고리즘 채택이나 r5 합격이 아니다.
8가족 밖의 의미 현상·실제 모델 일반 정확도까지 검증했다고 보고하지 않는다.

## 2단계: 실제 출처의 비용·이유 보존 profiling

이전999에서 고정한 eligible6후보/19출처/25관계를 유지한다. 성공한3출처를 골라 Agent로 승인하지 않는다.
먼저 길이·root/reply 등 입력 특성으로 고른 최대3출처를 profiling하고, 실제 응답과 wire·토큰·비용·지연을 저장한다.
이3개는 개발용이며 전체19 비교나 Agent 품질 판정의 대체가 아니다. 선택은 새 모델 응답을 보기 전에 동결한다.

v3 stage profile이 생기기 전 전체19 비용은 null이다. 측정 후 남은19 처리/필수 사실/Compiler/runtime의
각 비용을 별도로 계산하고, 미측정 stage를0으로 채우지 않는다. 조건을 충족한 범위만 다음 실행 후보로 만든다.
예산에 안 맞으면 전체 비용 검토를 보류하며, 남은 돈을 실패 사례 반복 호출에 쓰지 않는다.

legacy+PR92 비교는 이전A의 미완료 결과와 구별한다. 기존 A322응답을 수정 후 complete 결과로 재사용하지 않는다.
공정한 paired 비교에는 동일 원문/후보/생성·검증 모델과 새 설정의 실제 결과가 필요하다.
이전 A의 출처/비용/실패는 배경 이력으로만 보이며, v3의 새 응답과 섞어 순개선을 계산하지 않는다.

## 3단계: 개발·전이와 실제 Agent

기존 개발48/전이48의 ID·hash·thread 분리를 보존한다. 개발의 기대값 유무와 주석 출처를 확인한다.
전이는 같은 corpus의 annotation-blind 표본이며 새로운 domain이라고 부르지 않는다.
기대값이 없는 source-target 관계는 미평가이고, 기존25관계의 coding-agent 주석은 독립 사람 gold가 아니다.
기존 최소 이유 관계 R≥20·순회복 `max(3,ceil(0.10*R))`·유효 support/proposition 순손실0·층별 이유 순손실0을 유지한다.
자료/주석이 부족하거나 paired 실행이 미완료면 채택은 inconclusive다.

전체 source/필수 사실/Compiler 검사를 통과한 모든 자동 Agent를 확인한다.
서로 다른2 Agent·각 유효 지지3개와 각3질문(입장/이유/없는 구체 수치)을 검사하며,
인용·조건·자기 이유와 필요한 abstain을 함께 원문 대조한다. 질문 수만 채워 유용성을 승인하지 않는다.
전체999의453/755 활용·G2/G3·3000 비용·속도·TA 초행 usability는 별도 검증으로 남는다.

## 비용·권한·중단 조건

사용자 지적으로 **실험별6달러 제안/확인은 철회**했다. [누적 예산 revision](TEAM_BUDGET_REVISION.md)에 따라
이미 증액된 팀 누적150달러를 사용하며,50달러 내부 장부를 동일DB/계정/opening에서 명시적으로 반영한다.
이전5달러 owner의4.7406401 차감과 미사용0.2593599,과거 보수 차감·owner별 상한은 그대로 보존한다.

사전 도구는 canonical v3 요청과 reasoning 배분 후 wire bytes·가격 ceiling으로1단계의 전체 예약 상한을 산출한다.
고정16요청 합계5.405045,단일 최대 예약0.341860을 더한5.746905를 현재 누적 잔여/키 잔여와 비교한다.
이는 **보수 예약 상한**이며 예상 실제 청구나 stage 실측 단가가 아니다. 과거5/6달러 what-if 결과는 이력으로만 남긴다.
source/통제/판정 기준을 예산에 맞춰 줄이지 않는다. v1/v2 profile을 v3 실측으로 빌리지 않는다.
현재 endpoint 가격·지원 parameter와 키/현재 장부 잔여는 GET/동일장부 조회로 확인하고 모델 호출 수와 분리한다.

현재 policy를 사용하는 새 고정 owner·유한 기한·단계별 유한 요청 집합·코드/자료/request hash를 등록한다.
별도 소액 subcap 대신 누적 계정150달러와 현재 키 잔여를 함께 지킨다.
기존5달러 owner를 새150달러 owner로 바꾸거나,다른 단계마다 계정 지출을 초기화하지 않는다.
실제 dispatch는 기존 금융/시간/host/lock/receipt/checkpoint 제어를 사용한다.
pending/미확정 과금·가격/코드/자료 변경·다음 요청 예약 초과는 즉시 중단한다.
원 응답·실패·유실 보수 차감은 보존한다. 이번 무료 동결 도구에는 provider dispatch 기능이 없다.

## 산출물과 완료 경계

공유 파일에는 합성 통제·구성 도구·검사만 둔다. 실제 원문/후보/주석/키/장부는 private runs에 둔다.
private manifest는 source split/coverage·주석 준비 상태·전체 요청 hash·price/wire 상한·남은 미검증을 고정한다.
계획/host 검사·실제 model 평가·알고리즘 채택·MVP 완료를 각각 보고한다.

구현: `tools/prepare_source_fidelity_validation.py`, 현재 합성 자료: `tests/fixtures/source-fidelity-controls-v2.json`.
원 v1 자료/실제16응답은 이력으로 보존한다. 정상3/8·왜곡8/8보류·등록 문제7/8탐지,
실청구0.2058115달러였다. 정상 참고 주석 오류가 확인되어 모델 정확도나 과도 보류율로 해석하지 않는다.
[v4 계약](SOURCE_CONDITION_QUALIFICATION.md)은 일반조건/필요조건을 분리하고 참고 주석을 바로잡는다.
v2 통제는 이전 결과를 본 뒤 만든 개발 자료이며 독립 전이/gold가 아니다. 최소5/8·왜곡오승인0 기준은 유지한다.
현재 도구는 준비/정적 검토/진단 채점만 하며 실행 권한·유료 dispatch를 지원하지 않는다.
구 v1 실행기의5달러/세 arm 계약은 종료된 그대로 두고 새 고정 검증을 별도로 등록한다.
실제 실행에는 새 요청 집합·단계·공유 상한을 묶는 실행 등록이 필요하다.

실행 등록은 `tools/source_fidelity_validation.py`의 reconcile/prepare/run으로 구별한다.
reconcile은 명시적 credit revision과 현재 policy만 기록한다. prepare는 이전 owner를 수정하지 않고,
현재 누적150달러·동일DB·과거 지출·고정16요청/19출처·최대800개 요청·최대7시간·코드/자료를 결합한다.
후속 v4는 `prepare --money-owner <원authorization.json>`으로 동일 원owner와 최종 기한을 참조한다.
이전16요청/0.2058115달러를 포함하며 money owner·종료 시각·요청 한도를 초기화하지 않는다.
run은 실제 영수증이 있는 통제 채점 후 대표3출처를 측정하고,고정19출처 전체의 F4/필수 사실/Compiler/3질문을 진행한다.
대표 출처는 같은 request/stage의 checkpoint를 재사용한다. 다른 source/단계/코드/기한은 거절하며 유료 자동 retry는 없다.
전체19의 동작 확인도 개발48 paired/전이나 formal r5를 대체하지 않는다. 결과의 원문별 검토는 별도로 남긴다.

무료 확인 명령(비공개 실자료·키 불필요):

```bash
PYTHONPATH=src:tests:. python -m unittest test_source_fidelity_validation_plan -q
```

실제 workspace의 무료 동결 결과는 eligible6후보/19출처/25관계, 개발48개 참고 주석 존재,
전이48개와 thread 교집합0이었다. 참고 주석의 존재를 완전한 정답 준비로 승격하지 않는다.
정적 wire/context 검토는16요청 모두 통과했다. 실제 모델의16요청 통과 결과가 아니다.

읽기 관측의 API 계약은 OpenRouter의 [키 한도 확인](https://openrouter.ai/docs/api/reference/limits)과
[모델 endpoint 조회](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model)를 따른다.
실제 수치·관측 시각·원 응답은 private 파일에 보존하며, 실행 직전에는 다시 확인해야 한다.

무료 구현 검사는 새10개·관련46개(2.428초), 전체 Factory819개(285.206초)를 통과했다.
양OS CI는 PR에서 확인한다. 이 수치는 실제 auditor의 의미 탐지 성능이나 모델 청구 결과가 아니다.
