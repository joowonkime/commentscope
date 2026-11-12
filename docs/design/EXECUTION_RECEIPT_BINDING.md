# 동일 금융 owner 안의 실행별 정산 영수증 결합

TASK-022 / REQ-008·010 / DEC-023. 의미 품질 개선과 별개인 실행 증거 수정이다.

같은 요청 본문을 서로 다른 모델/실행에서 호출하면 money owner+request SHA는 같을 수 있다.
기존 saved_length는 이 키의 금융 행이1개라고 가정했다. 원 C는 length 오류 없이 완료됐으므로
이 충돌은 당시 실행에서 발생하지 않았으며 미정산이나 추가 지출로 보고하지 않는다.

새 PaidBudget 호출은 원 provider response를 변경하지 않고 정산과 함께 보조 receipt_bindings에
execution plan SHA·actual request SHA·deployment SHA·provider response SHA를 기록한다.
금융 call ID가 이 증거를 특정 정산 행에 연결한다. 정산과 결합 저장은 같은 transaction이다.
예산·opening·과거 calls/resolutions·보수 차감·한도를 변경하거나 과거 행에 추정 결합을 쓰지 않는다.

saved_length는 기존 checkpoint/request/raw receipt 검사에 더해 정확한 실행/모델/응답 결합이
일치하는 유일한 complete 금융 행과 금액을 요구한다. 같은 본문의 다른 모델 행은 충돌하지 않는다.
구 기록은 결합이 전혀 없고 기존 금융 행이 유일한 경우만 기존 증명을 유지한다.
모호한 과거 다중 행·다른 결합·중복 증거·unknown/예약·금액 불일치는 계속 중단한다.
원래의 실패 응답만 반환하며 출력 수리·재시도·환급·새 owner·기한 연장은 없다.

합성 검사에서 서로 다른 실행/모델의 같은 본문·같은 비용, 변조·중복 결합,
legacy 단일/모호 행·unknown과 원 장부 합계 보존을 확인한다. 실제 API 호출은0이다.

새 회귀7개와 기존 예산·공유scope·credit revision·continuation 검사를 포함한 관련100개, 전체 Factory884개를 통과했다. 실제 API 호출이나 과거 금융 행 수정은 없다. 원 response를 변형하지 않고 미래 PaidBudget 정산에만 결합을 기록한다.
