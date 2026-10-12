# 고정 주장·독립 가입: 마지막 제한 개발 비교

## 목적과 제품 경계

초기 제품은 **관점 발견 → 같은 질문 비교 → 후속 질문 → 원문 확인**이다.
실험 카드 수를 늘리는 것 자체가 목적이 아니다. 기존 질의 UI와 source-grounded runtime을 유지하며,
사람이 카드/가입을 고쳐줘야 하는 Factory 경계를 자동화할 수 있는지 제한 비교한다.
실행 중 사람/assistant의 수정·승인은 넣지 않는다. 사후 assistant 평가는 개발 평가이며 독립 gold가 아니다.

## 변경한 경계

```text
기존 frozen 댓글64개 → 기존 claim113개 / 동일 embedding·후보
  → 기존 claim 중 고정 주장 선택 (후보당 최대3개)
  → 각 전체 원문을 해당 주장 하나와 독립 비교 (anchor도 검사)
  → distinct canonical 댓글의 모델 지지 수 집계
  → 원문 인용 카드 + rare/unresolved 보존
  → 품질 기준 통과 전 agent 연결 금지
```

공통 주장/가입/상세 이유를 한 요청에서 함께 생성하던 matched V1 단계를 제거한다.
첫 target은 다른 source별 최대 cosine을 평균한 중심 claim, 이후는 선택한 claim들과 최대 유사도가 가장 낮은 claim이다.
동률은 centrality/claim ID로 결정하고 exact target 문자열만 중복 제거한다. source가 여러 claim을 가져도 중심성에 여러 표를 주지 않는다.
영문 claim은 기존 모델 추출물이므로 원문 충실성을 보장하지 않는다. anchor도 원문 관계 검사를 통과해야 지지로 센다.
주장 검사 중 target을 변경하지 않고 다른 댓글/이전 판정/사후 라벨은 모델에 보내지 않는다.
댓글은 여러 주장에 가입할 수 있으나 각 주장 안에서는 한 번만 센다. 세 댓글은 세 사람/독립 여론 표본이 아니다.

상세 이유는 새로 생성하지 않는다. 해당 댓글 **전체 원문 인용**을 표시하며, 그 전체가 모두의 공통 이유라는 뜻은 아니다.
의미가 같은 target의 semantic merge/대표 한글 제목/정제 상세 이유는 이번에 구현하지 않는다.

`raw_support`/`grounded_core`에도 고정 target은 있었다. 개념 자체를 새로운 해법으로 주장하지 않는다.
이번 차이는 최신 matched 추출·검색을 유지하면서 joint draft/assignment를 제거하고,
기존 `source-statement` v2 감사 하나로 가입을 계산하는 것이다. 예전 NLI/qualification guard cascade는 적용하지 않는다.
따라서 여러 경계가 바뀌는 **패키지 비교**이며 단일 요소의 인과 효과 증명이 아니다.

## 실행 전 고정 조건

- 구현: `src/commentscope/factory/fixed_core.py`, `experiments/fixed_core_probe.py`.
- 입력: private `runs/matched-factory-20261013/`의 plan/extraction/claim-vectors/V1/V2. 원본 완료 manifest·code와 후보 replay 확인.
- 개발64개, 다인 후보9개 → target24개 / 관계72개. 예약64개는 읽거나 실행하지 않는다.
- 원문 full own-comment, 부모 내용 제외. 동일 frozen corpus 만료 상속. 입력/코드/모델/서버 hash 고정.
- Qwen3-4B Instruct2507 Q4_K_M, context8192, GPU26, CPU6, cache-off, temperature0, seed407.
- 기존 audit v2, request당300tokens, UTF8 30,000bytes 상한. 초과/오류/unknown은 지지가 아니다. 재시도/수리0.
- 신규 호출 상한96, 완료 요청 추론 합600초. 마지막 호출은 기존 HTTP timeout180초 범위에서 예산을 넘길 수 있다.
- 원문+target+source ID가 같은 요청만 이 실행 안에서 재사용한다. 이전 실행의 모델 답변은 재사용하지 않는다.
- baseline V1/V2는 저장 결과를 사용한다. 추출/embedding은 재실행하지 않으므로 이번 시간은 전체서비스 latency가 아니다.
- plan SHA: `53b0dbc705a7c27f0b0f366d520131fb920e17a7aaa011f984886cd72fc66e40`.

통과 조건은 충실한3-source 이상 카드≥1, 모든3-source 이상 카드의 잘못된 가입0,
기존 물가3-source 공통 핵심 보존, 계속 일하겠다는 댓글을 일하지 않는다는 주장에 넣지 않음,
오류0·예산 보류0이다. 3-source 미만도 사후 검토하여 과장된 품질 주장을 막는다.
사후 합격을 위해 target/threshold/판정 기준을 바꾸지 않는다.

통과 때만 예약 표본 비교1회로 갈 수 있고, 실패하면 같은4B prompt/auditor 반복을 중단한다.
모델/학습 방식 변경 또는 MVP 범위 결정이 필요한 상태로 보고한다. 이 실험은 자동 서비스 승인이나 main 기본 경로 변경이 아니다.

## 재현

raw data/모델/생성 결과는 public Git에 없다. 허가된 로컬 artifact와 유효한 만료 기간이 필요하다.

```bash
.venv/bin/python -m unittest tests.test_fixed_core -v
.venv/bin/python -m experiments.fixed_core_probe --phase prepare --run-dir runs/fixed-core-20261013
.venv/bin/python -m experiments.fixed_core_probe --phase run --run-dir runs/fixed-core-20261013
.venv/bin/python -m experiments.fixed_core_probe --phase verify --run-dir runs/fixed-core-20261013
```

기록은 append-only라 완료한 경로에 재실행하지 않는다. `verify`는 저장 응답의 원문/target 결합과 집계를 재생하며 새 모델 호출0이다.
이전 비교의 historical 코드 hash도 검사하므로 코드가 달라지면 해당 frozen commit에서 재현해야 한다.

## 결과: 기본 미채택, 같은 계열 반복 중단

사전 코드 `b12a24f`로72개 fresh 관계 검사를 실행했다. 신규 추출/embedding/카드 재생성0,
추론 합195.09초, 오류0·예산 보류0·모든 응답 stop이다. 모델 지지23/72,3-source 카드1개다.
서버 시작·hash·기존 추출/검색 비용은 별도이며 영상 전체 분석이3분이라는 뜻이 아니다.

assistant가24target/72관계를 전체 원문과 비블라인드로 대조했다. supported15/partial28/unsupported29,
모델은 supported15/15를 유지했지만 partial8개도 승인했다. 모든 인용이 충실한 작은 카드는14개,
**충실한3-source 이상 카드는0개**다. 수치는 이 개발 평가의 결과이며 독립 gold·일반 정확도·이전 방법 대비 통계적 개선이 아니다.
이전 V1/V2와 target/검사 분모가 다르므로 오승인 비율을 직접 순위 비교하지 않는다.

### 나아진 부분과 남은 실패

- 물가3댓글이 한 고정 주장에 모였다. joint assignment의1+1+1 과분할은 이 선택에서 재발하지 않았다.
  하지만 target은 `Inflation is not solely caused by printing money, which is a supply-side factor.`이다.
  뒤의 supply-side 분류는 셋째 원문에만 있다. 첫째/둘째를 이 **전체 문장**의 지지로 세는 것은 부연의 출처 이동이다.
  좁은 앞부분만 남기면 될 듯 보여도, 사후 사람이 잘라서 성공으로 만들지 않았다.
- 중심 target 뒤에 diverse target을 고르는 방식은 다른 두 상세 주장들을 선택했다.
  더 좁은 물가 target은 원래 후보에 있지만 선택되지 않았다. core 고정만으로 원자적 공통 핵심 선택이 해결되지는 않는다.
- 계속 일하겠다는 댓글은 일하지 않겠다는 target에서 거절됐다. 세 댓글이 있다는 이유로 반대 입장을 묶지 않았다.
- generated details를 없애 새 상세 이유를 섞는 단계는 제거했지만 기존 추출 claim의 조건/범위 손실은 남는다.
  생산 증가/유지 조건의 합침, large amount의 규모 조건 누락, 개인 조건부 비용 예측의 일반화,
  can be 추측의 강화, 트럭 가정/most likely의 일반화, 일자리 창출 부재를 대체 관계로 해석한 사례가 통과했다.
- 일부 올바른 거절도 모델 설명은 틀렸다. 예를 들어 추가한 조건을 오히려 'omits'라고 설명했다.
  최종 enum과 모델이 쓴 이유가 모두 의미 증명인 것은 아니다.

정상 관계 보존과 반대 입장 거절은 관측했지만 사전 기준 중 유효3-source 카드/오가입0/물가 전체 주장 충실성이 실패했다.
**예약64개·1,000개 확대·새 agent·UI 기본 연결을 실행하지 않는다. 같은4B prompt/auditor 계열의 다음 변형도 자동으로 이어가지 않는다.**
사용자와 약속한 개선 비교1회는 소진했다. 추가 모델 호출은 없다.

### 다음 의사결정 경계

초기 제품 목표나 원문 충실성 원칙을 바꿀 이유는 없다. 원문/검색/독립 가입/집계/질의 UI의 교체 가능한 경계는 유지한다.
남은 핵심은 **어떤 좁은 명제를 고를지, 한 원문이 그 전체를 지지하는지 판단하는 의미 모듈**이다.
단순히 같은 모델에게 검사 항목을 더 붙이는 작업을 다음 task로 등록하지 않는다.
모델/학습 방식 변경 또는 MVP 범위를 명시적으로 결정한 뒤 다음 실행을 정한다.
이전8B 단독 교체도 실패했으므로 '더 크면 해결'로 가정하지 않는다. 유료 API·새 다운로드·학습·수동 runtime 검수는 이번에 추가하지 않았다.

기존 review-assisted2-agent 로컬 비교/후속질문/원문확인 데모는 유지되지만 **무인 자동 Factory→agent MVP 완료는 아니다.**
이 모듈은 opt-in이며 `model_support_count`와 검증된 지지 수를 분리하고 `agents=[]`를 유지한다.

### 증거 위치

- private `runs/fixed-core-20261013/overview.html`:24target/72원문 관계/모델 응답.
- private `runs/fixed-core-20261013/assistant-review.html`:전체 관계의 assistant 판정·원문·이유.
- `assistant-ratings.json`은 plan/report hash에 결합하며 `runtime_input=false`, `independent_gold=false`, `blinded=false`다.
- report SHA `026d70a336f70c76dbf729406176165be0925c2f19ff6d60c406d3bed3737691`.
- completed SHA `e34e68c345b421eb759cc00a5dece63470d33a087744afe6c6762a894b5d846a`.
- 새 모델0회로72관계의 요청 원문/고정 target/응답/집계를 replay했다. 사후 검토 도구는 별도 추가이며 추론 코드는 수정하지 않았다.
- 신규 구현14개·사후 검토5개 회귀를 추가했다. 로컬 Python511/Node4 통과, 소유 서버PID44692 returncode0 종료·부재 확인.
