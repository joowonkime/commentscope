# 원문만 보는 주장 자격 검사 비교

독립적인 주장이 있는지 판단하는 자격 검사와 특정 target을 지지하는지 판단하는 충실성 검사를 분리한다.
기존 합동 감사가 질문·단순 반응까지 승인한 문제를 대상으로 한 opt-in 실험이며, 기본 Factory나 원문 registry를 변경하지 않는다.

## 사전 고정 대조

기존 evidence-unit16개와 새로운 대비16개, 총32고유 원문을 사용한다. 각 군은 정상8/제외8이다.
새 대비는 질문/진술, 해결된/미해결 지시어, 명시된/생략된 권고, 영상 의견/도착 반응, 주장/인용,
질문에 경험이 섞인 댓글, 농담에 실제 주장이 섞인 댓글, 한국어2개를 포함한다.
모든 기대는 추론 전에 고정한 assistant 개발 라벨이다. 알려진 실패를 보고 작성했으므로 독립 holdout이 아니다.

| 조건 | 입력 | 출력 |
|---|---|---|
| joint | SOURCE와 동일 문자열 TARGET | 기존 assertion/eligibility/6속성/evidence |
| eligibility_with_target | SOURCE와 동일 문자열 TARGET | eligibility만 |
| source_only | SOURCE만 | eligibility만 |

뒤 두 조건은 system/schema가 같고 입력의 TARGET 필드만 다르다. 둘 다 TARGET은 자격 근거가 아니라고 명시한다.
joint와 자격 전용의 차이는 prompt/schema/역할 명료화가 함께 바뀐 **분리 패키지 효과**다.
그 결과를 TARGET 제거 하나의 인과 효과로 설명하지 않는다. 혼합 댓글에서 최소 한 독립 주장이 있는지 보는 정책도 명시했다.

각 조건을 새4B 서버에서32회씩 총96회 실행한다. 조건 순서는 표 순서, source 순서는 ID 정렬로 고정한다.
지난 모델 비교의 Qwen3-4B-Instruct-2507 Q4_K_M/revision/hash/llama.cpp b11541을 유지한다.
양쪽 전용 검사와 joint 모두 context4096/GPU26layers/CPU6threads/parallel1/cache-off/non-thinking,
temperature0/seed407/max_tokens900이다. 새 모델 다운로드/추가 수집/외부 댓글 전송은 없다.
조건당600초를 호출 전에 확인하며 진행 중 요청에는 기존180초 timeout이 적용된다. 재시도·repair·부분 실행 재개는 없다.

## 모듈과 판정 경계

`factory/source_eligibility.py`는 SOURCE만 받는 요청 생성, 엄격한 단일 enum 검증, host 상태 매핑을 제공한다.
원문4,000자/80segments 한도를 넘으면 잘라 쓰지 않고 거절한다. 기대 라벨/다른 댓글/후보 target은 입력하지 않는다.
자격은 substantive→eligible, non_substantive→excluded, context_dependent→동명 보류, unclear→uncertain이다.
형식·전송 오류는 error이며 미확정을 승인하거나 맞게 제외한 것으로 세지 않는다.

비교의 주 지표는 **eligibility 필드**다. joint의 전체 projection이 충실성 이유로 실패해도 자격을 잘 분류했다고 세지 않는다.
자격 통과는 target 지지나 agent 승인이 아니다. 여러 문장이 있는 댓글의 자격 통과는 그 안의 모든 문장 자격을 보장하지 않는다.
원문은 검사 결과와 관계없이 보존한다. 이번 코드에는 corpus 필터/지지 집계/서비스 cache 연결이 없다.
`identity`는 source·모델 식별정보·prompt/schema/version에 결합한 향후 재사용 키이며 실제 cache 구현이나 채택은 아니다.
실제 연결 시 모델 식별정보에는 가중치 hash/revision/양자화와 실행 프로파일까지 포함해야 한다. 모델명만으로 환경 간 결과를 공유하지 않는다.

## 사전 통과 기준

source_only가 기존 정상8/8, 새 대비 정상7/8 이상을 보존하고 두 군에서 제외 대상 오승인0·오류0이면
**다음 실제 데이터 시험의 후보 자격만** 얻는다. 사람이 서비스 중 승인하는 단계나 자동 품질 승격을 추가하지 않는다.
전용 검사 간 label 변화와 원문별 실패를 전수 공개한다. 통과해도 새 실제 표본·원문별 재사용·전체 충실성 경로 연결은 별도 검증이다.
기존 OpenJev typed routing 실패와 별도이며 같은 문제를 해결했다고 미리 가정하지 않는다.

## 실행과 재생

기존 private 모델 비교 plan과 로컬4B/런타임이 필요하다. 모델 기동/종료는 이전 소유 서버 helper를 재사용한다.
이미 실행 중인 localhost8091 서버에는 접속하지 않고 실패하며, 자신이 생성한 서버만 종료한다.

```bash
python -m experiments.source_eligibility_probe --run-dir runs/NEW-ELIGIBILITY --phase plan --diagnostic-only
python -m experiments.source_eligibility_probe --run-dir runs/NEW-ELIGIBILITY --phase run --diagnostic-only
python -m experiments.source_eligibility_probe --run-dir runs/NEW-ELIGIBILITY --phase verify --diagnostic-only
```

private plan/attempt/report는 원문·출력과 code/model hash를 결합하고 snapshot 만료를 상속한다.
verify는 새 추론0으로 요청·순서·출력·집계를 재계산한다. overview.html에서32원문/96출력을 확인한다.
공개 저장소에는 코드·합성 fixture·설계·집계만 저장한다.
