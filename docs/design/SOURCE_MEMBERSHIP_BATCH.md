# 원문별 membership 전송 최적화

TASK-017, REQ-001/002/008/010, DEC-008. 구조v1의 논리 책임을 유지하는 opt-in transport다.
프로토콜: `source-membership-batch-20261110-v1`. scalar 기본값과 과거 영수증은 보존한다.

## 입력과 판정 계약

원문 한 개, 그 원문만의 독립 source-context/world 관측, 최대6개의 서로 다른 후보와 각 후보의
독립 world 관측을 전달한다. 원문/부모/영상 문맥은 한 번만 보내고 후보는 C1..Cn으로 주소를
부여한다. 각 행은 기존 WORLD_CONTEXT 관측 schema와 동일하며 다른 후보를 근거로 쓸 수 없다.
후보 전체가 unrelated여도 유효하다. 후보 간 상대 선택이나 지지 개수를 강제하지 않는다.

응답은 모든 행 ID가 정확히 한 번 있어야 한다. 누락/중복/외부 ID/잘못된 관측은 전체 packet을
보류하고 scalar fallback이나 자동 재호출을 하지 않는다. 각 행은 기존 host bind의 귀속·조건·
인용·reported descriptor·world·원문 구간 검사를 그대로 거친다. 긍정 행의 독립 route와
own-evidence 검사, 논거·사실·Compiler·runtime 검사는 유지한다.

행 proof는 원래 batch 요청 hash, 전체 응답과 입력 witness, 행 ID 및 논리 scalar 요청 hash를
보존한다. scalar API 호출이 있었다고 가장하지 않는다. 실제 transport가 있으면 원래 전체
provider 응답을 실제 deployment로 재검증한다. 합성 응답은 실제 모델 영수증이 아니다.

동일 PipelineWork 안에서 정확한 source/candidate/context/world/protocol의 완료 proof만 재사용한다.
후보 provenance가 달라지면 새 입력이다. 실패한 packet의 각 pair는 같은 실행에서 다시 보내지
않는다. 다른 run의 응답 재사용·부분 응답의 성공 승격·과거 plan 재태깅은 허용하지 않는다.

## 비용과 적용

shared/raw/typed 및 FULL_SCOPE 경로에만 명시적으로 활성화한다. nomination → initial → expansion은
각각 별도 phase이므로 N원문/K후보가 무조건 N호출이 되는 것은 아니다. 각 phase/source별 최대6개로
묶고 정확한 pair 중복만 제거한다. 물리 batch는 별도 비용 stage로 기록하며 scalar 단가를 대입하지
않는다. batch 단가 미측정이면 전체 비용 admission은 보류한다. 기존 trial/원owner/총50/시간은 유지한다.

무료 비교는 저장된 요청의 source/context/world가 정확히 일치하는 경우만 phase/source별로 묶는다.
호출 수·UTF-8 전송량·출력 예약 상한을 보고하고 달러 절감·품질 동등을 추론하지 않는다. cached token이
이미 많은 기존 호출은 호출 감소 비율만큼 싸지지 않을 수 있다. 입력 순서는 고정하고 실제 비교의
표본/모델/schema/최대예약/중단 조건을 먼저 동결해야 한다. 이번 작업은 유료 호출0이다.

## 정상·부정 검사와 채택

- 여러 후보를 독립 판정하고 source packet은 한 번만 전달한다. 서로 다른 source는 합치지 않는다.
- 행 순서 변경은 ID로 결합하고 누락/중복/외부 ID/6개 초과를 거절한다.
- source/parent/video/후보/world/응답/hash 변조를 거절하고 기존 veto와 별도 evidence 거절을 유지한다.
- 같은 pair 중복은 재호출하지 않고 실패 packet을 phase 변경으로 재시도하지 않는다.
- 기본 scalar 경로 및 합성2 Agent/각3지지 경로를 회귀 검사한다. 이는 실제 품질 승인과 구별한다.
- 비용 stage 누락/기존 scalar profile 대입은 admission을 차단한다. 실제 원가·fresh gate 전까지
  최적화 후보로 유지하며 기본값을 자동 전환하지 않는다.

구현 범위·무료 전송량 비교·실제 검증 한계는 [결과](SOURCE_MEMBERSHIP_BATCH_RESULT.md)를 따른다.

여러 후보가 같은 모델 호출에 보이므로 행들이 통계적으로 독립된 표본이라는 보장은 없다.
후보 사이의 문맥 영향과 지지 누락은 fresh 대조에서 따로 검토하며, 독립 own-evidence 요청에는
해당 원문/후보만 전달한다. 이 transport 최적화로 논리 역할의 품질을 자동 승인하지 않는다.
