# Cluster → Agent의 실제 실행

TASK-005~007, REQ-001~003/008/010. 설계 `commentscope-detailed-design-20261105-v4`.
사용자 정정: 별도 프론트는 아직 없다. 먼저 실제 댓글을 관점으로 묶고 근거를 가진 Agent를 생성해 질문에 응답한다.
이미 구현한 `/mvp`는 결과를 확인하는 개발 화면으로 유지한다. 원본 Figma는 수정하지 않는다.

## 실행 경로

기존 기본 Factory의 source registry → free discovery → candidate consolidation → raw membership
→ source arguments/facts → Agent compiler → 각 Agent의 고정3질문 경로를 사용한다.
실험 중인 typed S1/S2 교체나 전체 새 역할 구조를 채택하지 않는다. 알려진 의미 오류는 보존한다.
현재 모듈의 source/조건/부모/인용 검증은 유지하고, 모델 자체 판정을 최종 의미 품질로 부르지 않는다.

새로 동결한 동일 코드·모델·설정의 G1을 수행하고 전체 산출물을 원문 대조한다.
성공 시 같은 설정의 실제24개 G2 →96개 G3 →999개 G4를 진행한다.
실행 완료/관점 수/Agent 수만으로 gate를 통과시키지 않는다. 자동 생성된 전체 Agent를 검토하고 각3질문을 확인한다.
고정12/19·45/74·453/755와 집계 지지 전수 유효·최소2Agent/각3유효지지·사실 기준을 유지한다.
실패 시 해당 범위를 수정하고 동결한 새 실행으로 확인한다. 실패한 plan/응답/청구는 덮어쓰지 않는다.

## 동일 cycle의 비용·시간 연결

`openrouter_factory_pipeline.prepare`에 선택적 `cycle_file`을 추가한다.
cycle을 지정하면 선택 deployment와 공유 policy가 원본 cycle과 정확히 일치하고,
maximum_cost_usd는 cycle의 원래 maximum_additional_usd와 같아야 한다. 잔여액으로 새 한도를 만들지 않는다.
cycle 원본·hash·경로를 plan/inputs에 동결하고 `PaidBudget.spend_scope_sha256`에 **원본 cycle SHA**를 전달한다.
plan SHA는 checkpoint/응답 provenance에 유지한다. 다른 서버/분석 plan도 원래 단일 $5 차감을 공유한다.

기존 확인 시 차감$0.96962145·잔여$4.03037855이며 이는 실행 전 최신 장부로 다시 확인한다.
기한은 기존2026-11-05T03:15:51Z다. 새로운7시간이나 새$5를 승인한 것으로 해석하지 않는다.
생성·embedding·fact 호출 직전에 해당 작업의 timeout과 정산 여유를 기한이 수용하는지 확인한다.
완료한 결과의 재열람은 기한이 지났어도 새 모델 호출 없이 가능하다.
원본 cycle 변경·소유자 변경·model/policy/한도 불일치·기한 만료는 새 호출 전에 거부한다.
reserved/unknown·과금 불명·가격 상한 변경은 기존 정책대로 새 유료 호출을 중단한다.
CLI의 `run --key-file /PRIVATE/KEY_FILE`은 키를 worker 환경으로만 전달하고 plan/출력에 저장하지 않는다.
기동 시 자원 부족도 기존 typed resource stop으로 반환하며 traceback이나 자동 재시도로 이어가지 않는다.
기존 cycle 미지정 사용자는 종전 plan별 한도를 유지한다. 현재 승인 실행에는 cycle을 반드시 지정한다.

## 정상·부정 확인

- 두 Factory plan이 같은 기존 cycle 차감을 공유하고, 다른 plan을 만들어도 한도가 늘지 않는다.
- cycle과 plan의 한도/모델/policy 변경은 provider 호출 전에 거부한다.
- 중간에 기한이 끝나면 다음 호출이 없고, 완료 결과의 재개는 추가 과금0이다.
- G1 전체12원문과 모든 Agent/응답을 보존한다. 사람이 두 관점을 골라 만든 demo로 대체하지 않는다.
- G2 이후는 동일 설정의 실제 이전 gate 원문 검토와 결합해야 한다. 과거 다른 모델의 성공을 승계하지 않는다.
- 일반 source 처리 실패·원문 해석 오류·Agent 부족·답변 보류와 비용/전송 실패를 별도로 보고한다.

이 문서는 실제 품질 성공이나 서비스 단가 달성을 선언하지 않는다. 모델·원가 실측은 동결 plan과 영수증에 기록한다.

## 이번 구현의 확인 범위

동일cycle/이전차감/새plan/모델·한도변경/중간기한/완료재열람/기동자원부족의 새7개 검사와 기존자원14개를 통과했다.
새7개를 포함한 필수Factory482개 검사도 통과했다. 최종 전체검사는 PR CI로 확인한다.
고정12개 G1과 실제24/96/999개의 원본·scope를 읽고 source 요청 schema와 문맥 수용 여부를 모두 비용 없이 확인했다.
이는 군집·지지·Agent 생성 성공이나 의미 품질 검증이 아니다.

동결G1을 실제파일진입점으로 기동했으나 호스트디스크여유가 기존최소6GiB에미달해
`ResourceStopRequested/low_host_disk`로 모델작업전에 중단됐다. checkpoint intent와 모델호출은0이다.
보호기준을낮추거나원문·기록·무관한파일을삭제하지않았다. 자원확보후 같은plan으로 재개할 수 있다.
현재TASK005는in_progress이며 G1/G2/G3/G4는미통과다.
