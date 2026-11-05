# 논거 전제 관측의 Factory 연결

TASK-005/006, REQ-001/002/003/008/010, DEC-007. 2026-11-06 사용자 요청:
기존 audit 연결 → 미사용 사례 → fresh 합성12 → 실제24/96까지 순차 실행한다.
기존 $50 공유 장부를 유지하며 이번 작업의 자율 실행 상한은 $8, 최대7시간이다.
이 상한은 사용자가 새 $8을 별도로 지정했다는 뜻이 아니라 승인 범위 안의 보수적 실행 제한이다.
과거 $5 cycle·첫 Jev trial의 기한/모델/장부를 수정하지 않는다.999개와 프론트는 이번 범위 밖이다.

## 책임과 입력

새 opt-in protocol은 GPT source audit의 entity/time/conditions/kind/authorship/function/
language/whole-source coverage, 별도 owner/world/core fidelity, 사실 NLI와 Agent 자격 검사를 유지한다.
기존의 단일 dependency_fidelity 질문만 **blind Jev 전제 관계 관측 + host 집합 비교**로 대체한다.
GPT source-only 요청에서는 requires/core_requires_for를 제거하고 전제 승인도 요구하지 않는다.
다른 source/관계/생성/runtime 호출의 GPT deployment와 기본 split5는 바꾸지 않는다.

Jev 입력은 전체 원문·부모(문맥 전용)·모든 literal unit·대상 literal unit 또는 실제 core 본문이다.
이전 kind/role/requires/core_requires_for, 기대값과 평가 case ID는 전달하지 않는다.
각 premise의 fact 여부·작성자 귀속·대상을 도출하는 필수 사실인지와 전제 누락을 관측한다.
개인 가치 이유·정책 적용 조건과 사실 전제를 구별한다. core에는 실제 core 본문을 제공한다.
같은 원문·대상은 한 관측을 재사용하고 서로 다른 선언 그래프를 host에서 비교한다.
질문은 최대16개씩 나누되 전체 원문/후보 inventory를 매 요청 보존한다. 입력이 한도를 넘으면
명시적으로 보류하며 자르거나 빈 전제로 승인하지 않는다. 선택지 순서를 포함한 wire hash를 보존한다.

## 결합과 실패

별도 raw 관측 영수증·모델/provider·정확한 요청·source/core/contract hash를 audit에 결합한다.
requires와 core_requires_for의 방향별 정확한 집합, fact/자기 귀속, 누락/불확실을 host가 비교한다.
관측이 빠졌거나 다른 원문/core/모델의 영수증이면 결합을 거부한다. 전제 없음은 관측 완료 후에만 허용한다.
기존 DAG/closure·출처 구간·owner·사실 검사는 그대로 남는다. 전제 거절 시 Agent 전체 보류 규칙을 완화하지 않는다.
이전 split5/split6 영수증을 새 protocol로 이름만 바꾸어 승인할 수 없다.

정상: 빈 사실 전제를 가진 가치 이유, 올바른 사실 추론, 조건 보존, 자기 주장과 인용 구별.
부정: 누락/오연결 전제, 부모 사실 차용, 미표현 조건, 불완전 source coverage, 불확실 관계,
다른 core/원문/옵션 순서 영수증, 부분 관측, 확정 과금 후 의미 거절, 미확정 비용 재호출.
모델 confidence는 정답 확률로 사용하지 않으며 임의 threshold나 자동 fallback/재시도는 없다.

## 실행과 채택

1. 오프라인 회귀와 기존 Factory 필수 검사를 통과한다.
2. 결과를 보기 전에 고정한 새 주제·한국어·인용/부모·조건·사실 추론의 미사용 사례를 제한 실행한다.
   기존2관측/4선언 결과는 독립 전이 사례로 재집계하지 않는다. 중대한 오승인 시 확대 중단한다.
3. 동일 코드/전체 role map/자료로 fresh G1을 실행하고 모든 원문·지지·논거·Agent·각3답변을 검토한다.
4. G1 합격 시 실제24 G2, 합격 시 별도96 G3를 수행한다. r5 분모/기준을 유지한다.

각 계획은 새 scoped authorization의 hash와 공유 ledger를 결합하고 모든 GPT/Jev 요청을 같은
총$8 money owner로 예약/정산한다. provider 가격·기한·자료 만료·자원·과금 불확실을 실행 전 검사한다.
완료된 체크포인트 재개만 허용하고 fresh gate 간 모델 응답을 재사용하지 않는다.
후속 gate admission은 단일 GPT model뿐 아니라 Jev 배정/adapter 계약까지 동일해야 한다.
실제 의미 실패·예산·자료 만료로 중단되면 산출물과 비용을 보존하고 해당 gate를 미완료로 기록한다.
기본 production 배정의 자동 승격이나 $50 안의 전체 MVP 완성을 보장하지 않는다.

## 현재 구현과 검증 범위

`source-argument-observations-jev-graph-20261106-v7`을 명시한 free/raw 실행에서만 활성화한다.
전제 관계는 `argument_dependencies`, 기존 원문 fidelity 결합은 `argument_observations`,
같은 공유 money owner/기한/role binding은 `scoped_authorization`이 담당한다.
첫 trial의 $0.10 한도와 기본 split5를 유지한다. 재개는 attempt별 resource 기록과 같은 plan checkpoint를 쓴다.

PR65 구현에서 필수 Factory515개, 연결/회계26개, 명세16개의 오프라인 검사를 통과했다(중복 포함).
기존 G1 논거8원문의 신규 typed 입력을 무과금 구성해16요청 전부28kB 한도 안임을 확인했다.
이는 과거 응답을 새 protocol로 승인하거나 fresh G1을 실행한 결과가 아니다.
새 전이는 합성6원문/최대12물리요청·별도$0.20 subcap으로 고정했다. 기대값은 provider 입력에 없다.
최초 시작은 호스트 가용 메모리가 기존1.5GB 기준 아래라 호출 전에 보류됐다. 이후 재개 결과는 아래와 같다.
다른 앱/다른 대화의 프로세스를 종료하지 않는다. 이후 G1/G2/G3는 아직 미실행이다.

## API 전용 실행의 자원 계약과 실제 전이 결과

2026-11-06 사용자가 현재 메모리와 OpenRouter 사용 시 메모리가 필요한 이유를 확인하도록 요청했다.
가용 메모리2327MB로 회복된 뒤 **기존 코드·계획·같은$8 money owner**에서 전이를 재개했다.
6원문/12물리요청, 실제$0.000916062,5원문 기대 일치/1원문 실패, 예약·미확정0이다.
한국어 T6는 local 사실전제와 누락/오연결 변형을 올바르게 구별했지만 core의 사실 재진술U3 연결을
필수 전제로 관측하지 않았다. 같은 형태의 영어 T5도 해당 선택은 necessary0.51/none0.48로 근소했다.
한국어는 necessary0.40/none0.56이었다. confidence를 정답률로 해석하지 않는다.
동일 주장/재진술과 추론의 필수 사실 전제를 같은 relation으로 묶은 계약의 모호성이 의심되며,
이 결과만으로 한국어 전체 성능이나 더 좋은 모델이 필요하다는 결론을 내리지 않는다.
기대값을 바꾸거나 실패를 제외해 합격 처리하지 않는다. all-pass 미달로 G1/G2/G3 확대는 중단한다.

기존1536MB floor는 로컬 embedding/NLI를 포함한 실행용이며 OpenRouter의 서버 모델 요구량이 아니다.
Jev 전이 경로는 모델을 로드하지 않는데 같은 floor가 적용됐다. 합성28kB 입력·1.9MB JSON 영수증으로
실제 disposable worker를 무과금 측정한 Linux RSS high-water 합은 약74MiB였다(torch 로드/네트워크0).
이는 측정한 경로이며 최악 메모리 보장은 아니다. 새 HTTP-only profile의 공학적 floor는256MB로 고정한다.

- `host-headroom-0.1`/1536MB: 전체 Factory와 로컬 모델 경로에서 그대로 유지한다.
- `http-only-headroom-0.1`/256MB: 모델을 로드하지 않는 typed HTTP 전이 경로에서만 명시적으로 사용한다.
- 기존 commit headroom1GiB·디스크6GiB·관측 실패 중단·진행 중 요청 정산/체크포인트·가격/예산/기한은 유지한다.
- 새 전이 plan에 workload와 resource_policy를 고정하고 validate/replay에서 정확히 대조한다.
  다른 policy로 이름만 바꾼 plan이나 혼합 Factory의 HTTP-only profile을 거부한다.
- 자원 profile 변경은 semantic 선택지/관측/기대값을 수정하지 않는다. 이전 실패 영수증은 원래 동결 코드로
  보존하며 현재 코드의 새 전이 또는 G1 합격으로 승계하지 않는다. 이번 수정 후 유료 재시도는 하지 않는다.

정상: 가용512MB에서 HTTP-only 경로는 통과하되 혼합 Factory는 중단한다.
부정: HTTP-only256MB 미만, commit/disk 부족·관측 실패, 임의 floor 변경·잘못된 workload/profile은 중단한다.
관련 자원·회계·재개·명세51개와 필수 Factory516개 오프라인 검사를 통과했다(중복 포함). 자원 수정으로 위 전이 실패를 합격 처리하지 않는다.
