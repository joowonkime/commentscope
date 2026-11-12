# 실제 원문 F4와 Agent 생성 비교

TASK-022 / DEC-013/015 / REQ-001/002/003/008/010.
사용자2026-11-12 요청: Agent 생성 파이프라인을 우선하고 구현 및 테스트까지 진행.
외부 자료로 논증을 확장하는 토론 기능은 이번 범위에 넣지 않는다.

## 실행 범위

이전 완료999 실행의 후보303개·검증 membership map을 입력으로 고정한다.
Agent-eligible 후보6개에 속한 전체 지지 출처19개/관계25개를 대상으로 **F4 모델 응답부터 새로** 실행한다.
기존 응답을 새 F4 응답으로 사용하지 않는다. 전체999의 발견/검색/M1/M2를 새로 실행한 실험도 아니다.
기존 raw map의 의심 관계도 입력에서 몰래 제거하지 않고 기대값과 최종 노출 여부를 별도로 확인한다.

구현: `tools/source_evidence_trial.py`.

| arm/순서 | F4 경로 | 생성/검증 |
| --- | --- | --- |
| B | 새 source evidence graph | 기존 GPT-5.2 생성 / Sol 관측 |
| A | PR89 용량 수정이 포함된 기존 scalar 경로 | 동일 생성/검증 |
| C | B와 동일 graph 계약 | 생성도 Sol,검증은 동일Sol |

각 arm은 독립 core typing/fidelity·원문 논거·필수 사실·Compiler·생성 Agent의 기존3질문을 실행한다.
전체 eligible 지지 출처를 처리하며 특정 성공 댓글만 고르지 않는다. 모델/자료/조건/기준을 바꾸지 않는다.
개별 오류는 기록하고 원 계획 안에서 계속하되 금융·무결성·자원 중단은 기존 규칙을 따른다.

## 기대값과 한계

25관계 전부에 coding-agent의 사전 기대값 supported / not_supported_as_unqualified_core / uncertain을 부여한다.
기존 개발48개 원문 메모와 별도로 추가2원문도 읽었다.3개 scope 의심 관계와1개 불확실 관계를
성공으로 채우지 않는다. 출처 원문·case ID·주석·실제 응답은 private 실행 디렉터리에만 저장한다.
이 주석은 independent human gold가 아니며 기존 실패·map을 알고 작성한 진단이다.
반대 사례 노출/유효 지지 보존과 source별 이유 보존을 함께 확인한다.

등록된48원문/256쌍 paired 평가와 미사용 전이의 대체가 아니다.
이번은 새 stage의 **유한 profiling과 적격 출처 전체의 통합 확인**이며,원문 이유관계 R≥20 등
기존 채택 조건이나 formal r5를 변경하지 않는다. 작은 결과만으로 B/C 기본값을 채택하지 않는다.

## 돈·기한·복구

현재 사용자 테스트 지시를 근거로 **세 arm 합계 추가5달러/최대7시간**의 새 한정 실행을 등록한다.
단일 authorization hash를 모든 arm의 money owner로 사용한다. arm별5달러가 아니다.
기존 운영장부50/팀한도150과 이전 보수차감·실패·원owner·만료15달러 계획은 보존한다.
새 단계는 기존 운영장부의 실제 잔여와 현재 키 잔여 안에서만 시작한다.

새 graph stage profile이 없어 full matrix의 실제 비용/완료 가능성은 아직 모른다.
profiling 경로에서만 실제 wire/input/output/reasoning·가격 상한으로 매 요청을 예약하며
공유5달러 cap에 다음 요청의 최대 예약이 맞지 않으면 중단한다. 미측정 비용을0으로 채우지 않는다.
전 행렬 최악비용이5달러에 맞는다고 주장하지 않으며,미완료면 그 상태와 실제 차감을 남긴다.
A 물리요청 상한700,B/C각140이며 요청 수와 별개로 동일5달러 cap이 우선한다.

provider endpoint·context·지원 schema/가격,원문/입력 hash·코드/tool hash·기한·자료 만료를 고정한다.
각 arm의 plan/checkpoint/실제 영수증을 분리하고 completed 결과만 동일 plan에서 재사용한다.
자동 retry/fallback0. 미확정 과금·pending checkpoint는 재호출하지 않는다.
기존 HTTP host headroom/storage guard와 durable money accounting을 사용한다.

## 결과 기록

arm별 complete/unresolved source,오류/보류,최종 Agent 수/원문 수/이유,정답 관계의 게시 여부,
필수 사실 상태,3질문의 answered/abstain과 실제 청구를 저장한다.
source scope/모달리티/귀속·조건·이유와 실제 노출 내용을 원문과 대조하고,
실행 성공/논리형식 통과/실제 의미 품질/전체 MVP 완료를 구별한다.

## 호스트 재부팅 복구

첫 B 실행 중 Linux 호스트가 재시작돼45개 완료 응답과1개 pending 요청이 남았다.
현재 부팅 시각보다 이전에 시작된 요청임을 원 요청·checkpoint intent·시간장부·공유 금전장부로
대조한다. `tools/source_evidence_recovery.py`는 별도 불변 manifest/launcher 사본에 이 증거를 결합한다.
저장 응답이 있거나 이번 부팅 이후의 요청·다른 활성/미확정 비용이면 복구를 거절한다.

정확한 유실 요청의 원 예약 전액을 보수 차감하며 원 plan·intent·요청·한도·deadline을 유지한다.
시간장부의 재구성 시간은 요청 시작부터 재부팅까지의 달력 시간 상한이며 실측 provider 시간이 아니다.
해당 요청만 `PriorRequestUnavailable`로 보류한다. 응답 합성·재호출·성공 판정 채우기는 하지 않는다.
나머지는 원 Session/의미 검증을 거치며 arm 완료 결과를 복구 manifest SHA와 별도로 결합한다.
이 추가 실행 제어를 사용한 결과는 최초 무중단 실행과 구별하며 formal admission은 계속 false다.

재개 첫 시도는 기존 자원 감시 `started.json`과의 충돌로 유료 호출 전에 종료됐다.
원 자원 로그142개를 SHA 목록/원·이동 경로를 가진 별도 private archive로 보존한 뒤,
동일 경로에서 새 감시를 시작한다. 원 stop 기록을 삭제하거나 정책을 낮춰 해제하지 않는다.
현재 호스트를 같은 정책으로 새로 측정하고 원본/재개 감시 기록을 구별한다.

후속 실행기 수정은 `resources/attempt-NNNN`에 시도별 새 감시 기록을 만든다.
기존 root 자원 기록/이전 attempt를 덮어쓰거나 삭제하지 않으며,같은 observer와 정책을 사용한다.
이 수정은 동결 원 v1 실행 파일에는 반영하지 않았다. 원본·부분 결과는 보존하고 후속 수정본과 구별한다.

## 후속 수정본의 무료 회귀

격리한 수정본은 관련50개와 Factory 전체793개(431.500초)가 통과했다.
v2 정상 코드 처리,실제 실패/불확실 보류,이전 protocol 증거 거절,시도별 자원 로그 보존,
동일5달러/기한/이전차감/요청 식별과 재호출 없는 보수 복구를 검사했다.
이 증거는 합성 모델 응답과 host 계약의 회귀이며 실제 v2 Agent 품질 검증이 아니다.
