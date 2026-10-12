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

## 결과

실행 전. 기존 review-assisted 2-agent 데모만 검증된 상태이며 자동 Factory 품질 완료는 아니다.
