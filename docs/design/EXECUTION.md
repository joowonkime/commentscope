# 실행·비용·검증·전환 상세 설계

설계 `commentscope-detailed-design-20261105-v3`, DEC-001/004/005/006, REQ-001~010.
이 문서는 실험을 실행하거나 예산 보류를 해제하지 않는다. 모든 수치 비교는 기존 품질 기준 안에서 한다.

## X-01. 비용 모델

개발 총예산은 기존 공유 장부의 $50이며 추가 충전은 없다. 이미 확정/보수 차감한 비용을 유지한다.
현재 잔액은 실행 직전 관측한 장부와 key metadata로 확인하며 문서에 적힌 과거 잔액을 재사용하지 않는다.

변수: N=처리 원문, K=동결 후보, E=실제 검사한 후보 pair, P=nomination/최종 source-target task 수,
P+=M1 긍정 제안 수, A=source-target 논거 task, F=사실 packet 수다.
S2는 source의 제안 수에 따라 최대8개씩 검토하므로 “원문당 항상1회”로 견적 내지 않는다.

후보 요청 수의 상한식(continuation/복구를 제외한 기본 모델):

```text
Q = N(S1) + sum_s ceil(proposals_s / 8)(S2)
    + K(C1) + 2E(E1/E2) + P(M1) + P_positive(M2)
    + A_batches(A1) + A_batches(A2) + F_batches(fact checker)
```

source당 nomination 수를 n_s라 하면 최종 검색 edge는 `sum_s min(K, 6+n_s)` 이하이며
통합 전 nomination 검사는 별도다. 정확히 동일한 최종 target/원문/계약의 실행 내 판정만 중복 제거한다.
E의 최악은 K(K-1)/2다. 모델 출력 전에는 K/P/A가 확정되지 않으므로 N만으로 완료 비용을 약속하지 않는다.
plan은 K/E/P/A task 상한과 금액 상한을 선언하고 실제 값이 넘으면 중단·미처리 범위를 기록한다.

실청구는 input/cache read/cache write/output/reasoning/request 비용을 포함한다.
캐시 사용 여부가 실제 비용을 뒤집은 [과거 batch 결과](BASELINE.md#b-02-보존된-수치와-한계)를 보존한다.
정적 input byte 감소·호출 수 감소를 달러 절감으로 간주하지 않는다.

요청 예약은 기존 `PaidBudget`의 최대 context×입력 상한+출력 한도×출력 상한+요청비를 유지한다.
host 가격 상한은 cache-write와 모든 context tier를 포함하며 실제 metadata/단일 provider와 대조한다.
실제 input 예상량이 작다고 예약을 축소하거나 provider context를 허위로 낮추지 않는다.
그 결과 작은 비교 한도로 단1회도 예약할 수 없으면 실행 불가다. 상한을 몰래 늘리거나 장부를 초기화하지 않는다.

model role별 deployment에는 model ID, provider, context, supported schema, reasoning/output 한도,
timeout, 가격 상한과 버전이 필수다. 일반 구현이 이 값을 임의 변경하지 않는다.
provider 미지원 schema 변환은 기존 adapter를 재사용하되 host validator의 제약은 그대로 유지한다.

측정 단위는 최초 영상 분석, 추가댓글 갱신, 동일 분석 재열람, 단일 Agent 질문, 그룹 한 턴/한 세션,
Explore 비교, Reflect 분석이다. 저장/GET/poll·동일 완료 결과 재열람은 신규 생성0회여야 한다.
서비스 1회 원가와 개발 중 여러 실패·검토의 누적 비용을 따로 보고한다.
$0.50/1,000댓글·$0.02/두 관점 질문은 미검증 제안이다. 이를 맞추려고 r5나 출처 검증을 낮추지 않는다.

## X-02. 계획·중단·복구

plan에 다음을 고정한다.

- spec/design/contract/prompt/code 버전과 input/snapshot/hash/사용기한.
- source·candidate·edge·논거 task의 scope와 상한, 역할별 model/provider/deployment.
- 실행별 금액 한도, 공유 장부 identity, 출력·context·timeout·동시성1·재시도0.
- 사용할 평가 profile·고정 질문·채택/폐기 조건, 실험인지 fresh gate인지.

host 단계에서 실패하면 모델을 부르지 않는다. 호출 후에는 원본 영수증→정산→검증→게시 순서를 지킨다.
partial/length/빈 응답/전송 불명은 서로 구별하고 완성 출력으로 취급하지 않는다.
사용자 pause·close·프로세스 종료는 과금 환급의 근거가 아니다.
동일 계획 재개는 완료 checkpoint를 읽고, 불명확한 호출은 새 요청 없이 reconciliation을 요구한다.
취소·종료는 현재 bounded call의 정리를 기다리며 실제 handle·정산 상태를 인계한다.

## X-03. 분석 재사용·증분·기한

캐시 identity는 `snapshot/source/parent/video_context hash + contract/prompt + model/provider/config + schema`다.
해당 판정이 읽은 다른 입력도 모두 포함한다. 같은 문자열이라도 target 문구/범위·source 문맥이 다르면 재사용하지 않는다.
실행 내 캐시·동일 plan checkpoint는 이미 있다. 서비스용 immutable analysis 재사용은 별도 저장 정책이다.

완료된 analysis는 revision별 불변 파일과 registry에 등록한다. GET/재열람은 모델 호출0회이며
입력·기한·검증 상태를 다시 확인한다. 사용자 초기 의견·대화·성찰은 공용 analysis 캐시에 넣지 않는다.
질문/비교/성찰 결과를 재사용할 때는 해당 사용자/opinion/context revision까지 identity에 포함한다.

신규 댓글의 증분 처리는 다음 순서다.

1. added/changed/removed ID와 부모·영상 문맥 변경을 계산한다.
2. 입력/계약이 같은 source 해석만 재사용한다. 부모가 바뀐 답글의 해석은 무효다.
3. 후보/병합이 바뀌면 그 최종 문구에 대한 기존 지지를 다시 확인한다.
4. 새 후보는 기존 원문에도 영향을 줄 수 있으므로 전체 source의 retrieval 계획을 다시 계산한다.
5. 영향받은 논거·사실·Agent와 이전 지원 수를 무효화하고 새 revision으로 완성한다.
6. 영향 범위를 안전하게 증명할 수 없으면 전체 재검증 계획으로 승격하고 비용 사전 검사를 다시 한다.

“새 댓글 수만큼만 비용이 든다”는 보장은 없다. 수천 개 확장은 고정999 통과 후 별도 corpus/규모로 평가한다.
진행 중 대화는 원래 revision을 유지한다. 새 분석으로 이동할 때 새 room을 만들고 이전 발언을 새 근거로 재작성하지 않는다.
source 만료·삭제·hash 불일치는 생성/원문 게시를 막는다. user note·비인용 상태 기록의 보존은 별도 정책을 따른다.
정식 fresh gate에는 서비스 캐시나 다른 실행 응답을 끼워 넣지 않는다.
NLI 고정40건은 기존 동일성 검사(모델/가중치/코드/임계값/런타임)를 통과할 때만 호환 증거로 재사용하고 fresh 아님을 밝힌다.

## X-04. 계약 사례

아래는 합성·고정할 회귀 사례다. 구현 전 기대 동작이며 이 문서를 작성했다고 실행 통과한 것이 아니다.
의미 판단은 모델을 실제 호출한 결과와 원문을 대조한다. 모의 응답 검사로 의미 정확성을 대신하지 않는다.

| ID | 입력/상황 | 기대 동작 | REQ |
| --- | --- | --- | --- |
| CASE-01 | 같은 도입 찬성, 서로 다른 회복/가족 이유 | 공통 P와 source별 이유 분리, 이유 전이0 | 001/002/003 |
| CASE-02 | 임금 유지 경우에만 찬성→무조건 P | conditional, 확정 지지0 | 001/002 |
| CASE-03 | 같은 원문→임금 유지 조건을 명시한 P | 조건 범위까지 일치할 때만 supported | 001/002 |
| CASE-04 | 친구는 찬성, 작성자는 반대 | 인용과 자기 입장 분리 | 001/002 |
| CASE-05 | 비용 걱정되지만 찬성 | 걱정은 concession, 찬성 이유로 사용 금지 | 001/003 |
| CASE-06 | 도입 찬성+별도 초과근무 개선 요구 | 추가 입장을 필수 조건으로 자동 변경하지 않음 | 001/002 |
| CASE-07 | undecided가 명확한 원문 | 미결정 보존, 확정 찬성/반대 생성 금지 | 001/002 |
| CASE-08 | 부모는 비용 이유, 답글은 동의만 | 동의 해석과 부모 이유 전이를 구분 | 001/003 |
| CASE-09 | 가상 세계의 정책 요구와 현실 요구 | world 범위가 다르면 무조건 동치 금지 | 001/002 |
| CASE-10 | 주당 며칠과 연속 몇 주 | 수량·빈도·기간을 서로 대체하지 않음 | 001/002 |
| CASE-11 | A~B, B~C, A~C 미검사 | complete-link 병합 불가, 누락 edge 평가 또는 보류 | 002 |
| CASE-12 | final representative text 변경 | 과거 지지 단순 합산 금지, 새 text 직접 판정 | 002/003 |
| CASE-13 | 같은 canonical source의 여러 이유·alias | 관점당1표·전체 활용1회, 이유 제공자 집합 별도 | 001/002 |
| CASE-14 | 후보 descriptor가 없는 조건을 제안하거나 fact를 value로 오분류 | M2는 목표 문구/전체 원문으로 독립 검토, core 유형 충돌은 후보 보류 | 001/002/003 |
| CASE-15 | 필수 사실이 반박·불충분 | 전제 삭제/가치 재분류 없이 후보 보류 | 003 |
| CASE-16 | 이유 없는 Agent에 왜 질문 | core/양보로 대신 답하지 않고 근거 범위의 보류 | 003/005 |
| CASE-17 | 일부 catalog만 검색해 이유 없음 | not_in_context, 전체 관점에 이유가 없다는 단정 금지 | 005 |
| CASE-18 | 사용자 의견에 없는 내용을 Agent가 말함 | 그 부재만으로 의견 차이를 단정하지 않음 | 004 |
| CASE-19 | 동일 request_id 동일 body 재접속 | 같은 job/result, 신규 추론0·중복 게시0 | 005/008 |
| CASE-20 | 동일 ID 다른 body / stale revision |409, 기존 job·이력 변경0 | 005/008 |
| CASE-21 | 그룹 실행 중 pause | 현재 호출 정산 후 다음 dispatch 정지, cursor 유지 | 006/008 |
| CASE-22 | 실행 중 close 후 늦은 응답 | 비용/응답 보존, 옛 epoch 메시지 게시0 | 006/008 |
| CASE-23 | 그룹2번째 턴 실패 | 기존 유효 발언 유지, partial round, 자동전체재실행0 | 006 |
| CASE-24 | 다른 Agent가 새 해결책 제안 | 자기 source가 없으면 자신의 사실·지지로 승격 금지 | 003/006 |
| CASE-25 | 현재 의견 유지 또는 분석 후 편집 | stayed/수동저장 허용, changed/new 강제0·stale AI를 새 글에 연결 금지 | 007 |
| CASE-26 | 존재하지 않는/타인 message ID로 성찰 |404/검증실패, 관련대화 발명0 | 007/009 |
| CASE-27 | 관련 대화는 있지만 사용자가 영향 원인 미명시 | 변화 원인 단정 금지 | 007 |
| CASE-28 | 정산 후 message 저장 전 crash | 같은 완료 응답으로 복구, 신규 과금·중복 게시0 | 008 |
| CASE-29 | reserved/unknown 비용과 재시작 | 새 유료 dispatch0, reconciliation 상태 | 008 |
| CASE-30 | source가 호출 중 만료/변경 | 정산 보존, 결과/원문 게시 거부 | 001/008 |
| CASE-31 | 한국어 조건문·영문 conditional의 동등 사례 | 언어에 따라 조건 삭제/찬반 반전 금지 | 001/004/005 |
| CASE-32 | renderer 번역 요청이 필수 조건을 생략 | 번역 비활성/보류, 원문 보존. 품질 미검증 번역 게시 금지 | 001/009 |

초기 source 계약 구현은 CASE-01~10/14, 관계·통합은11~15, runtime/제품은16~32를 담당 테스트에 연결한다.
기존 [Factory 회귀](../../tools/check_factory_draft.py), `test_acceptance_r5`, `test_grounded_runtime`,
`test_grounded_web_failures`, `test_openrouter_budget`를 재사용·확장한다.
새 테스트 이름·코드가 없는데 실행됐다고 보고하지 않는다.

## X-05. 비교·채택·확대

먼저 TASK-003의 S1/S2 계약 연결과 TASK-004의 bounded 의미 진단을 진행한다.
이때 후속 검사를 유지하므로 비용 절감을 요구/주장하지 않는다. 추가 필드의 실제 의미 보존과 정상 보존을 확인한다.
나머지 계약·중복 호출을 대체한 TASK-013 이후, 아래 전체 비용/품질 채택 비교를 TASK-014에서 수행한다.

1. 오프라인: 고정 사례와 저장 실패에서 새 계약/adapter의 ID·범위·판정 경계를 검사한다.
   기존 positive/negative를 함께 사용하며 source 문구 하나에 맞춘 예외를 추가하지 않는다.
2. 제한 비교 계획: [고정 합성 입력](diagnostic-fixture.json)의8 source·4 target·9 source-target pair·3 candidate pair를 사용한다.
   P0에 대한 기대 관계는 S1/S2/S5/S6/S8=supported, S3=conditional, S4=opposed, S7=uncertain이다.
   S3→P1은 조건 일치 supported, P0↔P1은 포함 관계, P0↔P2는 반대, P0↔P3은 동치 대조다.
   S8의 동의는 부모의 이유를 차용하지 않는다. 이 fixture는1Agent만 나올 수 있고 정식 G1이 아니다.
   baseline/candidate의 실제 논리 task 목록과 최대 요청 수·출력·비용을 실행 전에 저장한다.
   역할별 같은 모델로 구조 차이를 먼저 비교하고 provider/model 변경 효과는 섞지 않는다.
3. 유료 실행 전 공유 장부·보류·현재 권한·단일 요청 예약 가능성을 확인한다.
   새 금액 한도는 계획에 명시하며 이 문서에서 자동 승인하지 않는다. 알려진 음성 batch4 실험은 반복하지 않는다.
4. 순서/캐시 warming을 고정하고 요청별 input/cached/write/output/reasoning/실청구를 기록한다.
   과거 baseline 영수증은 역사 비교이며 현재 가격·캐시 조건의 paired 비용 증거를 대체하지 않는다.
5. 새 중대 왜곡·미확정 과금·한도/형식 실패가 발생하면 다음 dispatch를 중단하고 비교는 incomplete로 남긴다.
   끝난 일부 성공만 선별해 채택하지 않는다.
6. 제한 비교에서 중대 오류0·기존 정상 보존 손실0·총 실청구 비증가가 후보 채택의 필요조건이다.
   작은 표본 성공은 범용 정확도·서비스 단가의 증명이 아니다. 실패 시 현행 경로를 유지하고 가설을 폐기/수정한다.
7. 후보를 동결한 뒤 기존 G1→G2/G3→G4를 수행한다. model/provider/prompt/판정 코드 변경 후 과거 합격을 승계하지 않는다.

G1 합성12, G2 보존12/19, G3 보존45/74, G4 활용453/755와 집계 지지 전수 유효·모든 Agent 검토를 유지한다.
G2/G3의 후보 보존과 G4 공유군집 활용을 혼용하지 않는다. source/관점 수를 임의로 줄여 통과시키지 않는다.
주요 사실8/10·오승인0/30, 실제 Agent 사실·각3질문·이력/출처 분리의 기존 기준을 유지한다.
개발 담당의 직접 대조는 독립 사람 gold가 아니다.

## X-06. 제품 통합과 버전 전환

- TASK-003/004: S1/S2의 opt-in 계약·오프라인 전체 연결→bounded 모델 진단. legacy 경로/기록 보존.
- TASK-013/014: 나머지 계약·중복 호출 대체→전체 후보의 제한 품질/비용 비교.
- TASK-005~007: 동일 설정 fresh G1→G2/G3→G4. 앞선 진단으로 게이트를 대체하지 않음.
- TASK-008/009: Explore와1:1/그룹의 API·저장·Controller 구현. 기존 계약의 실패/중복 규칙을 유지하는 adapter 검사.
- TASK-010: 성찰 입력·분석·채택본·관련 대화·저장 구현. 변화 없는 경로를 포함.
- TASK-011/012: 기존 팀 프론트 연결→실제 자동 bundle의 세 과업→실행 URL·원가·사용자 검증.

새 artifact/DB schema는 버전을 선언하고 migration 이력을 남긴다. 앱 상태 DB 전환은 백업/단독 lock/호환성 검사 후
실행하며 지출 장부의 policy·잔액·과거 호출은 마이그레이션으로 재작성하지 않는다.
새 compiler adapter가 이전 bundle에 새 검토가 있었다고 꾸미지 않는다. 기존 room은 기존 bundle revision에 고정된다.
전환 실패 시 이전 실행기/불변 artifact를 보존하고 새 버전 실행만 거부한다.

제품 완료는 세 과업을 실제 자동 결과로 수행하고 오류·중단·원문 이동·저장·재열람 비용을 확인한 범위로 판정한다.
전체 시장 경쟁력·재방문·지불 의향은 별도 사용자 근거가 필요하다. 명세·CI·Figma가 그 증거를 대신하지 않는다.
