# 현행 파이프라인·호출·비용 기준선

연결: TASK-001, REQ-001/002/003/008/010. 대조 코드 `4c96191`, 관측일 2026-11-05.
범위: 소스와 보존된 2026-11-04 실험 요약을 오프라인으로 대조했다. 새 모델 요청 0회.
실제 원문·응답·장부는 비공개로 유지한다. 이 문서의 합성 실험 수치는 서비스 완료 실측이 아니다.

## B-01. 실제 진입점과 단계

[`minimal_pipeline.process`](../../src/commentscope/factory/minimal_pipeline.py)는 입력·모드를 확인한 뒤
discourse 파싱 → embedding → discovery → memberships → arguments → compile을 호출한다.
[`pipeline_stages`](../../src/commentscope/factory/pipeline_stages.py)는 단계 순서를,
[`PipelineWork`](../../src/commentscope/factory/pipeline_work.py)는 요청·출처 결합·오류/용량·실행 내 캐시를 관리한다.

`SCHEDULE`의 extraction/membership/equivalence/argument 기본 물리 크기는 1이다.
원격 실행의 정확한 mode/protocol은 해당 plan에 고정된다. 코드의 기본 `free/scoped`를 현재 원격 선택으로 추정하지 않는다.

| 현행 경로/단위 | 입력 → 판정 | 기존 재사용·후속 호출 |
| --- | --- | --- |
| extract / source | 원문·부모 → 최소 주장·구간·조건 | extraction protocol에 따라 compact/해석 검토 분기 |
| source-interpretation-review / source | 제안과 원문 → 귀속·발화·세계·충실성 | 이미 존재하는 제안 검토이며 새 기능으로 재발명하지 않음 |
| source-context / source | 원문·부모 → 문맥 관측 | `source_contexts[digest(source)]`에 실행 내 캐시 |
| source-world / source | 원문·부모 → 현실/가정/허구 관측 | `statement_worlds`에 실행 내 캐시 |
| candidate-world / text | 후보 문구 → 세계 관측 | 같은 world cache를 사용하지만 원문 문맥과 구별 |
| nomination-raw / edge | 원문·후보 → 지지 제안 | 후보를 낸 원문도 자동 지지하지 않음 |
| raw-candidate-route / candidate | 후보 단독/계약별 origin → 판정 경로 | `raw_routes[digest(target)]`에 실행 내 캐시 |
| raw-own-evidence / positive edge | 원문 지지 제안 → 원문 충실성 재검토 | 긍정 판정에만 추가 독립 요청 |
| equivalence / pair | 후보 쌍 → 동치·포함·반대·차이 | 가까운3 추천 후 실제 complete-link 증거 필요 |
| qualification-inventory / text | 목표 문구 → 필수 상세 구조 | `shape_cache[text]`에 캐시 |
| qualification-detail / source-detail | source·필수 상세 → 보존 판정 | `assessment_cache`로 같은 source/shape 재사용 |
| qualification-ownership / pair | source·목표 → 귀속 검사 | 동치 양방향과 논거 alignment에도 진입 가능 |
| assertion-counterexample / pair | 후보 쌍 → 범위 차이 검사 | 해당 protocol의 동치 제안 후 추가 |
| membership-initial/expanded / edge | 최종 후보·원문 → 지지 및 검토 | 최초 top3+nomination, 필요 시 추가3. 실패 pair를 확장 재시도로 보내지 않음 |
| core / eligible candidate | 지지충족 후보 → 핵심 유형·범위 | core-fidelity와 후보 보류로 연결 |
| argument-node-metadata / node | 원문 node → 유형·귀속 | 지지 source별 모든 node를 따로 처리 |
| argument-position-alignment / node-target | 원문 node·후보 → 입장 연결 | 동치 제안이면 qualify 양방향 |
| argument-dependencies / source | 원문 논거·후보 → 사실/전제 연결 | 사실이 없는 경우 host 결합, 있는 경우 호출 |
| argument-owner / task | source·대상·논거 → 귀속 관측 | split protocol에서 추가 |
| argument-audit / task | 원문·핵심·논거 → 검토 | source를 제한하더라도 task마다 다시 호출 |
| fact checker / batch | 주요 사실·고정 자료 → NLI 기록 | 현재 별도 컴포넌트; 전 댓글 사실 검사 아님 |

동일한 정보를 여러 역할이 읽는 것과 동일한 판단을 반복하는 것은 다르다.
독립 검토는 유지하며, source 단독 관측과 후보/원문 관계 판정의 허용 입력을 합치지 않는다.

## B-02. 보존된 수치와 한계

2026-11-04의 **미완료 합성 12원문 실행** 두 개를 비용 병목 진단으로 사용했다.
후속 세부 prompt/검토 변경이 있는 현행 코드의 완료 비용이나 실제999개 결과가 아니다.

| 실행 범위 | usage가 있는 호출 | 확정 비용 | extraction 비용 비중 | 전체 품질 완료 |
| --- | ---: | ---: | ---: | --- |
| 보존 실행 v2 | 288 | $0.5298163 | 약5.10% | 아니오 |
| 보존 실행 v3 | 255 | $0.4471032 | 약6.05% | 아니오 |

v2의 주요 stage 집계:

| stage | 호출 | 비용 USD |
| --- | ---: | ---: |
| equivalence | 41 | 0.060542 |
| membership-initial-raw | 39 | 0.0594222 |
| argument-audit | 24 | 0.0611858 |
| raw-candidate-route | 21 | 0.0543280 |
| argument-node-metadata | 16 | 0.0445005 |
| nomination-raw | 19 | 0.0409852 |
| raw-own-evidence | 27 | 0.0296740 |
| extract | 12 | 0.0270177 |

추출 단계만 낮춰서는 이 실행의 대부분 비용이 남는다. 다만 이 비중이 다른 영상에서도 같다고 주장하지 않는다.
완료되지 않은 12개 비용을 선형 배수로 계산해 “한 영상당5만원” 같은 서비스 단가로 고정하지 않는다.

완전히 동일한 요청은 288개 중15개였고 비용은 $0.0165283(약3.1%)였다.
따라서 단순 hash 캐시 추가만으로 해결됐다고 할 수 없다. 실행 내 캐시·같은 계획 재개는 이미 있다.

고정8 membership 비교에서는 단건8호출 $0.022632, batch4의2호출 $0.025332였다.
입력 감소에도 캐시 효과·출력 비용 차이로 총 실청구가 증가했다. 긍정/비긍정은8/8 같았지만 전체 라벨은7/8이었다.
이 비교는 전체 품질 게이트가 아니며 해당 batch4 비용 최적화를 채택하지 않은 결과다.
새 설계는 같은 experiment를 비용을 들여 반복하지 않고 이 음성 결과를 기준선으로 유지한다.

위 수치의 비공개 근거 식별자:
`scale-cost-analysis-20261104-v1`, `batching-adoption-decision-20261104-v1`,
`exact-request-duplication-audit-20261104-v1`. 공개 코드에서 독립 재현 가능한 품질 점수는 아니다.
기존 공개 설명은 [OpenRouter 안내](../OPENROUTER_FACTORY.md)에도 있다.

## B-03. 기존 상호작용의 정확한 범위

- [`grounded_runtime`](../../src/commentscope/agents/grounded_runtime.py)는 허용 claim ID를 최대3개 선택하고 host가 문장·인용을 복원한다.
  질문 역할 regex는 선택 제약이며 일반적인 질문 의미 이해나 번역기의 품질 증거가 아니다.
- [`grounded_web`](../../src/commentscope/agents/grounded_web.py)는 최대2Agent 동일 질문을 순차 실행한다.
  한 Agent의 답변을 다른 Agent에게 보내지 않으며 실패하면 해당 round의 이력을 되돌린다.
- 초기 의견은 원문 저장만 있다. 자동 공통점/차이 비교·그룹 Controller·성찰 분석/저장 API는 없다.
- 현재 app session은 메모리 중심이고 일부 manifest/turn/round를 파일로 저장한다.
  영구 room/message/성찰 저장을 이미 구현한 것으로 보고하지 않는다.
- 기존 session1시간, app전역 busy, session최대8개, request최대6개는 현재 개발 실행기의 제한이다.
  새 제품 프로토콜은 legacy 동작을 유지하는 adapter와 별도로 도입한다.

## B-04. 교체·유지·검증 표

| 현행 판단 | 후보 설계의 담당 | 처리 |
| --- | --- | --- |
| source-context/world + node type/authorship 반복 | S1/S2 source record/review | 같은 source 해석·검토 요청에서 관측하고 연결. 기존 개별 호출을 병렬로 더하지 않음 |
| candidate-world/route/inventory/core 표현 | C1 target descriptor | 후보 문구만으로 한 번 구성. donor 문맥을 숨은 정의로 추가하지 않음 |
| 동치 제안 + 양방향 범위/반례 | E1/E2 pair decision/review | 양방향 비교를 명시한 두 요청으로 통합, complete-link 승인 조건은 유지 |
| raw 지지 + own-evidence | M1/M2 관계/긍정 검토 | 독립 검토 유지. source 해석을 원문 대신 입력하지 않음 |
| node별 metadata/alignment/dependency | A1 source-target argument links | 기존 source 단위 해석에서 선택하고 현재 target에 대한 연결만 제안 |
| owner + argument audit | A2 source-target argument review | 독립 원문 검토를 한 계약으로 통합. 필수 전제 검사 유지 |
| NLI fact checks | 기존 fact packet/NLI | 재사용. 모델/임계값/자료 변경 시 기존 결과 승계 금지 |
| compiler/runtime/budget/checkpoint | 기존 모듈 + versioned adapter | 재사용. 형식만 맞춘 가짜 값으로 legacy 계약을 통과시키지 않음 |

## B-05. 아직 측정되지 않은 것

새 계약의 실제 호출 수·캐시 적중·출력 토큰·실청구·정상 보존·전체999개 활용률은 미측정이다.
complete-link의 최악 비교 수, 새 후보 누락, source 하나의 여러 주장/가정 해석, 조건 손실은 남는 위험이다.
코드의 호출 경로와 작은 과거 합성 수치만으로 새 설계의 품질·비용 우월성을 확정하지 않는다.
