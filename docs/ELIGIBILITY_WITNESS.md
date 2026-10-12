# 원문 위치 근거를 갖춘 자격 검사

단일 자격 라벨의 남은 지시 대상·인용 오승인과 혼합 댓글 손실을 대상으로, 주장 구간과 필요한 근거를 함께 제출하는
opt-in 검사다. 기본 생성기·후보 선택기·충실성 감사·원문 registry는 변경하지 않는다. 위치 일치가 의미 정확성을 보장하지 않는다.

## 계약과 코드 판정

`factory/eligibility_witness.py`는 전체 SOURCE와 공백 기준 WORDS를 전달한다. 모델은 반열린 단어 범위 `[start,end)`로
하나의 최소 완전 주장 candidate, 발화 유형, 작성자 입장, endorsement 범위, context 상태와 mention→antecedent 관계를 반환한다.
target·평가 라벨·다른 댓글은 입력하지 않고 새로운 주장 문장을 생성하지 않는다. 원문 문자 위치와 실제 문자열은 코드가 복원한다.

발화 유형은 assertion/question/reaction/quotation/joke/unclear, 작성자 입장은 direct/endorsed/attributed/unclear,
문맥 상태는 independent/resolved/missing/unclear다. 질문이나 단순 동의로 시작해도 뒤의 독립 주장 구간을 선택하도록 한다.
인용을 명시적으로 채택했다면 candidate 밖의 동의 구간을 요구한다. 분리 불가능하면 unclear이며 이 제한의 손실도 평가한다.

코드는 범위의 정수·경계·키를 검증한다. 잘못된 형식은 error다. 위치가 맞아도 다음 구조 모순은 uncertain으로 보류한다.

- resolved인데 관계가 없거나 antecedent가 빠짐, independent인데 필요한 관계를 제출함.
- mention이 candidate 밖이거나 중복됨, antecedent와 mention이 겹침.
- endorsed인데 동의 근거가 없음, 다른 입장에 동의 근거를 제출함, 동의 근거와 candidate가 겹침.

유효한 구조에서 비주장/타인 인용은 excluded, 필요한 문맥 부재는 context_dependent, 불확실/빈 후보는 uncertain이다.
나머지만 eligible이다. 이 값은 source의 한 주장 자격이지 모든 문장의 자격·충실성·cluster 지지·agent 승인이 아니다.
모델이 잘못된 연결을 만들거나 필요한 관계를 아예 누락해도 코드가 모두 알아낼 수는 없다.

원문 4,000자·128공백 단위 token을 넘으면 잘라 쓰지 않고 `ValueError`로 보류 신호를 낸다.
이 opt-in 요청 경계는 서비스의 댓글 삭제 정책이 아니다. 공백 단위는 다국어 형태소 분석이 아니며 문자열 보존만 보장한다.
최대 candidate1개·관계4개이고 전체 주장 복원이나 exhaustive extraction이 목적이 아니다. 실제 cache·서비스 필터 연결은 없다.

## 사전 고정 비교

기존32개에 새 대비16개를 추가한다. 각 군 정상8/제외8, 총48고유 합성 원문이다. 새 대비는 질문/동의/농담과 실질 주장의 혼합,
인용의 채택/미채택/반대, 해결된/생략된 지시 대상, 조건부 개인 주장, 한국어 혼합 댓글을 포함한다.
모든 라벨은 알려진 실패를 참고해 추론 전에 고정한 assistant 개발 기대이며 독립 holdout이나 인간 gold가 아니다.

| 조건 | 작업 | 호출 |
|---|---|---:|
| source_only | 기존 source-eligibility0.1 단일 enum 그대로 | 48 |
| witness | 원문 위치 근거와 코드의 구조 판정 | 48 |

Qwen3-4B-Instruct-2507 Q4_K_M·llama.cpp b11541, context4096/GPU26layers/CPU6threads/parallel1,
cache-off/non-thinking/temperature0/seed407/max_tokens900은 직전 실험과 같다. 같은48개를 조건마다 새 서버에서 실행한다.
조건 순서는 표 순서, source는 ID 정렬이다. prompt·입력 표현·schema가 함께 바뀌므로 위치 필드 하나의 인과 효과로 읽지 않는다.
조건당900초를 호출 전에 확인하고 진행 중 요청에는 기존180초 timeout이 적용된다. 총96회, retry/repair/부분실행 재개0이다.

각 군 정상8/8·제외 오승인0·오류0, 새 대비의 `required_text`7개 모두 정확한 저장 근거 안에 보존돼야
다음 실제 표본 시험의 후보가 된다. `required_text`는 offline 평가에만 쓰고 모델/코드 승인에 입력하지 않는다.
이는 선택한 근거에 필수 구간이 있는지의 최소 검사이지 의미적 완전성 증명이 아니다. 통과해도 기본 연결은 별도 결정이다.

## 실행과 보존

기존 private `runs/source-eligibility-20261013/plan.json`과 로컬 모델·서버가 필요하다. public fixture만으로 과거 private 실행을 재현할 수는 없다.
8091이 사용 중이면 실패하며 기존 프로세스에 연결하거나 종료하지 않는다. 실험이 만든 서버만 종료한다.

```bash
python -m experiments.eligibility_witness_probe --run-dir runs/NEW-WITNESS --phase plan --diagnostic-only
python -m experiments.eligibility_witness_probe --run-dir runs/NEW-WITNESS --phase run --diagnostic-only
python -m experiments.eligibility_witness_probe --run-dir runs/NEW-WITNESS --phase verify --diagnostic-only
```

plan은 입력·코드·모델·런타임과 모든 요청을 고정한다. attempt는 raw HTTP/parsed output/시간/host 판정과 hash를 보존한다.
verify는 추론0회로 요청·순서·출력·위치 결합·집계를 재계산한다. `overview.html`에서 모든48원문/96출력을 확인한다.
공개 Git에는 코드·합성 fixture·설계·집계만 기록하며 실제 댓글·모델 출력·가중치·키는 포함하지 않는다.

## 실행 상태

계약과 대비 사례를 고정했으며 실제 추론은 아직 실행 전이다. 효과를 확인하기 전 기본 경로나 agent에 연결하지 않는다.
