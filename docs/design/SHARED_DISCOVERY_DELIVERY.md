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


## 실제96 실행의 종료와 남은 문제

Sol/common typed v3 고정96 개발실행은584개의 유료응답, $1.34735548 뒤 중단됐다.
앞선24개 제안 $0.02544198까지 동일trial 누적 $1.37279746이다. 잔여 $0.12720254로
다음 요청의 고정가격·wire 최대예약 $0.12762를 감당할 수 없어 전송 전에 거절했다.
실패 요청에 대한 장부 호출0, 전체 예약/미확정0이다. 모델/전송 오류나 최종 의미검사 실패라고
바꿔 표현하지 않는다. 이번 trial 한도를 늘리거나 새 이름으로 초기화하지 않는다.

전체96 원문의 context/world, 첫288쌍 지지검사는 끝났다. 추가192쌍 비교를 포함한 총480쌍 중
350쌍만 판정했다. 마지막까지 독립검사를 통과한 **부분 지지**는 후보 순서대로1/2/4/2/0이다.
3명 이상을 가진 것은 한 후보뿐이다. 논거 감사·최종 Agent compiler·실제3질문까지 도달하지
못했으므로 최종0Agent 판정이나 새 bundle 품질검증 성공으로 기록하지 않는다.
기존 합성자료 제품 화면은 유지하며 실제96 제품 테스트의 추가호출0이다.

저장된 같은 plan 응답만 읽는 무료 host 투영으로 첫288쌍과 추가192쌍 계획을 재현했다.
새 모델호출0이며 fresh 전체 실행이나 독립 사람평가가 아니다. 부분 raw 지지 중 금액조건,
개인경험/미래계획, bare agreement, 부모의 입장 전이를 별도 검토 대상으로 보존했다.
검토 표시만으로 모델 응답이나 최종 지지 수를 지우거나 바꾸지 않았다.

### 실행 전에 빠졌던 비용 검토

실제96 비용 중 원문·후보 raw 비교350회가 약$0.7962, source context/world192회가 약$0.3843이다.
공통제안5개라는 수만으로 후속 실행이 저렴하다고 추정할 수 없다. 현재 관측 평균으로 남은130쌍만
추가해도 실제96 membership까지 약$1.64가 예상된다. 추가 own-evidence·논거·사실·runtime은
제외한 추정치이며 가격 보장이나999개 실측값이 아니다. 최초 $1.50 계획은 전체 호출계획에
대한 이 검토가 부족했다. hard cap은 지켰지만 한도 내 전체 완료 계획으로는 부적합했다.

다음 유료 실행 전에는 전체 원문/후보·검색/확장 pair 수·stage별 입력/출력예약·기존실측비용·
아직 측정하지 않은 후속단계를 먼저 제시한다. 제안만 확인한 시점에서 전체완료 비용을 검토하고,
작은 표본의 Agent 가능성·원문별 근거/조건/유형을 무료 검사로 대조한다. 값이 부족한 항목을0으로
넣어 예산 내라고 승인하지 않는다. 판정 batch화와 중복관측 제거는 비용 후보이며 아직 구현/채택하지 않았다.
이번 부분 결과만으로 좋은 모델이 불필요하거나 모델을 더 좋게 바꾸면 해결된다고 결론짓지 않는다.

PR77의 공통/방향성 연결과 PR78의 제품 동일예산/wire예약 수정은 Ubuntu·Windows CI를 통과해
main에 병합됐다. 관련Factory635·제품80 오프라인 검사는 실제96 완료나 정식gate를 대신하지 않는다.
정식G1 실패와G2/G3/G4 admission 차단, 999개/60% 활용과 사람평가 미검증 상태는 유지한다.
