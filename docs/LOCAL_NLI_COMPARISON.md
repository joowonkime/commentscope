# 로컬 관계 판정기 비교 — 개발용

목적은 모델 교체로 B의 오연결을 줄일 수 있는지 확인하는 것입니다. 원문, 전체 원문 대표 후보, 방향 있는72쌍,
greedy 배정 알고리즘과 최소3개 지지 기준은 고정합니다. Qwen의 원문 쌍 결과는 저장된 실행을 재사용하고,
공개 합성20사례는 두 모델 모두 새로 실행합니다. 모델 가중치만의 효과가 아니라 전체 판정 방식 비교입니다.

## 준비

저장소 루트에서 실행합니다. 기본 설치와 기존 README의 로컬 Qwen 서버, 8단계 실제 결과가 필요합니다.
실제 댓글/산출물/평가 계획은 공개 저장소에 없습니다. 공개 CI는 합성 테스트만 실행하고 모델을 받지 않습니다.

```bash
python -m pip install -e '.[clustering]'
HF_HUB_DISABLE_TELEMETRY=1 python -c "from huggingface_hub import snapshot_download; print(snapshot_download('MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli', revision='6f5cf0a2b59cabb106aca4c287eed12e357e90eb', allow_patterns=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','added_tokens.json','model.safetensors','README.md']))"
```

[모델 카드](https://huggingface.co/MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli)는 영어 NLI용으로 설명합니다.
이번 comparator는 CPU float32, 6 threads, safetensors, trust_remote_code=false, local_files_only=true입니다.
모델 파일 다운로드 이후에는 offline으로 추론하며 댓글을 외부 추론 API로 보내지 않습니다. Windows PowerShell에서는
inline 환경변수 문법 대신 `$env:HF_HUB_OFFLINE="1"` 등의 문법을 사용합니다.

## 실행 전에 평가 기준 고정

비교할 baseline JSON의 SHA256과 만료를 기록하고, 실제 원문을 읽어 기대 관계를 먼저 작성합니다.
`artifacts/YOUR-plan.json`의 최소 형식은 다음과 같습니다. SHA/만료/쌍 ID는 자신의 baseline에 맞게 바꿉니다.
예시 allowed는 판정 정답을 제공하는 것이 아니므로 실제 두 원문을 읽고 결정해야 합니다.

```json
{
  "baseline_sha256": "YOUR_BASELINE_FILE_SHA256",
  "expires_at": "COPY_FROM_BASELINE",
  "nli_model": "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
  "revision": "6f5cf0a2b59cabb106aca4c287eed12e357e90eb",
  "threshold": 0.8,
  "real_cases": [
    {"id": "M01->M02", "category": "review_before_run", "allowed": ["not_established", "unclear"]}
  ]
}
```

공개 합성 평가표는 `tests/fixtures/synthetic-support-cases.json`입니다. 정상 지원8, 부정8, 모순2, 애매2개이며
assistant가 작성한 개발용 기준입니다. 사용자 검수/독립 gold가 아닙니다. 실행 후 결과에 맞춰 정답을 고치지 않습니다.
기준 자체의 이견은 별도 검수 파일에 남기고 다음 버전에서 변경합니다.

```bash
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 python -m experiments.compare_local_nli data/YOUR-snapshot.json artifacts/YOUR-extraction.json artifacts/YOUR-candidates.json artifacts/YOUR-extractive-baseline.json artifacts/YOUR-plan.json --output artifacts/YOUR-nli-comparison.json
```

출력: 비교 JSON, `.json.html` 검수 화면, `.json.nli.json` 재배정 결과, `.json.manifest.json` 실행 전 hash,
쌍별 checkpoint입니다. 기존 경로는 덮어쓰지 않습니다. 자동 resume는 없고 새 출력 경로가 필요합니다.
Qwen 서버/model 설정은 baseline과 동일하게 운영자가 확인해야 하며 서버 모델 identity를 자동 인증하지 않습니다.

## 판정 계약

원문은 premise, 대표는 hypothesis 순서입니다. entailment→supports, neutral→not_established,
contradiction→contradicts로 변환하되, 최대 class softmax가0.8 미만이면 unclear입니다.
이 임계값은 실행 전에 고정한 실험 정책이지 보정된 신뢰도가 아닙니다. 결과를 보고 임계값을 튜닝하지 않았습니다.
원문500자/입력512tokens 초과는 거절하고 조건/부정을 조용히 잘라내지 않습니다.
오류는 relation=null로 저장하며 지원 edge로 사용할 수 없습니다. 승인/agent 생성은 항상0입니다.

## 2026-10-11 결과

| 확인 항목 | 기존 Qwen4B | 로컬 DeBERTa NLI |
| --- | --- | --- |
| 알려진 실제 부정12쌍: 지지하지 않음 | 8/12 | 12/12 (3개는 보류) |
| 조건/범위 주의2쌍: 지지하지 않음 | 0/2 | 1/2 |
| 합성 정상 연결 | 7/8 | 7/8 |
| 합성 부정: 기대 relation과 일치 | 7/8 | 6/8 |
| 합성 모순 / 애매 | 2/2 / 2/2 | 2/2 / 2/2 |
| 실제9개 배정 / 미배정 | 7 / 2 | 0 / 9 |
| 미승인3개 이상 묶음 | 2 | 0 |

NLI는 기존 필요성→도입 오연결3건을 막았습니다. 하지만 합성 사례에서 조건부 도입을 무조건 도입으로
바꾼 문장에 supports를 주었고, entailment softmax도0.987이었습니다. 높은 점수가 충실성 보장이 아닙니다.
두 모델 모두 `Most → Some` 지원을 놓쳤습니다. `Most → All`은 둘 다 contradicts로 판정했는데,
사전 기준은 문자 그대로 읽어 not_established였습니다. 일상어의 '대부분, 전부는 아님' 해석에 따른 기준 이견은
사용자 피드백 대상으로 남기며 실행 후 점수에서 임의 제외하지 않습니다.

실제72쌍 NLI 호출시간 합7.53초(CPU), 이전 Qwen16.77초(GPU). NLI 로딩0.91초 별도.
단일 소표본/서로 다른 실행 환경이므로 일반 속도 우위나 전체1,000개 처리시간으로 환산하지 않습니다.
NLI가 남긴 비동일 지원 edge는1개이며 조건/범위 검수가 필요합니다. 0묶음은 품질 성공도,
원래 의미 있는 묶음이 없다는 증거도 아닙니다. 전체 원문 대표 방식이 coverage를 제한하는지는 별도 가설입니다.

결정: 기본 판정기와 threshold를 변경하지 않습니다. 원문·조건 보존에 대한 사용자 검수 기준과 실제 긍정 pair를
확보한 뒤 다음 변경을 정합니다. 같은 표본에서 모델/프롬프트/임계값을 끝없이 바꾸지 않습니다.
미사용 실제 표본, 다국어, 장문/다중 주장, 사람이 승인한 관점과 agent는 아직 검증/구현되지 않았습니다.
