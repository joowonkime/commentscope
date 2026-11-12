# 기존 C 생성 모델 설정의 동일 owner 비교

TASK-022 / REQ-003·008·010. v5 B는 GPT5.2 생성/Sol 감사로 고정 실행 중이다.
완료 전 B의 wire·모델·원문·기준은 변경하지 않는다. 실제 생성이 부족하면 동일19개 전체에서
기존에 등록된 C의 Sol 생성 설정을 비교할 수 있도록 별도 실행 계약을 준비한다.
현재 B의 실패1건을 Sol로 재호출하는 fallback이 아니다.

## 금융 권한과 실행 역할의 분리

기존 cumulative money owner는150달러 계정·장부·기존 비용·최종14:45:28UTC를 보존한다.
같은 금융 owner 안의 새 실행은 고정한 모델/역할·원문·요청·가격·코드로 별도 묶는다.
원래 owner의 generation 필드를 바꾸거나, 새owner/새7시간으로 지출·시간을 초기화하지 않는다.

일반 prepare는 부모 generation 일치를 계속 요구한다. 명시적인 registered-generation-comparison 경로만
다음 증거를 갖춰 다른 생성 배정을 허용한다.

- 종료된 원 C plan의 file/SHA를 execution auth에 기록하고 입력 hash에도 결합한다.
- 참조는 arm=C, source-evidence-graph-20261111-v1의 **설정 이력**이며 deployment가 현재 고정 Sol과 같아야 한다.
- 참조의 계정/동일 DB/opening은 현재150 policy와 같아야 한다. 과거50 policy·원5달러 owner는 수정하지 않는다.
- 새 deployment는 그 C 설정과 정확히 일치해야 한다. 다른 모델·provider·가격·reasoning 임의 변경은 거절한다.
- 부모의 돈/시간 검사는 그대로이며, 새 실행의 모델 변경과 그 근거만 별도 기록한다.

이 예외는 돈을 새로 승인하거나 만료된 C 실험을 재개하는 권한이 아니다. 사용자 계속 진행과
이미 요청했던 A/B/C 비교의 설정을 누적150/원기한 안의 새 고정 요청 집합으로 구체화한다.
등록 B가 끝나고 미정산0을 확인한 뒤 다음 C를 등록한다. 동시에 돈 예약을 경쟁시키지 않는다.

## 비교의 범위

v5 B와 같은 source quote schema·prompt·고정6후보/19출처/25관계·Sol 감사/후보/사실 검사를 유지한다.
C는 generation과 그 client를 쓰는 runtime이 Sol이다. F4 생성 품질/청구와 runtime 결과는 구별한다.
새16 통제→대표3→전체19→Compiler/질문 순서, 최소지지3·whole-source·필수 사실 검사를 유지한다.
모든 결과·보류·출력 용량 실패·새 비용은 원 owner에 누적한다. 추정 전체서비스 단가/3000개/r5를 대체하지 않는다.
새 구현·등록의 검사와 실제 모델 우월성/제품 완료는 별개다.
