# 공통 입장 제안부터 Agent까지의 계약 연결

TASK-005/017, REQ-001/002/003/008/010. 사용자 `ㄱㄱㄱ`로 후보 생성→관점 통합 수정을 재개했다.
기존 $8 owner/총$50 장부와 r5를 유지한다. 실제24개 0Agent 실패와 과거 결과는 보존한다.

## 수정할 일반 문제

기존 free 경로는 source별 완전 명제를 생성하고 동치 후보를 합친다. 실제24개에서는47개가
각각0~1명 지지에 남았다. source-only 초기 지지39개도 후속 route/범위 검토 후15개로 줄었다.
새 관점의 이유를 서로 섞거나 조건을 지워서 지지 수를 늘리지 않는다.

저장소에 이미 구현된 `shared_claims.COMMON`을 사용해 전체 원문12개 이하 묶음에서 공통 입장을
최대4개 제안한다. 서로 다른 이유를 가진 source가 같은 bare position을 가질 수 있다.
제안과 nominee는 승인/지지 수가 아니다. 기존 원문별 full-scope membership/own evidence/
세계/귀속/조건 검토를 모두 통과한 최종 문구만 실제 지지로 센다.

## 연결 경계

- `shared` + 새 shared typed audit를 명시한 실행만 새 동작이다. 기존 free/literal/contextual과
  기존 shared/audit 영수증은 바꾸지 않는다. 새 모델 역할이나 새 검증 서비스를 추가하지 않는다.
- 전체 원문을 shared proposal record에 보존한다. unshared/empty-proposal source도 원문 처리
  inventory에는 남는다. per-source extraction record가 없다는 이유로 실제 처리한 원문을
  transport 실패로 표시하지 않는다. 의미 내용의 보존/활용 여부는 별도로 검토하며 자동 승인하지 않는다.
- source context/world/후보 world와 full-scope evidence는 기존 최신 경로로 수행한다.
- 공통 core와 개별 source position의 관계는 방향성 지지다. 기존 `shared_owned_positions`로
  source 자신의 전체 입장과 필수 조건을 확인하고, 별도 Sol owner 관측에서도 방향성 지지를
  재검토한다. 동치와 혼동하지 않는다. 다른 source/부모의 이유·조건을 가져오지 않는다.
- 새 shared typed source audit는 기존 source kind/귀속/function/범위/coverage와 typed graph
  검사를 유지한다. owner/core 유형 충돌, 누락 사실 전제, world/조건 불일치는 계속 거절한다.
- `candidate_verified_subset`과 최소3명·모든 사실/주요 논거/runtime 조건을 유지한다.
  실패 source/후보를 지우거나 더 좋은 응답으로 바꿔 정식 합격 처리하지 않는다.

## 정상/부정 회귀

정상: 서로 다른 개인 이유/추가 요구를 가진3명 이상이 공유하는 입장→하나의 core와 개별 이유.
부정: only-if 지지를 무조건 지지로 전환, 개인 계획을 보편 명제로 전환, 예측을 요구로 전환,
인용/반대의 endorsement 승격, source kind나 필수 fact premise 누락, 다른 source/owner 영수증,
미확정 세계/조건, 공통 후보0개인데 고정 Agent 수 채우기는 거절한다.
기존 equivalent owner 계약은 그대로이며 directional 영수증으로 바꿔 붙일 수 없다.

## 실행과 비용

코드/회귀와 필수Factory 검사 후 하나의 동결 실제24개 development 실행만 검토한다.
동일 원문24개/의미19개 또는 등록96개/의미74개·현재 재검증 snapshot·고정 generation/verification/provider를 사용한다.
새 개발 artifact는 정식 review/admission에서 수용하지 않는다. formal G1 실패를 건너뛴 정식G2가 아니다.
24/96 개발 표본과 필요한 후속 검증을 합한 이번 수정의 유료 상한은 $1.50이며 원$8 잔액 안에 둔다. 먼저 공통 제안 단계만 실행하고,
실제 지지 가능성이 없는 경우 다음 고비용 단계를 시작하지 않는다. 빈 제안/실패 자동 재시도0이다.
진행할 때는 같은 plan의 완료된 제안 checkpoint를 사용한다. 다른 실행의 의미 응답은 재사용하지 않는다.
필요한 G1 또는 제품 응답도 합계 상한 안에서만 진행하고, 최소 Agent 미달이면 제품 자료를 교체하지 않는다.
fact40의 실제6개 runtime 파일이 같으면 호환 증거만 다시 검사하고 재결제하지 않는다.

전송 adapter는 새 semantic stage 두 개를 기존 모델 배정에 명시적으로 연결한다:
`shared-discovery`→verification/core(Sol), `shared-owned-position`→generation/argument-position-alignment.
별도 owner/source/graph/fact 검토는 기존 verification(Sol)이다. adapter 자체 SHA와 매핑도 동결한다.
이는 의미 판단을 생략하거나 전용 서비스를 쓴다는 뜻이 아니다. 기존 공유 장부/예약/정산/재개/자원 기준을 그대로 쓴다.

## 제안 단계의 실제 관측과 명시적 보강

원래 shared v2 제안만 실제24개에 실행했다(3calls/$0.02544198). 후보2개 중 하나가
요구와 예측을 섞은 disjunction이라 후속 membership/논거는 실행하지 않았다. 기존 실패·비용은 보존한다.
새 `COMMON_TYPED` v3는 각 후보의 `assertion_kind`를 value/prediction/fact 중 하나로 요구하며,
서로 다른 주장·모달리티를 묶어서 공통점을 만드는 것을 금지한다. 이 kind는 생성 제안이며
독립 source/core 관측이나 사실 검증을 대체하지 않는다. 기존 v2 영수증을 v3로 이름만 바꿀 수 없다.

공통제안의 배정은 기존 Sol로 고정한다. 나머지 generation/verification 모델은 유지한다.
등록된 별도96개 표본에서도 먼저 제안 단계만 읽고 실제 원문과 대조한다. 표본을 결과에 맞춰
교체하거나 새 유형을 합격으로 간주하지 않는다. 24개와96개·향후 G1/제품 응답은 같은 trial
시작 지출을 공유하며 합계1.50를 넘길 수 없다. G3는 금융 scope 표기일 뿐 정식G3 합격이 아니다.
