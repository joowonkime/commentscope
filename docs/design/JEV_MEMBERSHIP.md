# Jev raw membership: opt-in 구현·비용/정확도 비교 계약

TASK-005/017, REQ-001/002/003/008/010, DEC-009. 프로토콜 `jev-world-membership-20261110-v1`.
사용자가 역할 분리의 실제 진행과 비용·정확도 모두의 검증을 요청했다. 첫 변경은 F3 M1만이다.
기존 발견/문맥/Sol M2/논거/사실/Compiler는 유지하고 새 배정은 명시적 opt-in이다.

## 입력·질문·결합

원문·부모·영상·최종후보·독립 source-context/source-world/candidate-world를 기존 WORLD_CONTEXT와
동일하게 결합한다. 호스트의 고정 계약과 읽을 데이터를 분리하고 평가 ID/기대값/기존 모델 답은 보내지 않는다.
기존 raw의 모든 enum, descriptor ID별 사용 관측, 각 원문 segment의 근거 선택을 질문 manifest로 작성한다.

기존 Jev 모델/가격/provider/질문16개·wire28kB·선택지8개 제한은 그대로 사용한다.
9개 source-use 값은7개+other 및 나머지+other의 두 choice로 표현한다. 모든 enum을 일반적인
조각들로 완전히 덮고, 정확히 한 조각에서만 실제 값을 선택해야 한다. 모순/누락은 전체 pair 보류다.
임의 pass/빈 값으로 누락 필드를 채우거나 기존 global cap을 늘리지 않는다.

질문별로 state+question UTF8와 기존 provider margin을 보수적으로 합한 입력 상한도 context 안에
들도록 packet을 분할한다. 전체 state는 유지한다. 질문/원문을 자르지 않고 모든 packet이 있어야 bind한다.
원래 physical payload/전체 응답·모델/provider·질문/선택지 순서/manifest와 전체 원문을 proof에 결합한다.
scalar Sol 영수증을 만든 것처럼 표시하지 않는다. host가 복원한 출력에 기존 raw.bind guard를 적용한다.
불확실한 근거 선택은 긍정 지지로 승인하지 않는다. 긍정만 기존 독립 Sol M2를 계속 거친다.

## 배정과 실패

`membership_judge_protocol`과 별도 `membership_deployment`로 M1만 선택한다. 기존 Sol
`membership_batch_protocol`과 최초 동시 선택은 거절한다. runner의 typed decide가 없으면 시작 전에 거절한다.
같은 실행의 정확한 pair는 재사용하며 실패한 의미 입력은 phase/metadata 변경으로 다시 결제하지 않는다.
후보 변경·누락 질문·변조 응답·잘못된 source/world/provider·의미/용량/전송 실패는 보존하고 자동 fallback/재시도하지 않는다.
기존 일반 Factory와 Sol/legacy Jev 계약은 회귀를 유지한다.

## 비용과 정확도는 따로 기록하고 함께 판단

정확도는 사전 고정한 관계/최종 raw 지지 기대값으로 측정한다. 잘못된 지지, 유효 지지 누락,
불확실/구조 보류를 나누고 Jev-Sol 일치도를 정답률로 쓰지 않는다. labels는 입력과 분리한다.
기존 실제 Sol 관측과 비교하는 경우 원래 입력과 확정 청구를 검증하며, 과거 cache/시점이 다른
비교임을 표시한다. 새 Jev의 모든 질문/packet 비용을 포함한다. 한 영수증을 여러 번 합산하지 않는다.
독립 사람 평가/다른 영상 일반화/전체 r5는 별도이고 작은 component로 production을 자동 승격하지 않는다.

유료 component는 먼저 fixture/모델/provider/wire/정답/코드/전체 최대 예약/중단 조건을 동결한다.
기존 owner8·global50·원 trial1.50의 시작 차감과 모든 과거 비용을 그대로 적용한다.
현재 사용자의 실제 진행 요청은 새 bounded resume window로 기록할 수 있으나 금전한도를 올리지 않는다.
과거 시간/plan을 수정하지 않는다. 당시 잔여 약0.1272보다 전체 최대 예약이 작아야 첫 측정에 진입한다.
whole Factory/G1~G4 확대는 기존 비용/선행/금융 gate를 별도로 통과해야 한다.

정상/부정:9값 enum 완전성·overflow 모순, descriptor/world/조건/귀속 veto, 근거 불확실/24개초과,
질문/packet 누락·중복·순서·응답/원문 변조, 동일 pair 재열람/실패 재과금, typed stage 과금1회,
Sol 기본 경로와 합성2Agent/각3지지 및 M2 거절을 검증한다.

## 첫 고정 component

공유 fixture의 합성6건은 영어/한국어의 직접 지지·필수조건 보존·조건 누락·명시적 반대·
인용·지칭 불충분을 포함한다. 실제5건은 기존 Sol raw 관계5종에서 각각 한 건을 사전 선택하며,
기대 관계/지지 여부를 새 응답 전에 별도 파일에 고정한다. 이 층화 표본은 실제 댓글 전체의
분포가 아니며 전반 정확도를 추정하는 표본도 아니다. 기존 모델과의 일치도를 정답으로 삼지 않는다.

`tools/jev_membership_probe.py`는 원래 Sol 입력/영수증·고정 annotations를 검사하고,
11건의 모든 질문과 최대 예약을 기존 trial 잔여에 대조한 뒤 plan/code/input을 동결한다.
원문·annotations·장부·결과는 `runs/`에만 저장한다. 공유 합성 fixture의 ID/기대값도 API에 보내지 않는다.
새 응답은 M1만 실행하고 기존 upstream 관측을 그대로 입력하므로 fresh Factory나 M2 실제 품질 시험이 아니다.
완료 후 원본 영수증 재결합은 추가 호출0이며, 실패 사례를 바꿔 다시 유료 측정하지 않는다.

관계 일치 수, raw 오지지, host 검사 후 오승인, 유효 지지 누락, 구조 보류와 실제 총비용을 각각 보고한다.
개발자가 사전 작성한 기대 판정은 독립 사람 gold가 아니다. 작은 실험의 성공 여부로
production 기본값·전체755/453 기준·정식 gate 차단을 변경하지 않는다.

첫 실제 측정과 채택 보류는 [결과](JEV_MEMBERSHIP_RESULT.md)에 기록했다.
