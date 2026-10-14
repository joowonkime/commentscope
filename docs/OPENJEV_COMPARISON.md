# 로컬 OpenJev 판정 비교

## 범위와 결정

TypeSafe 상용 Jev가 아니라 별도 공개 모델 **OpenJev2B v5**를 로컬로 비교합니다.
기본 Factory0.2, Qwen 추출, cluster/agent 생성은 변경하지 않았습니다. 댓글은 외부 API로 보내지 않습니다.
이는 판정 부품의 진단이며 자동 생성 MVP 완료나 논문용 독립 평가가 아닙니다.

모델은 `AlexWortega/openjev`의 `qwen3.5-2b-nli-v5`, revision
`a20448012c213128955ca0c693e7c943865cab77`로 고정했습니다.
[배포 모델 카드](https://huggingface.co/AlexWortega/openjev/tree/a20448012c213128955ca0c693e7c943865cab77)에
실제로 존재하는2B 파일을 사용합니다. 카드의4B 성능이나 상용 Jev 성능을 이번 모델의 성능으로 옮겨 쓰지 않습니다.
모델 카드에 일부 공개 benchmark의 test split도 학습에 사용했다고 명시돼 있어 그 benchmark 점수 역시 독립 검증으로 인용하지 않습니다.

## 직접 NLI 실행 결과

53개 모두 실제 로컬 추론했고 실행 오류0입니다. 정상 유지와 왜곡/제외의 비승인을 따로 집계합니다.
`unclear`도 비승인에 포함하므로 차단 수가 모두 확신 있는 반박을 뜻하지 않습니다.

| 과제 | DeBERTa 정상 유지 | OpenJev 정상 유지 | DeBERTa 왜곡/제외 비승인 | OpenJev 왜곡/제외 비승인 |
| --- | --- | --- | --- | --- |
| 충실성 기존 합성12 | 6/6 | 5/6 | 1/6 | 6/6 |
| 충실성 새 합성12 | 6/6 | 6/6 | 5/6 | 6/6 |
| 충실성 기존 실제13 | 8/8 | 8/8 | 3/5 | 3/5 |
| 직접 eligibility 개발8 | 0/4 | 2/4 | 4/4 | 3/4 |
| 직접 eligibility 전이8 | 0/4 | 3/4 | 4/4 | 3/4 |

OpenJev는 합성 왜곡 비승인을6/12→12/12로 개선했지만 정상 조건 동의어1개를 새로 과잉거절했습니다.
해당 entailment0.4963은 threshold0.8 바로 아래의 단순 경계 문제가 아닙니다.
실제 잘못 추가된 속성2개는 두 모델 모두 승인했습니다. OpenJev entailment0.9775/0.8937로 높았으며,
두 판정기를 합쳐도 이 공통 오승인은 없어지지 않습니다. 실제 원문은 private 화면에서만 볼 수 있습니다.

직접 eligibility는 정상0/8→5/8로 늘었지만, 대상이 없는 지시어 발언2개도 실질 주장으로 잘못 승인했습니다.
**주장 존재와 원문 함의는 다른 과제이며 판정기 교체만으로 해결되지 않았습니다. 기본 채택 조건은 실패입니다.**
선택형 원문 복사/최종 evidence 문맥 검사 같은 구조적 대책을 제거할 근거가 없습니다.

| CPU 운영 관측치 | DeBERTa | OpenJev2B |
| --- | --- | --- |
| 고유53요청 추론 시간 합 | 10.24초 | 68.45초 |
| 요청 p50 / p95 | 0.183 / 0.257초 | 0.889 / 1.655초 |
| 모델 로딩 | 1.44초 | 13.22초 |
| 프로세스 peak RSS | 1.53GiB | 10.33GiB |

아래 환경 차이·CPU reference 커널·swap 한계가 있습니다. GPU 최적화나 전체 파이프라인 wall time 비교가 아닙니다.
53개 결과는 새 추론0회로 checkpoint replay 일치를 확인했습니다.

## 별도 사전 분류 실행 결과

각 모델48요청/16댓글을 실제 실행했으며 오류0, 모델 재호출 없는 replay도 일치했습니다.
아래는 개발/전이를 합친 수치이고 원본 report에는 각각 보존합니다.

| 정책 | DeBERTa 정상 유지 | OpenJev 정상 유지 | DeBERTa 제외 비승인 | OpenJev 제외 비승인 |
| --- | --- | --- | --- | --- |
| 상대 argmax routing | 2/8 | 8/8 | 6/8 | 3/8 |
| 상대·절대0.8 strict | 0/8 | 2/8 | 8/8 | 8/8 |

OpenJev routing은 정상8개를 모두 남겼지만 단순 동의/미해결 지시어/질문 등 제외 대상5개도 substantive로 골랐습니다.
strict는 이를 승인하지 않았지만 정상6개를 잃었습니다. 이 조건에서 **자동 선별기 채택도 실패**입니다.
상대 점수와 절대 지지의 구별은 필요하지만 그것만으로 적정 선별 성능이 확보되지는 않았습니다.
찬반·이념·감정 등 댓글 경향 분류는 이번에 시험하지 않았고, 유형별3분류 정답도 별도로 검증하지 않았습니다.
이 표는 substantive 대 나머지의 이진 기대값 비교입니다. 옵션 순서/표현 변화에 대한 강건성도 미검증입니다.

결정은 기본 모델/서비스 경로 유지입니다. OpenJev는 교체 가능한 연구 comparator로만 남깁니다.
다음 구현 우선순위는 원문 topic quote의 위치 선택 계약, 최종 evidence의 자체 문맥 완결성,
알려진 cross-source 공통 주장에 대한 retrieval recall 확인입니다. 이들은 이번 OpenJev 실험의 완료 기능이 아닙니다.
이후 미사용 실제 표본에서 판정 부품을 다시 비교해야 하며, 이번 수치를 맞추기 위한 threshold/라벨 조정은 하지 않았습니다.

## 비교 계약

`local_openjev.py`는 생성 대신3분류 logits를 반환합니다. 고정 template는
`Premise: {premise}\nHypothesis: {hypothesis}`이고 label ID는 contradiction/entailment/neutral 순서입니다.
원문과 대상 문장만 입력하며 기대값/기존 판정/부모 댓글은 전달하지 않습니다.
원문·대상 각각500자, 합친512token 상한을 넘으면 자르지 않고 오류로 보류합니다.
threshold0.8은 두 모델에 동일하게 고정했지만 점수가 보정된 확률이거나 동일 보수성이라는 뜻은 아닙니다.

입력53개를 사전 고정했습니다.

| 과제 | 개발 | 전이/추가 | 의미 |
| --- | --- | --- | --- |
| 원문→대표 문장 충실성 | 기존 합성12 | 새 주제 합성12 | 각 정상6/왜곡6 |
| 실제 추출 문장 충실성 | 기존 검토13 | 없음 | 정상8/왜곡5 |
| 직접 NLI 실질 주장 여부 | 합성8 | 합성8 | 각 정상4/제외4 |

실제 기존20개 중 뉘앙스2·선택 문맥 부족4·독립성 문제만 있는1개는 **결과 보기 전에** fidelity에서 제외했습니다.
이 제외는 문제가 해결됐다는 뜻이 아닙니다. 실제13개는 과거 assistant 개발 평가이며 미사용 표본/독립 gold가 아닙니다.
전이 합성도 assistant가 작성했으므로 통계적 일반화나 다국어 품질을 주장하지 않습니다.

별도 typed routing은 같은 eligibility16개를3개 선택지로 분류합니다.
[공식 wrapper](https://huggingface.co/AlexWortega/openjev/blob/a20448012c213128955ca0c693e7c943865cab77/code/openjev_decide.py)의
`The answer to "{question}" is {label}: {criterion}` 형식을 사용합니다.
substantive/non_substantive/context_dependent 가설의 entailment를 상대 정규화하며 모델당48요청입니다.
이 실험은 DeBERTa 직접 NLI eligibility 실패를 확인한 뒤, **OpenJev 출력 전**에 별도 고정했습니다.
직접 NLI 결과를 덮어쓰거나 같은 실험으로 합치지 않습니다.

상대 점수1에 가까워도 모든 선택지의 절대 지지가 낮을 수 있습니다. strict 승인은 substantive가1위이고
상대 점수와 절대 entailment가 모두0.8 이상일 때만 기록합니다. 동점/실행 오류는 올바른 음성 판정으로 세지 않습니다.
어느 결과도 서비스에서 댓글을 삭제하거나 cluster 가입을 승인하지 않습니다.

## 실행 환경과 한계

원래 GPU 실행을 계획했지만 대용량 CUDA 의존성 다운로드를 OpenJev 추론 전에 중단했습니다.
기존 계획 `runs/openjev-comparison-20261012`와 DeBERTa 결과를 보존하고 별도 CPU 계획을 고정했습니다.
두 모델 CPU/float32/6threads/batch1로 실행하되 tokenizer와 transformers 버전은 다릅니다.
GPU 속도·VRAM이나 전체1,000개 처리시간을 이 결과로 주장하지 않습니다.

OpenJev 전용 venv는 기존 CPU torch2.14.1+cpu 환경을 `.pth`로 읽기 전용 재사용하고 새 transformers5.19.0,
huggingface-hub2.2.0, tokenizers0.23.3, httpx2 2.13.1을 자체 설치했습니다.
기존 환경의 빈 httpx2 패키지로 import가 실패해 새 환경에만 정상 패키지를 설치했습니다.
기존 DeBERTa/embedding 환경은 변경하지 않았습니다. 두 모델을 동시에 메모리에 올리지 않습니다.
CPU 메모리는 프로세스 peak RSS이며 라이브러리/로딩도 포함합니다. 추론 시간 합은 import/모델 로딩/파일 IO를 제외합니다.
CPU에서 causal-conv/linear-attention 최적화 커널 없이 PyTorch reference 경로를 사용했습니다.
실행 중 시스템 swap 사용도 관찰했으므로 GPU/최적화 서버 환경 성능으로 일반화할 수 없습니다.

## 설치와 합성 입력 시험

기존 clustering 환경과 **다른 venv**를 사용합니다. `.[clustering,openjev]`처럼 함께 설치하면
서로 다른 transformers 버전 요구가 충돌합니다. 기본 설치/CI에는 새 ML 의존성을 추가하지 않습니다.
다음은 Bash 예시이며 Windows에서는 해당 venv의 `Scripts/python.exe`와 PowerShell 환경변수 문법을 사용합니다.

```bash
python3 -m venv .venv-openjev
.venv-openjev/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-openjev/bin/python -m pip install -e '.[openjev]'
HF_HUB_DISABLE_TELEMETRY=1 .venv-openjev/bin/python -c "from huggingface_hub import snapshot_download; print(snapshot_download('AlexWortega/openjev', revision='a20448012c213128955ca0c693e7c943865cab77', allow_patterns=['qwen3.5-2b-nli-v5/config.json','qwen3.5-2b-nli-v5/model.safetensors','qwen3.5-2b-nli-v5/tokenizer*']))"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv-openjev/bin/python -c "from commentscope.providers.local_openjev import LocalOpenJev; m=LocalOpenJev(device='cpu'); print(m.metadata); print(m.score('White roofs might reduce indoor temperatures.', 'White roofs will reduce indoor temperatures.'))"
```

이 설치 예시는 CPU torch 최신 호환판을 선택합니다. 이번 실행의 정확한 버전은 위와 각 runtime manifest에 보존합니다.
새 환경의 버전이 다르면 동일 결과/성능 재현으로 보고하지 마세요. 모델 가중치는 약4.43GB이고 CPU float32 실행에는
추가 RAM이 필요합니다. 모델 파일 SHA256은 `9fd6a352fb00d6bdf848a84a1345f94244fc2d648408c01ee9d9109863e0c9d1`입니다.

## 연구 실행 재현

실제 댓글/평가/이전 실행은 Git에 없으므로 위 합성 입력 시험과 달리 아래 연구 재현은 승인된 로컬 자료가 필요합니다.
`experiments.openjev_probe.INPUTS`의6개 파일, 기록된 모델, 만료되지 않은 snapshot이 있어야 합니다.
CPU 계획 코드 commit은 `270fea0`, 그 이전 GPU 계획 코드는 `eab12f8`입니다.
아래 `python`은 단계별 환경을 뜻합니다. plan/report/verify는 기본 환경, deberta는 기존 clustering 환경,
openjev는 별도 OpenJev 환경에서 실행합니다. repo root에서 `PYTHONPATH=src`를 설정하거나 editable 설치합니다.

```bash
python -m experiments.openjev_probe --run-dir runs/openjev-comparison-new --phase plan --diagnostic-only
# 같은 명령의 phase를 deberta, openjev 순으로 실행한 뒤 report, verify로 재생성/검증합니다.
python -m experiments.openjev_typed_probe --base-plan runs/openjev-comparison-new/plan.json --run-dir runs/openjev-routing-new --phase plan --diagnostic-only
# typed도 같은 base-plan/run-dir로 deberta, openjev, report, verify 순서로 실행합니다.
```

추론 단계는 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`을 사용합니다.
plan은 입력/코드 hash, 모델 revision, threshold와 기대값을 고정합니다. raw checkpoint는 실제 입력/출력/logits/hash를 남깁니다.
report/verify는 새 모델 호출을 금지하고 저장된 score를 다시 계산합니다. 기존 run-dir는 덮어쓰지 않습니다.

이번 artifact 위치:

- `runs/openjev-comparison-20261012-cpu/`:53개 직접 비교와 `overview.html`.
- `runs/openjev-routing-20261012/`:16개 사전 분류 비교와 `overview.html`.
- `tests/fixtures/openjev-transfer-cases.json`:공개 가능한 새 합성 사례12개.

실제 원문/출력/가중치는 계속 Git 제외입니다. 사람 라벨은 연구 평가용이고 서비스 runtime 입력이 아닙니다.

검증 기록: Python317개/Node4개 통과. plan/결과 SHA256은 다음과 같습니다.

| artifact | SHA256 |
| --- | --- |
| CPU 직접 비교 plan | `0597bf429eb2f8491519cb6f042d03b29f18e3bb9fafb50bf1880cc6dc53cb31` |
| CPU 직접 비교 report | `a6c19e8d2e2b929732ad8f710f5b571025b3adcb1ace89a9ebb4c3f11935c4ff` |
| typed routing plan | `f203f76d5c1026d1ab53b9939d52168960a9c0c81547f687afb71e4e0d27c568` |
| typed routing report | `3230265198900aba9fa607c651b72743ea61c41178c1e7f305bc7a315cd2a71f` |
