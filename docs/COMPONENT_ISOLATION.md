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

## 실행 결과 2026 10 12

코드 `446adaa`와 사전 spec을 고정한 뒤 기존 로컬 모델로 실행했다. 이번에는 prompt/schema/threshold를 바꾸지 않았다.
결론은 **생성 실패와 판정 실패가 모두 존재하며, 자동 구간 선택이 성공 가능한 실제 주장도 잃게 한다**는 것이다.
기본 경로 변경이나 모델 일반 성능 개선을 입증한 것은 아니다.

| 모델의 양쪽 원문 통과 | 전체 원문으로 제안 | 자동 선택 구간으로 제안 | 사전 선택 구간으로 제안 |
| --- | --- | --- | --- |
| 합성 정상6쌍 | 2/6 | 2/6 | 2/6 |
| 실제 개발3쌍 | 1/3 | 0/3 | 1/3 |

합성 통과2개 중1개는 사후 검토에서 수정이 필요했다. 따라서 이 표는 모델 동의율이지 생성 정확도가 아니다.
합성 사례는 한 문장씩이라 세 조건 입력이 같고, 같은 요청은 cache를 공유한다. 27개의 독립 표본으로 세지 않는다.

### 분리된 실패와 성공

1. 실제 물가 댓글 한 쌍은 전체 원문과 사전 선택 첫 문장 모두에서 ‘화폐 발행만이 물가 상승의 원인은 아니다’라는
   공통 주장이 나왔고 두 전체 원문 검사도 통과했다. assistant 원문 대조에서도 충실했다.
   자동 선택기는 왼쪽 첫 문장을 빠뜨렸고, 제안은 구매력 감소를 포함한 일반 정의로 바뀌어 실패했다.
   이 사례에서는 새 생성 모델 없이도 제안이 가능하며 선택기가 실패 지점이다. 전체 원문 조건도 성공하므로
   사전 수동 선택이 유일한 성공 방법이거나 새 자동 selector가 완성됐다고 볼 수는 없다.
2. 재택근무·내년 열차 이용 증가 합성 사례는 생성 문장이 충실해도 검사기가 한쪽을 거절했다.
   합성6쌍에 미리 고정한 기준 주장을 직접 넣어도2/6만 양쪽 통과다. 원문별12검사 중7support/5uncertain이고
   거절5개는 모두 속성 감사의 host_projection이다. 적용할 조건이 없는 문장도 conditions=unclear로 출력했다.
3. 요금 하락이라는 조건을 일반적인 가격 하락으로 넓힌 생성 문장은 양쪽 검사에 통과했다.
   도서관 사례는 한쪽만 말한 조용한 학습 장소라는 이유를 공통 주장에 넣었다. 안전 검사 수를 늘려도 생성 충실성이 보장되지 않는다.
4. 취업 쌍은 take a job/stop working/willingness 차이와 원문 오타 문제가 남는다. 긴 물가 쌍도 money availability,
   printing money, money in circulation의 차이가 있어 사전부터 기준을 검토 후보로 표시했다.
   긴 물가 source의 선택 evidence에 다른 조건절까지 포함돼 qualification_guard가 막는 현상도 확인했다.
   이를 특정 사례 예외나 guard 제거로 맞추지 않았다.

기존 직접37개 저장 trace에서 NLI만 쓰면 정상20/20이지만 부정17개 중8개를 오승인한다.
전체 검사에서는 정상10/20·오승인2/17이다. 대표 주장 자격11개도 NLI-only 부정7/7오승인 대 전체4/7오승인이다.
따라서 **감사를 없애는 것**과 **감사를 신뢰할 수 있게 교체하는 것**은 다르다.

### 검증과 결과 파일

- private `runs/component-isolation-20261012/review.html`: 원문과 생성 조건별 결과, assistant 사후 의미 평가.
  `overview.html`: 전체 모델 trace. `assistant-review.json`: 27조건 결과를 report hash에 결합한 검토.
- 실행111.13초, 신규 LLM53/NLI51 checkpoint, 형식 수리0/transport 오류0. 전체 서비스 시간 아님.
  저장 evidence71회 결합 검사 일치. 중복 조건의 같은 evidence도 포함하므로 고유71개를 뜻하지 않는다.
- replay 새 LLM0/NLI0으로 전체 report 일치. Python386개·Node4개 통과. 자체 모델 서버 종료.
- plan SHA256 `94f79b8973765862a8944bbd0575a30f1fa666b68e3da5bc7afac51fd14cd8ce`,
  report SHA256 `81df611ac88fabb5e5c55b2b73a8a9a5f5e14cd9ce162f542464fdba203b9064`.
- assistant 사후 평가이지 독립 gold/사람 승인/미사용 표본 검증이 아니다. 기존 라벨·출력은 그대로 보존했다.
  새 agent0, ledger0, 전체64/1000재실행0. 자동 MVP 품질은 미완료다.

## 다음 구현 경계

다음 비교 대상은 자유로운 공통 문장 합성에 의존하지 않는 **원문 문장 후보 선택 baseline**이다.
원문 위치에 결합된 문장 후보를 검색하고, 지지도는 선택된 고정 주장에 대해 따로 측정한다.
이는 아직 구현·검증 전이며 전이적 유사도 묶음을 곧바로 agent로 승인하자는 뜻이 아니다.

판정기는 생성기와 분리해 고정 원문→target 정상/왜곡 대조군에서 비교한다. 새 감사 층을 덧붙이거나
unknown을 일괄 승인해 통과 수를 늘리지 않는다. 선택과 감사 각각의 보존·오승인 개선을 입증한 뒤 합쳐야 한다.
