# 기존 생성 결과로 제품 흐름 구현

연결: TASK-015/008/009/010/011/012, REQ-004~010. 설계 `commentscope-detailed-design-20261106-v10`.
사용자2026-11-05 지시: 후속 검증의 신뢰성을 가정하지 않고 MVP 기능 구현을 진행한다.

## 완료된 제품 개발 연결의 범위

현재 우선 작업은 [Cluster→Agent 실제 실행](FACTORY_DELIVERY.md)이다. 아래는 TASK-015/008/009/010의 완료된 개발 연결 기록이다.
새 의미 역할 교체 TASK-013/014와 S1/S2 오류 튜닝은 보류한다. 관측 오류/실패는 그대로 남긴다.
기존 자동 Factory의 bundle을 제품 개발에 연결하고 Explore → Converse → Reflect를 구현한다.
개발 입력 연결과 formal G1~G4/최종 제품 합격은 구별한다. 최종 출시는 기존 r5와 전체 과업 검증을 모두 요구한다.
TASK-008/009를999개 품질 검증 이후에만 개발하도록 했던 의존성을 제품 개발 입력 TASK-015로 바꾼다.

## TASK-015: 실제 생성 산출물 연결

- 기존 Factory run의 plan/snapshot/output/agent-inputs를 읽는다. 원본 hash와 bundle 일치를 확인하고 현재 compiler로 다시 검증한다.
- 모든 compiler profile을 가져오며 사람이 좋은 Agent만 선택해 합격시키지 않는다. 실제 가용 Agent가 부족하면 그대로 표시한다.
- 분석 ID와 bundle revision은 host가 계산한다. 등록 자료만 사용하며 임의 URL 분석은 추가하지 않는다.
- 과거 실행은 개발 자료의 provenance다. 현재 코드의 fresh G1이나 정식 품질 성공으로 승계하지 않는다.
- 개발 분석은 `experimental`이며 semantic reliability는 `not_assessed`로 보존한다. 모델 confidence 점수를 만들지 않는다.

## 제품 API와 상태

[I-01~07](INTERACTIONS.md)의 `/api/v1` 입력·소유권·revision·idempotency·그룹/성찰 계약을 구현한다.
기존 M0 API는 변경하지 않는다. 개발용 화면은 별도 `/mvp` 경로이며 팀 프론트/Figma 원본을 수정하지 않는다.

- 초기/현재 의견·rooms·메시지·jobs·성찰을 별도 SQLite에 보존한다. token hash만 저장한다.
- Explore는 초기 의견 구간과 실제 관점 claim을 비교하고 정확한 revision·근거 참조를 반환한다.
- Converse는1:1와 실제2~3Agent opening/reply round·pause/resume·사용자 개입을 제공한다.
  다른 Agent 발언은 문맥이며 근거가 아니다. 답변 내용·인용은 기존 자기 allowlist에서 host가 복원한다.
- Reflect는 네 범주·실제 대화 참조·원문 revision을 가진 제안을 만들고 사용자 채택본을 별도로 저장한다.
  변화 없음·빈 범주·수동 저장이 유효하다. 저장/GET/poll/중복 요청에는 생성 호출이 없다.
- 미지원·실패·의미 품질 미평가를 표시한다. 잘못된 사실/귀속이 실제로 차단된다고 추측하지 않는다.

모델은 전역1개씩 호출하고 job 입력/결과를 durable하게 보존한다. pause는 현재 턴 뒤, close는 늦은 게시를 막는다.
프로세스 중단 시 실행 중 job은 reconciliation으로 남기며 자동 유료 재전송하지 않는다.
세션·source 기한, 인용·메시지 소유권, 잘못된 ID, stale revision, 요청 충돌을 host에서 검사한다.

## 비용과 확인할 결과

기존 승인된 최대7시간/추가총$5 사이클의 차감$0.92141945·잔여$4.07858055와 동일 spend_scope를 유지한다.
새 제품 서버/세션/room으로 한도를 초기화하지 않는다. 새 호출 전 기존 동결 cycle·현재 가격·예약 가능성·종료시각을 확인한다.
의미 오류만으로 다른 기능의 개발을 멈추지 않고 최종 산출물과 영향 범위를 기록한다.
과금 불명·상한/기한 초과는 새 유료 호출을 중단한다. 품질 미통과 결과를 정식 성공으로 올리지 않는다.

이번 완료 증거는 실제 자동 생성 bundle의 등록 → 의견 비교 → 대화/원문 확인 → 성찰 분석·편집·저장·재열람이다.
합성 HTTP/오프라인 검사, 제한된 실제 응답, 전체999개 의미 품질과 사용자 검증을 구별해 기록한다.
