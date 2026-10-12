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
