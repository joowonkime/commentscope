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

## 실행 결과 2026-10-13

**위치 근거를 요구하는 이번 패키지는 기존보다 악화됐으며 채택하지 않는다.** 오승인 감소만으로 개선이라고 부르지 않는다.
사전 코드 `b2338ce`, private `runs/eligibility-witness-20261013/`에96회 새 추론과 전수 검토를 보존했다.
plan SHA256 `4d8a9ebe0d710a28de15d5a5094a0ddbe5ad06a3df060941ede1d2315363a6d0`,
report SHA256 `b0031b0b7a419518e39d35a65f2752395e1b9a751f1c0c19735fc60238ca019f`.

| 조건 | 기존 정상 통과 | 기존 제외 오승인 | 이전 대비 정상 통과 | 이전 대비 제외 오승인 | 새 대비 정상 통과 | 새 대비 제외 오승인 |
|---|---:|---:|---:|---:|---:|---:|
| source_only | 8/8 | 5/8 | 7/8 | 4/8 | 8/8 | 6/8 |
| witness | 2/8 | 0/8 | 0/8 | 1/8 | 3/8 | 0/8 |

정상 source의 eligible 판정은23/24→5/24, 제외 source의 오승인은15/24→1/24다.
이 정상5개도 아래처럼 후보 근거가 불완전하므로 **유효한 주장5개를 복원했다는 의미가 아니다.**
새 대비의 eligible이면서 필수 구간을 정확히 보존한 경우는0/7이다. 사전6개 기준 중 오류0만 통과했다.
실제 표본 시험 진입·기본 필터 연결·agent 생성은 하지 않았다.

source_only는 eligible38/excluded10이다. witness는 eligible6/excluded18/uncertain23/context_dependent1이다.
제외 대상24개 중 witness는15개 excluded,7개 uncertain,1개 context_dependent,1개 eligible이다.
보류8개를 올바른 의미 제외8개라고 합산하지 않는다. 정상24개는5개 eligible,16개 uncertain,3개 excluded다.

추론 합은 기존40.47초/위치 근거222.59초, 출력 token490/3502였다. 총263.06초이며 서버 기동·hash·저장을 제외한다.
같은 부분GPU 환경의 이번48개 결과이며 전체 clustering 성능 수치가 아니다. 비용도 늘어 기본 연결의 근거가 없다.

## 관측된 실패

48원문·96출력과 코드가 결합한55개 범위를 assistant가 검토했다. 독립 평가자나 인간 gold가 아니다.

1. **구조 모순과 정상 손실.** context는 resolved29/missing19이고 independent/unclear는0이었다.
   코드가 보류한23개는 해결 근거 부재19, candidate 밖 참조1, 자기 참조3이다. 이 중 정상16/제외7개다.
   완전한 정상 문장을 선택하고도 resolved와 빈 references를 함께 반환해 보류된 경우가 있다.
   코드가 계약대로 동작한 사실과 모델이 의미를 올바르게 판단한 사실은 다르다.
2. **유효한 위치에 잘못된 내용.** 정상 source에서 통과한5개 candidate는 `late. It`, `get $820`,
   `would work more hours.`, `should stay open until`, `I could finish my`였다.
   숫자는 범위 안에 있었지만 완전한 주장이 아니었다. 주체·수치 주기·조건·문장 끝이 빠졌고 참조 관계도 맞지 않았다.
   단어 배열만 제공하고 인덱스 선택까지 맡긴 부담은 의심 원인이지만, 입력 표현만 분리한 대조가 아니므로 인과로 확정하지 않는다.
3. **남은 의미 오승인.** 한국어 단순 동의에서 `말에 동의합니다.`→`그`를 연결해 eligible이 됐다.
   원문에 존재하는 서로 다른 범위라는 조건은 충족했지만 `그`는 빠진 주장의 내용을 제공하지 않는다.
4. **혼합 발화와 인용.** 기존 질문+경험 댓글은 여전히 질문으로 통째로 제외됐다. 새 버스 요금+농담 정상도 반응으로 제외됐다.
   독립 인용2개는 제외했지만 명시적 인용 채택도 통과하지 못했다. author_commitment는 direct30/attributed7/unclear11,
   endorsed0이고 endorsement 범위도0개다. 인용 처리 일반화 성공으로 읽지 않는다.

기존32개의 baseline 요청과 parsed 출력은 직전 source-only 실행과 동일했다. 양쪽 prompt 최대391/954tokens,
완료 최대11/122tokens, finish_reason은 전부 stop이고 형식/전송/위치 오류0이었다. context4096/max_tokens900 한도 소진은 관측되지 않았다.
따라서 이번 실패를 출력 잘림이나 JSON 오류로 설명하지 않는다. prompt·표현·schema 중 어떤 요소가 주 원인인지는 분리하지 못했다.

모든 응답 모델 경로·library hash가 일치했고 cached_tokens0/nonempty reasoning_content0이었다.
소유 서버2개는 종료코드0으로 종료됐고 저장96개 재생은 새 모델 호출0으로 일치했다.
Python455/Node4 및 Linux·Windows CI 통과다. 테스트 통과는 의미 품질 통과가 아니다.

## 다음 구현 경계

이번 버전의 단어 위치·참조 그래프 생성을 서비스에 연결하지 않는다. resolved+빈 근거를 사후 승인하거나
통과한 불완전 조각을 성공으로 재분류하지 않는다. 기존 source-only 역시 오승인 때문에 기본 필터 후보가 아니다.

다음은 **이미 구현된 추출형 문장 후보 baseline을 재사용**해 완전한 원문 문장 ID를 코드가 제공하고,
모델은 후보 선택과 필요한 문맥의 존재 여부만 제한적으로 판단하는 비교를 설계한다.
단어 인덱스 계산과 참조 그래프 작성은 맡기지 않는다. 기존 문장 후보 baseline도 과거 실패했으므로 이것만으로 해결됐다고 가정하지 않는다.
혼합 발화·조건·선행 문맥의 보존과 정상 손실을 같은 기준으로 다시 확인해야 하며, 추가 감사 계층이나 전수 의미 복원은 넣지 않는다.
이 단순화는 미구현 가설이며 다음 단계다. 현재 원문 registry·검색·생성기·충실성·지지 집계·agent 연결은 그대로다.
