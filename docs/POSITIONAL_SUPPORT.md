# 검색 이후 위치 기반 근거와 코드 판정

기존 raw-support의 공통 주장0개 결과를 보존하고, 검색 이후의 입력·판정 계약만 바꾸는 제한된 진단이다.
모델 가중치/NLI0.8/검색 registry는 유지한다. 모델이 선택한 근거의 의미 정확성까지 코드가 보장하는 것은 아니다.

## 변경 계약

- `positional_support-0.1`: 이미 검색된 두 원문을 L/R sentence-ID로 구분해 각각 한 연속 구간을 선택한다.
  선택 실패는 그 쌍의 보류이며 source registry에서 원문을 삭제하지 않는다. top4/topic 필수 단계는 없다.
- 선택된 두 literal 구간만 공통 주장 제안기에 전달한다. 전체 긴 댓글의 논점 합집합 대신 대응하는 최소 부분을 사용한다.
  구간 대응 자체는 모델 판단이다. 문장 분할은 언어적 완벽한 분석기가 아니며 전체 원문도 그대로 보관한다.
- 각 원문→고정 주장 검사에는 다른 댓글을 넣지 않는다. 전체 원문 NLI 통과 후 모델은 assertion/eligibility와
  scope/time/modality/conditions/polarity/presuppositions를 판단하고 S-ID 근거 범위를 선택한다.
  자유 인용 복사나 최종 supported verdict를 출력하지 않는다.
- host 결정: 명시적 absent/non_substantive/changed이면 not_supported, 불명확/맥락 의존/근거 없음이면 uncertain,
  전부 명확히 통과한 경우에만 보조 조건 검사와 **저장 근거 자체의 NLI**를 추가한다. full source와 evidence 모두 통과해야 support다.
- 의미상 서로 다른 필드는 형식 오류로 취급하지 않는다. 의미 거절을 재질문하지 않고, unknown/reversed ID 같은 구조 오류만 최대1회 수리한다.
- 근거는 원문 digest와 first/last/start/end/text로 결합한다. 코드가 원문을 복사하므로 임의 문자 추가가 없다.
  400자 인용 상한은 없으며 source4,000자/80segments, NLI512token 초과는 unchecked다. 원문을 잘라 통과시키지 않는다.
- 기존 guard는 유지한다. 단순히 guard 제거·임계값 완화로 통과 수를 늘리지 않는다. ledger/agent 기본 경로에 연결하지 않는다.

## 고정 평가와 제한

추론 전 코드와 plan을 고정한다. 기존 직접 지지37개·합성 공통 주장12쌍·실제 정상 source3쌍을 사용한다.
이전 개별 support12건의 assistant 검토 중 명확한11건(정상4/수정·비독립7)을 representative 회귀로 별도 평가한다.
모호한1건은 사전에 excluded_ambiguous에 명시하며 올바른 결과로 세지 않는다. 기존37개의 라벨은 변경하지 않는다.
새 eligibility 요구가 있어 fidelity-only 라벨과 대표 주장 자격은 다른 task라는 한계를 함께 보고한다.
이미 사용한 개발 자료이고 독립 gold/새 영상 검증이 아니다.

성공 기준은 고정 정상 보존·왜곡 오승인0·오류/미검사0과 실제3쌍의 통과 주장 원문 대조다.
실패를 보고 prompt/threshold를 조정하거나 전체64/1,000개로 확장하지 않는다. 최대LLM400회, agent0.
alignment/입력 구간/schema/prompt/판정 규칙/근거 NLI가 함께 바뀌므로 단일 요인의 효과로 보고하지 않는다.
추가 alignment 비용이 있어 사전에 속도 개선을 보장하지 않는다.

## 실행과 재현

기존 private `runs/raw-support-20261012/`의 고정 plan/report/assistant-review가 필요하다.
README의 Qwen localhost8091/GPU/context8192 설정과 기존 clustering 환경을 사용한다.

```bash
python -m experiments.positional_support_probe --run-dir runs/NEW-POSITIONAL --phase plan --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.positional_support_probe \
  --run-dir runs/NEW-POSITIONAL --phase run --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.positional_support_probe \
  --run-dir runs/NEW-POSITIONAL --phase verify --diagnostic-only
```

원문·source digest·모든 model request/result·NLI·plan/report/measurements/HTML은 Git 제외다.
snapshot 만료를 상속하고 replay는 새 모델 호출을 금지한다. 개발 회귀 시간을 전체 서비스 latency로 부르지 않는다.

## 실행 결과: 구조 개선, 의미 품질 악화 (2026-10-12)

추론 전 코드 `80776fb`를 고정했다. 같은 Qwen3-4B Q4_K_M GPU/DeBERTa CPU를 사용했고
실행 중 코드·라벨·threshold를 바꾸지 않았다. **진단 경로는 기본 채택하지 않는다.**

| 고정 평가 | 이전 raw-support | 이번 positional-support |
| --- | --- | --- |
| 직접37개: 정상 보존 | 15/20 | 10/20 |
| 직접37개: 부정 비승인 | 13/17 | 15/17 |
| 직접37개: 의미 오승인 | 1 | 2 |
| 직접37개: 계약 오류 | 4 (정상1/부정3) | 0 |
| 합성12쌍: 정상 보존 | 5/6 | 2/6 |
| 합성12쌍: 부정 비승인 | 4/6, 오류2 | 6/6, 오류0 |
| 알려진 실제 정상3쌍: 양쪽 모델 통과 | 0/3 | 0/3 |

추가 representative 회귀11개는 정상2/4·부정3/7비승인·오승인4·오류0이다.
이전 개별 support 사후 검토로 고른 개발군이며, 기존37개와 평가 목적이 달라 단일 정확도로 합치지 않는다.
부정 비승인 증가는 이전 오류 해소를 포함한다. 실제 오승인도 증가했으므로 품질 개선으로 해석하면 안 된다.

### 저장 trace에서 확인한 병목

- 직접 정상20개는 전체 원문 NLI를 모두 통과했다. 모델 속성값을 조합한 host 판정에서9개가 탈락하고
  저장 근거 NLI에서1개가 더 탈락했다. 시간/조건이 적용되지 않는 정상 재표현도 unclear로 출력됐다.
- 마지막1개는 앞 문장의 시장/다리 언급을 빼고 “그 주장을 믿지 않는다”만 근거로 골랐다.
  근거 검사가 잘못된 선택을 잡았지만 올바른 target을 보존하는 데에는 실패했다.
- 부정17개 중 전체 원문 NLI만으로는8개가 통과한다. 감사 제거만으로 정상 보존을 회복하는 것은 안전하지 않다.
  최종적으로도 AI 관련 영상→AI가 생성한 영상, 무언가 하기→생산적 활동이라는 의미 추가2개가 통과했다.
- 취업 의사 실제 쌍은 조건을 포함한 구간을 선택했지만 원문의 조건 표현 오타를 lexical guard가 인식하지 못했고,
  다른 원문 감사도 unclear였다. 특정 오타 예외를 추가하거나 guard를 제거해 결과를 맞추지 않았다.
- 물가 실제2쌍은 최소 공통 주장 대신 긴 다른 논점 구간을 골랐다. 제안도 과도한 복합 주장/일반 정의가 됐다.
  즉 위치 결합은 문자 보존을 보장하지만 **어느 구간을 골라야 하는지**와 **그 의미**는 해결하지 못했다.
- representative 회귀에서는 밈, 미해결 대상, 개인 의사→집단 필요성 등4건이 계속 승인됐다.

### 실측·검증·산출물

- 실행153.17초, 신규 LLM85/NLI79 checkpoint, 형식 수리0/transport 오류0. 평가 표본의 최종 오류·미검사0.
  GPU 서버 시작·수집·검색·agent 생성은 제외하므로 전체 서비스 latency나 이전 실행 대비 속도 개선 수치가 아니다.
- 저장 evidence46개와 aligned span26개 전부 원문 digest/ID/offset/text 재결합 일치.
  replay 결과 전체 report 일치, 신규 LLM0/NLI0. Python379개·Node4개 통과. 자체 모델 서버 종료.
- private `runs/positional-support-20261012/overview.html`이 원문/판정 화면,
  `assistant-review.json`이 report hash에 결합된 사후 검토다. plan/report/measurements/runtime 관측을 함께 보존했다.
  plan SHA256 `1169c0811c46ef60a68086a3556d35b9ba344deef89cb8225c6245af6f2428ef`,
  report SHA256 `41dbc1ec2bcb8a2865e067edc930d08362da694e7385ea0f9d187bcbc505cf37`.
- 실제64쌍/1,000개 확장0, ledger0, 새 agent0. 기존 기본 경로와 main은 그대로다. 자동 MVP 품질 완료가 아니다.

### 다음 경계

새 검사 층을 계속 추가하지 말고 현재 pipeline을 고정한다. 먼저 **구간 선택**과 **관계 감사**를 분리해서 비교한다.
구간 선택에는 고정 원문 쌍을, 관계 감사에는 고정 원문→target을 넣어 모델/설정별 정상 보존·왜곡 오승인을 측정한다.
직접 지지와 대표 주장 자격은 별도 평가한다. 이번 여러 동시 변경만으로 단일 원인이나 모델의 한계를 확정하지 않는다.
오타 사례별 패치·threshold 완화·전체 corpus 반복 대신 컴포넌트 교체의 근거를 만든 뒤 확장 여부를 결정한다.
