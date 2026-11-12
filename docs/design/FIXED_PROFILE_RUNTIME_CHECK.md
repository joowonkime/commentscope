# 고정 Agent 입력의 실제3질문 검증

TASK-022 / REQ-003·008·010 / DEC-025. 현재 사용자의 중단 후 계속 구현/테스트 지시를
고정된1개 Agent의 기존3질문에 한정해 구체화한다. 전체 Factory 재실험이 아니다.

- 입력: PR98의 source-role policy로 재결합한 C 전체 저장 기록의 bundle.
  Agent1개·유효 지지4개·허용 항목7개를 고정하고 manifest/원문/claim hash를 보존한다.
- 질문: 기존 runtime_probe의 position, reasons, missing 세 문구·순서·프로필/schema를 그대로 쓴다.
  표준 GroundedSession/RemoteSession을 사용하며 신규 물리 호출 최대3개, 재시도/fallback0이다.
- 배정: 기존 C와 같은 Sol/OpenAI·reasoning·가격 상한을 사용하고 현재 provider/키 상태를 확인한다.
  새 제안·지지/graph·사실·embedding 호출과 임의 질문은 실행 전에 차단한다.
- 코드: PR98의 exact-head Ubuntu/Windows 성공 및 소스 tree 일치를 확인한 별도 checkout에서 고정한다.
  launcher SHA·source code SHA·입력·정책·키 파일 hash·CI 증거를 실행 plan에 결합한다.

## 실행 시간과 금융 이력

원 C/B의 종료 plan·기한은 그대로 보존한다. 현재 계속 지시에 근거한 **새 runtime-only 실행 시간**은
등록 시점부터 최대1시간이며, 이3질문 이외의 과거 미완료 작업을 재개하지 않는다.
금융 집계는 같은 누적150달러 DB/계정/opening·원 금융 owner를 유지한다.
새 owner·예산 초기화·별도 소액 승인 절차는 없다. 과거 금융 행은 cutoff/hash로 대조하며,
원 누적 지출과 보수 차감을 환급하지 않는다. 실제3회 비용만 그 장부에 추가한다.

실행 전에 변조 plan, 만료 시간, 다른 단계/4번째 호출/다른 질문을 차단하는 무료 통제를 확인한다.
표준 checkpoint·정산 영수증·quota·HTTP 자원 guard를 적용한다. 오류/미정산이면 멈추고
같은 질문을 새 요청으로 재시도하지 않는다. 새 실행에서도 원 graph 생성 응답은 재호출하지 않는다.

## 결과를 판정하는 범위

질문1·2가 실제 허용 입장/이유를 선택하는지, 질문3에서 없는 비용/실측 수치를 보류하는지 원문과 대조한다.
실제 응답·인용·선택 role·개인 예측의 비사실 지위를 기록한다. 하나의 Agent이므로
다중 Agent 이력 분리나 그룹 대화 성능은 이 실행으로 입증하지 않는다.
서로 다른2 Agent·전체999/r5·독립 사람 gold·3000단가/속도·초행 TA 사용성도 미검증이다.
현재 이 문서는 실행 준비 계약이며 실제 결과·청구는 실행 후 별도 증거로 추가한다.


## 실제 완료 결과 — 2026-11-13

PR98 검증 소스f645657의 Ubuntu/Windows 각각2687개가 통과했고, main18b0030과 전체 tree가 같음을 확인했다.
분리 checkout에서 현재1Agent/4지지/7항목 bundle을 그대로 실행했다.

| 질문 | 실제 상태 | 원문 대조 |
| --- | --- | --- |
| 입장 | answered,1항목 | 지지4개의 공통 가치 입장 |
| 이유·조건 | answered,2항목 | 한 출처의 빈곤/노동 동기 예측, 각각 member_source_count1·비사실 지위 유지 |
| 없는 비용·사고감소 실측 | abstain,0항목 | 숫자를 추가하지 않음 |

신규 물리 호출은 정확히3회, 실청구는 **0.0106315달러**다. 새 source/graph/지지/fact/embedding 호출은0이다.
세 응답의 모든 인용 구간을 원문과 대조했고, 금융 call ID의 실제 plan/request/deployment/provider-response
결합도3건 모두 일치했다. 과거 cutoff까지의 금융 행 hash는 전후 동일하며 신규 money owner는 없다.
예약/미정산0이다. 이는 coding agent의 원문/기계적 대조이며 독립 사람 gold나 다중 Agent 검증은 아니다.

20:57UTC API 관측은 누적24.74991794/잔여125.25008206달러다.
내부 장부는 보수 차감6.52865495를 유지해 누적31.24102029/잔여118.75897971달러다.
원 금융 scope 누적219회/5.8225344달러이며 원 C/B 결과·종료 기한은 보존했다.

초기 준비에서 checkout 완료 전 import를 시작해 tools 모듈을 찾지 못한1회 오류가 있었다.
실제 provider 호출/예약 전이었고 plan 생성도 없었다. checkout 완료 후 동일 고정 범위를 새로 준비했으며
모델 질문을 재시도한 것이 아니다. 이후3턴은 정상 완료했다.

현재 Agent 수는 여전히1개이며 최소2개 목표는 미달이다.
같은6후보/999풀의 [신규104쌍·69출처 확대안](SOURCE_SEARCH_EXPANSION.md)은 아직 실제 실행하지 않았다.
이3턴의 실행 비용을 전체 검색·수천 댓글·그룹 대화·TA 사용성의 단가/합격으로 일반화하지 않는다.
비공개 정본: runs/source-role-applicability-20261113-v1/runtime-check의 completed.json,
validation-manifest.json, semantic-and-finance-review.json, 원 calls/checkpoints와 같은 owner 장부.
