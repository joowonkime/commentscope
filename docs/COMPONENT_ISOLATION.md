# 논점 생성과 지지 판정의 분리 진단

위치 기반 판정에서 의미 품질이 악화돼, 서비스 경로를 더 늘리지 않고 단계별 입력을 통제한다.
기존 모델·프롬프트·threshold·기본 Factory는 그대로다. 미리 선택한 근거와 기준 주장은 **진단 개입**이며
사람의 선택을 runtime에 넣거나 자동 생성 성과로 세지 않는다.

## 비교 설계

고정 합성 정상6쌍과 기존 실제3쌍을 모두 포함한다. 실제 원문과 선택 ID는 private reference-spec에만 저장한다.
추론 전에 코드·spec·plan을 hash로 고정한다. 출력에 맞춰 기준 주장을 바꾸지 않는다.

| 분리 대상 | 변경하는 입력 | 유지하는 부분 |
| --- | --- | --- |
| 구간 선택이 생성에 미치는 영향 | 전체 원문 / 기존 자동 선택 구간 / assistant 사전 선택 구간 | 같은 제안 프롬프트·모델·schema |
| 생성기와 검사기 구분 | 생성된 주장 / 사전 고정 기준 주장 | 원문별 독립 지지 판정 |
| 문맥이 검사기에 미치는 영향 | 전체 원문 / 사전 선택 원문 구간 | 같은 고정 기준 주장·판정 코드 |

제안기는 reference core·라벨·rationale를 받지 않는다. 생성된 주장은 어떤 입력 조건이든 **전체 원문 각각**으로 검사한다.
고정 기준 주장의 구간-only 검사는 별도 진단이며 전체 원문 승인으로 간주하지 않는다.
자동 선택 실패는 no_alignment로 남고 전체 원문으로 조용히 fallback하지 않는다.

기존 직접 판정48개는 저장 trace로 NLI-only와 전체 검사를 비교한다. 부정 사례에서 NLI-only 오승인을 함께 보며
검사를 빼서 정상 통과를 늘리는 것을 안전한 개선으로 부르지 않는다. 이 부분에는 새 추론이 없다.

실제3쌍 중 취업 의사와 긴 물가 쌍의 기준 주장은 assistant 해석이 들어간 candidate_requires_review다.
취업 원문의 오타·hedging, money availability와 printing money의 차이를 명시한다.
기존 pair compatibility 라벨은 변경하지 않되 그것이 특정 core의 정답임을 뜻하지 않는다는 한계를 분리한다.

## 실행 경계

- 최대 신규 LLM190/NLI190 checkpoint. 로컬 Qwen GPU와 DeBERTa CPU, 기존0.8threshold와 예산을 유지한다.
- 원문·출력·사전 선택 spec·plan/report·HTML은 Git 제외하고 snapshot 만료를 상속한다.
- 합성/실제·고정 기준/생성 결과·모델 통과/assistant 사후 검토를 별도로 보고한다.
- 모든 진단이 통과해도 agent0, quality_gate_passed=false다. 전체1000개 실행과 기본 승격은 하지 않는다.
- 작은 반복 개발군과 공유 source이므로 독립 정확도나 모델 일반 성능을 주장하지 않는다.

## 재현

기존 private `runs/positional-support-20261012/`와 사전 작성 reference-spec이 필요하다.
spec은 각 pair ID별 두 원문 S-ID 범위, reference_core, confidence, rationale를 갖는다.
README의 로컬 모델 환경과 localhost8091 서버를 사용한다.

```bash
python -m experiments.component_isolation_probe --run-dir runs/NEW-ISOLATION \
  --spec runs/NEW-ISOLATION/reference-spec.json --phase plan --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.component_isolation_probe \
  --run-dir runs/NEW-ISOLATION --phase run --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.component_isolation_probe \
  --run-dir runs/NEW-ISOLATION --phase verify --diagnostic-only
```

verify는 cache만 읽고 새 모델 호출이 필요하면 실패한다. 생성 문장은 원문 대조 사후 검토를 별도로 저장한다.
