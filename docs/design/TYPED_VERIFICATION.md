# 유형과 관계를 함께 관측하는 검증 계약

TASK-005/006/011/012, REQ-001/002/003/008/010, DEC-007. 2026-11-09 사용자가 남은 MVP 전체 진행을 지시했다.
기존 구현을 유지하며 새 원격 실행에서만 이 계약을 선택한다. 기본/과거 Jev·chat record는 그대로 재생한다.
새 모델 성능이나 G1 합격은 구현·회귀 검사와 별도로 판정한다.

## 문제와 책임

기존 원격 G1은 local의 value 관측과 core의 necessary_fact 관측이 충돌해 정상 원문을 보류했다.
검증이 모순을 승인하지 않은 것은 올바르지만, 두 독립 요청의 타입 가정을 연결하지 않아 정상 보존이 불안정했다.
같은 원문의 literal units와 실제 core를 한 blind graph에 넣고 타입·귀속·관계를 함께 관측한다.
생성자가 선언한 kind/requires/core_requires_for와 이전 판정·기대값은 모델 입력에 넣지 않는다.
host는 선언과 관측을 대조하고 기존 source/owner/core/조건/사실 검사와 compiler의 veto를 유지한다.

## 그래프 입출력

- 입력: 전체 원문·문맥 전용 부모·literal unit ID/구간·실제 core ID/본문. 최대32 units,16질문 단위 분할.
- 모델 호출 전에 parser가 보존한 모든 literal node의 원문 구간이 unit inventory에 포함됐는지 검사한다.
  원문 구간이 빠졌으면 host에서 보류하며 모델 비용을 쓰지 않는다. 이것은 의미상 전제 완전성의 대체물이 아니다.
- 출력: 각 unit의 kind/authorship, 각 core의 kind, directed relation, factual coverage의 닫힌 enum.
- 관계: `restatement / necessary_fact / personal_ground / condition / reported_context / none / uncertain`.
- restatement는 같은 완전한 명제의 재진술이다. 규범·예측 재진술은 경험적 사실 전제가 아니다.
  사실 core의 fact 재진술은 직접 사실 근거로 기록하며 기존 사실 검사/closure에서 빠지지 않는다.
- necessary_fact는 asserted fact만 가능하다. value/prediction/미귀속 노드에 붙으면
  `unresolved_type_conflict`와 기존 보류를 남긴다. 잘못된 관측을 host가 바꾸어 승인하지 않는다.
- 관측된 core kind와 선언 kind가 다르거나 재진술의 양쪽 kind가 다르면 보류한다.
- 필수 전제 누락/오연결, 불완전 coverage, 불명확 관계는 계속 보류한다.
- 이 그래프는 사실의 참/거짓이나 다른 출처의 지지를 승인하지 않는다. 결과의 semantic approval은 false다.

## Owner의 world 문맥

새 owner 비교는 기존 원문/고정 owner/실제 candidate와 함께 버전 있는 문맥 정책을 고정한다.
영상 제목은 주제 metadata이며, 그 제목만으로 원문의 일반 정책 입장을 소설 속 주장으로 바꾸지 않는다.
원문·부모가 명시한 소설/가정의 범위와 필수 조건은 유지한다. Candidate가 범위를 잃으면 계속 거부한다.
문자 동일성으로 owner 비교를 건너뛰지 않는다. world 불일치·불확실·긍정 relation과 다른 basis는 계속 veto다.
새 정책의 task/record ID는 과거 정책과 다르며 legacy 기록을 이름만 바꿔 재사용할 수 없다.

## 구현·확인 순서

1. REMOTE_VERIFICATION의12종 유형/world 경계를 오프라인 정상/부정 사례로 고정한다.
2. combined graph·restatement 구분·문맥 정책을 명시적 새 protocol로 연결하고 기존 protocol 회귀를 실행한다.
3. 고정 합성 component에 한해 기존 money owner 안에서 누적 최대$0.40를 동결해 비교한다.
   최초$0.15 실행은4응답/$0.026629 후 가장 큰 요청의 예약액$0.15386을 수용하지 못해 중단됐다.
   원래 plan·비용은 보존하고, 동일 wire의4관측은 component 증거로만 대조한다. 나머지 원문만 새로 실행하며
   새 한도는 이미 쓴$0.026629를 차감한다. 모든 예정 요청의 최대 예약액을 준비 시 검사한다.
   정상 오거부를 모두 없애기 위한 전체 유료 반복은 하지 않는다. 실패/비용을 보존한다.
4. 전체 Factory 회귀와 component 검토 후 새 G1을 최대$1.50로 실행한다.
   기존2Agent/각3지지·각3질문, 고정fact40, 원문 전수검토를 통과해야 G2/G3로 확대한다.
5. 유료 대기 동안 Figma 기준 프론트를 기존 제품 API에 연결한다. 프론트 개발을 G4 이후로 미루지 않는다.

기존 총$50·과거 확정/보수 차감과 원래 G1~G3 scope$8을 유지한다. 이번 명시적 재개 window는
별도 authorization에 연결하며 원 money owner를 바꾸지 않는다. 전체999 표본 갱신은 사용자 응답을 기다린다.
G4 비용/자료/실행 계약은 G2/G3 실측 후 남은 전체 예산 안에서 별도로 동결한다.
