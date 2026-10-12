# 원문 문장 후보 선택 비교

공통 문장을 새로 생성하지 않고 원문 문장을 논점 후보로 고정한다. 선택기는 생성형 LLM을 사용하지 않는다.
문자 보존·후보 노출과 실제 의미 지지는 별도 평가하며, 기존 판정기나 기본 Factory를 교체하지 않는 비교 경로다.

## 입력과 선택 계약

- 이미 정해진 두 canonical 댓글 안에서 기존 punctuation/newline splitter로 문장 구간을 만든다.
  모든 구간에 source ID/digest/offset/문자열을 결합한다. 짧은 문장도 제거하지 않고 자격은 후속 검사에서 판단한다.
- source4,000자/80segments, target249자 한도를 유지한다. 초과 구간은 원문 그대로 보존하되 deferred_input으로 표시한다.
  긴 문장을 자르거나 짧게 다시 쓰지 않는다. 한 문장만 쓰므로 인접 문맥이 필요한 주장을 놓칠 수 있다.
- 기존 고정 multilingual MiniLM 임베딩을 사용한다. 긴 임베딩 입력은 기존 token chunk 집계로 처리하며 silently truncate하지 않는다.
- 각 후보의 반대쪽 댓글 문장에 대한 최대 cosine으로 순위를 정하고 **각 댓글 상위2개**를 교대로 큐에 넣는다.
  동점은 candidate ID로 고정한다. 동일 문자열은 제안 하나로 묶고 선택된 origin은 보존한다.
  위치 선택 reference·기준 주장·정답 라벨은 순위 함수에 전달하지 않는다.
- similarity threshold로 승인하지 않는다. 선택되지 않은 후보도 budget/no_other_candidate 상태로 보존한다.
  후보 수/유사도/원문 출처 수를 지지 수로 세지 않는다.
- 선택된 exact 문자열을 target으로 기존 positional-support의 전체 원문 NLI→속성 감사→근거 NLI에 전달한다.
  출처 댓글도 포함해 두 댓글을 각각 검사하며 origin 자동 지지, peer 내용 전이, 생성 제안 호출은 없다.

## 고정 평가

기존 합성12쌍(정상6/부정6)과 실제3쌍을 모두 사용한다. 추론 전 코드/plan을 고정한다.
이전 assistant reference는 **선택 후 노출 측정**에만 쓰며 새로운 수동 선택은 없다.
실제3쌍 중 일부 reference의 해석 불확실성도 그대로 상속한다.

순서대로 원문/구간 보존, 알려진 구간의 후보 노출, 모델의 양쪽 통과, 통과 target의 assistant 원문 대조를 보고한다.
pair compatibility 라벨은 특정 target의 충실성 라벨이 아니므로 부정 pair 통과도 target별로 재검토한다.
모델 통과 target 전수와 과거 실패 관련 target을 사후 검토하되 기존 판정/라벨을 수정하지 않는다.

최대LLM160/NLI200checkpoint, 생성 제안0, 전체64/1000확장0, agent0. 모델/프롬프트/NLI0.8은 유지한다.
후보를 최대4개 검사하므로 이전 한 제안 방식과 같은 비용 비교는 아니다. 의미 검사 비용은 사라지지 않는다.
반복 개발군이지 독립 gold나 일반 성능 증명은 아니며 기본 승격은 하지 않는다.

## 실행과 재현

기존 private component-isolation/positional-support plan과 report가 필요하다. 로컬 모델 환경은 README를 따른다.

```bash
python -m experiments.extractive_candidates_probe --run-dir runs/NEW-EXTRACTIVE --phase plan --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.extractive_candidates_probe \
  --run-dir runs/NEW-EXTRACTIVE --phase run --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.extractive_candidates_probe \
  --run-dir runs/NEW-EXTRACTIVE --phase verify --diagnostic-only
```

plan/원문/vector/모델 요청·출력/report/measurements/HTML은 Git 제외하며 원래 snapshot 만료를 상속한다.
verify는 저장 vector와 checkpoint로만 재현하고 신규 모델 호출이 필요하면 실패한다.

## 실행 결과 2026 10 12

코드 `0b7c026`과 plan을 추론 전에 고정했다. 선택 기준/모델/prompt/threshold를 실행 중 바꾸지 않았다.
**후보 노출은 성공했지만 실제 공통 지지·agent 생성은 성공하지 못했다.**

| 항목 | 결과 |
| --- | --- |
| 고유 source / 원문 구간 | 29 / 48 |
| 길이 한도 내 구간 / 원문 유지 후 보류 | 45 / 3 |
| 평가한 exact target / source–target 판정 | 36 / 72 |
| 실제 reference 양쪽 노출 | 3/3, 각 핵심 문장은 양쪽 모두1순위 |
| 실제 양쪽 모델 통과 | 0/3쌍 |
| 합성 정상 양쪽 통과 | 2/6쌍,3target |
| 합성 부정 양쪽 통과 | 0/6쌍 |
| source–target 상태 | support34 / uncertain19 / not_supported19 / error0 / unchecked0 |

선택기는 reference를 받지 않았고 proposal 호출0이었다. 노출3/3은 알려진 작은 개발군의 검색 결과이지 일반 recall이나 의미 승인율이 아니다.
36target을 사후 assistant 검토했다. 통과3target은 대기오염 감소1개와 같은 여행 의사 쌍의 표현2개다.
모두 해당 두 원문에 충실했지만 독립3개관점이 아니며, 실제 데이터에서는 통과target이 없다.

### 해결한 부분과 남은 실패

- 원문을 다시 쓰지 않아 이번 여행 의사 후보에는 요금 조건이 그대로 남았다. 이전 생성기의 일반 가격으로 확장하는 오류가 재발하지 않았다.
  모든36target의 문자·출처 결합이 일치한다. 그렇다고 다른 댓글의 지지나 독립 대표 주장 자격까지 보장되지는 않는다.
- 실제3쌍의 핵심 문장이 선택 단계에서 소실되지 않았다. 다만 취업 의사 쌍은 take a job/stop working 차이가 남아
  단일 원문 문장이 바로 최소 공통 주장이라고 볼 수 없다. 긴 물가 쌍도 표현 범위와 불필요한 조건절을 포함한 근거 선택 문제가 남는다.
- 짧은 물가 쌍의 literal target은 Rising을 포함한다. 양쪽 full NLI는 통과했지만 peer 감사가 time=unclear로 보류했다.
  이전 성공한 축약 target과 동일하지 않으므로 이를 무조건 동일 입력의 과잉거절로 해석하지 않는다.
- 재택근무·내년 열차 이용 증가의 정상 재표현은 여전히 host 감사에서 거절된다.
  도서관 문장은 각각 서로 다른 이유를 포함하므로 **단일 문장 복사만으로 최소 공통 권고를 표현할 수 없는 한계**도 확인했다.
- 모호한 동의 표현도 출처 자체에서는 substantive/support로 승인됐다. 다른 댓글에서 막혀 pair 통과는 없지만,
  원문 복사만으로 대표 주장 자격 문제가 해결됐다고 볼 수 없다. 임계값 완화/unknown 승인/조건 guard 제거는 하지 않았다.

### 새 추론 반복성에 관한 추가 관측

이전 component-isolation 실행과 **system/data/schema가 동일한 요청10개 중1개**의 출력이 달랐다.
안전검사 합성 사례에서 conditions가 preserved→unclear로 바뀌어 출처 자체 판정이 support→uncertain이 됐다.
Qwen 파일/server 실행 파일 hash와 명시 설정은 같았다. 다른 positional 실행과 겹친7개 요청에서는 차이가 없었다.
원인은 아직 확정하지 않았으며 요청 순서·런타임 상태 등을 통제한 반복 시험이 필요하다.
저장 checkpoint를 읽는 replay 일치는 **새 모델 추론의 결정성 증명과 다르다**.

### 시간과 재현

- 총123.54초: embedding 로딩·추론·cache11.90초, 순위 계산0.006초. 신규 embedding1/LLM45/NLI79 checkpoint.
  선택·제안용 생성형 호출은0이지만 의미 감사 호출45회는 남는다. 15쌍 진단이므로 전체 서비스 latency/동일 비용 개선 수치가 아니다.
- 형식 수리0/transport 오류0. source에 대한 target36회·저장 evidence44회 위치 재결합 일치.
  replay 새 embedding/LLM/NLI0으로 전체 report 일치. Python400개·Node4개 통과. 자체 모델 서버 종료.
- private `runs/extractive-candidates-20261012/review.html`은36target 검토, `overview.html`은 후보·보류·전체 trace다.
  `assistant-review.json`은 report hash 결합 의미 평가와 동일 요청 변화 관측이다. 독립 gold나 서비스 수동 승인 파일이 아니다.
- plan SHA256 `b9aead8e4e5ae3a9dc3119ab864216d542341ee20ff61bddbc9efb84c1200417`,
  report SHA256 `abdd62c6c71798fe80fccf194c42e8e55738ee818da6d20d0bc083749fb03bb4`.
- 기본 경로/main은 변경하지 않았다. 전체64/1000확장0, ledger0, 새 agent0. 자동 MVP 품질 미완료다.

## 다음 우선순위

이 후보 선택기를 비교 기준으로 고정하고, **동일한 감사 요청의 새 추론 반복성**을 먼저 좁은 표본에서 검증한다.
그다음 고정 원문→target 정상/왜곡 대조군으로 판정기 교체 후보를 비교한다. 생성기와 동시에 바꿔 원인을 섞지 않는다.
공통 이유를 분리하는 문장보다 작은 단위의 후보는 별도 과제다. 현재 단일 문장 baseline으로 모든 생성 문제가 해결됐다고 간주하지 않는다.
