# 정산된 불완전 원문 응답의 재호출 없는 후속 실행

TASK-022 / REQ-001·003·008·010 / DEC-018. 원 v4 계획·모델·출력 할당·의미 기준은 유지한다.
개발 통제16건은 정상8/8·왜곡8/8탐지·오승인0, 실청구0.1969075달러로 완료됐다.
최장 root의 첫 원문 그래프 생성은 출력13312토큰에서 length 종료됐고0.2008545달러로 정산됐다.
대표 검사에서 ModelResponseUnavailable을 처리하지 못해 실행 전체가 중단됐다. 원 응답/오류/비용을 보존한다.

## 허용하는 복구

별도 고정 continuation launcher/manifest로 원 실행을 이어간다. 원 plan·authorization·checkpoint를 수정하지 않는다.
같은 money owner·원 최종 기한·기존 지출/요청 수·가격·원문 목록·모델·출력 한도를 그대로 쓴다.
범위는 source-evidence proposal/observation/candidates의 **저장된 length 종료 응답**이다.

- 원 request·checkpoint intent/done·원 provider envelope·모델/라우팅·사용량·본문의 일치를 검사한다.
- 실제 ledger의 동일 owner/request가 정확히 하나이며 complete 정산액이 영수증 비용과 같아야 한다.
- raw 응답/실패 상태를 수정하지 않고 기존 binder에 그대로 반환한다. binder는 errors를 거절한다.
- pilot는 binding_error, Factory는 실패/보류로 기록한다. 잘린 출처의 일부를 지지나 이유로 채택하지 않는다.
- 정상 완료한16개 통제와 같은 요청은 기존 checkpoint로 읽는다. 재호출·출력 증액·자동 수정은0이다.
- 원본/manifest 변경, pending·unknown·over-ceiling 과금, 영수증 불일치, 다른 오류는 계속 중단한다.

완료된 실패 응답의 반환과 새 의미 승인은 다르다. 실제19개 전체를 방문하되, 출처별 실패와 미평가를 남긴다.
이 복구는 길이 문제 해결이나 Agent 생성 성공이 아니다. 원 실험에서 표현·용량·모델 실패를 측정할 수 있게 한다.

## 검사

정산된 길이 오류만 원형 반환, pending/unknown과 영수증/본문 변경 거절, 원 checkpoint 재사용/추가 호출0,
manifest·원 계획/기한의 결합을 합성 회귀로 확인한다. 실제 품질은 원 v4 결과와 함께 따로 보고한다.
