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
