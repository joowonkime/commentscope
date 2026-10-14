# 원문 선택과 로컬 모델 계약 검증

댓글의 의미를 새로 작성하는 추출 단계를 **원문 위치 선택 → 코드 복사**로 분리했습니다.
원문 글자 보존은 검사할 수 있지만, 선택의 독립성이나 공통 주장의 정확성까지 보증하지는 않습니다.
실제 Qwen4B 비교에서 출력 계약 누락의 영향은 확인했고, 의미 판정 실패도 남았습니다.
기본 Factory0.2와 main은 변경하지 않으며 이 경로는 진단 전용입니다.

## 원인과 수정 범위

| 문제 | 변경 | 보장하지 않는 것 |
| --- | --- | --- |
| 모델이 claim을 재작성하며 원문에 없는 뜻 추가 | 모델은 sentence-ID 범위만 선택, host가 원문 복사·offset·digest 검증 | 원문 일부만 고른 데 따른 의미 손실 |
| 자기 댓글의 필요한 앞 문장을 버림 | 짧은 자기 댓글 전체, 긴 댓글은 focus/topic과 인접 문장 보존 | 긴 댓글의 모든 지시 대상 완결성 |
| 문자적 지지를 실질 주장과 혼동 | 별도 eligibility 검사, 내용 없는 영어 지시어 공식은 코드 차단 | 구체 명사와 미해결 지시어가 함께 있는 문장 |
| JSON 형식은 강제하지만 모델이 출력 계약을 읽지 못함 | 선택·eligibility 단계에 한해 schema를 system에도 노출 | schema를 읽는 것만으로 올바른 의미 판단 |
| 동일한 이웃 수로 seed 우선순위가 무의미해짐 | 서로 다른 두 이웃 source의 유사도로 순서 비교 | 유사도가 높다는 이유만으로 cluster 승인 |

llama.cpp는 `response_format`의 schema로 출력을 제한하지만, schema를 모델의 prompt에 자동 삽입하지 않습니다.
따라서 계약을 모델에게도 설명해야 합니다. [공식 llama.cpp 문서](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md).
기존 모든 실패의 원인이 이것이라고 주장하지 않습니다. 아래 비교는 새 선택형 추출의 두 단계만 바꿉니다.

`SchemaVisibleCalls`는 **cache 앞에서** 실제 system 메시지를 구성합니다. 이전 보이지 않는 prompt와
새 prompt는 서로 다른 request hash를 가지며, raw 요청에 실제 모델 입력이 남습니다. 기존 transport 기본값,
NLI0.8, 의미 감사, 합성 기대값, 표본 선택, 모델·decoding 설정은 그대로입니다.

## 고정 표본 비교 결과

모델은 Qwen3-4B-Instruct-2507 Q4_K_M, temperature0/seed407입니다. 합성16개는 추론 전에 고정했습니다.
확인용 실제12개 source ID도 구현 전에 고정했지만, 과거 full1000에는 포함됐고 schema 보완 전에 첫 실패를 봤습니다.
독립 gold나 미사용 corpus의 정확도 평가가 아닙니다.

| 검사 | schema 비공개 | 선택·eligibility schema 공개 |
| --- | --- | --- |
| 개발 정상 주장 보존 | 1/4 | 3/4 |
| 개발 제외 사례 차단 | 4/4 | 4/4 |
| 전이 정상 주장 보존 | 0/4 | 4/4 |
| 전이 제외 사례 차단 | 4/4 | 3/4 |
| 기존 실제12개 추출 | 1unit / 1source | 13units / 6sources |
| 확인 실제12개 추출 | 2units / 2sources | 12units / 8sources |

정상 보존1/8→7/8은 동일 입력에서 schema 노출의 영향을 보여줍니다. 그러나 제외 차단8/8→7/8로 악화됐습니다.
주거 보조금 경험은 여전히 누락하며, 무엇이 입증됐는지 없는 문장은 오승인합니다. 추출 개수는 정확도가 아닙니다.

확인 표본에서 생성된12개를 전부 사후 검토했습니다. 원문에 묶인 실질 주장8개, 미해결 지시 대상2개,
최종 evidence의 필요 문맥 누락1개, 수사 의문문 정책 모호성1개입니다. 작성자의 주장이 사실이라는 판정은 아닙니다.
사후 assistant 평가는 runtime 입력·수동 배정·독립 gold로 사용하지 않습니다.

## 문맥만 바꾼 비교

기존 생성 claim20개를 고정하고, 기존 선택 span 대신 전체 자기 댓글을 같은 검사기에 주었습니다.
500자 안에 들어오는16개만 비교했으며 모델 통과는9→13개입니다. 복지 경험의 필요한 문맥은 일부 복구됐습니다.
반면 연구 실패에 대한 미해결 `otherwise`를 잘못 연결한 문장도 새로 통과했습니다.
AI video에 generated 의미를 추가한 기존 오류도 남았습니다. 따라서9→13은 품질 향상 점수가 아닙니다.

## 기능 조립 검증

기존64개와 자동 밀집32개를 새 선택형 추출로 처리합니다. 같은 units/candidates에서 degree와 source_density를
비교하며 최소3개 distinct source, 고정 core 직접 지지, seed_limit2, 결정 예산64를 유지합니다.
밀집32개는 과거 생성 claim의 검색 기하로 선택한 비대표 표본입니다. 과거 오염된 claim이 표본 선택에도 영향을
줄 수 있으므로 이 표본을 recall 개선 증거로 쓰지 않습니다. 과거 claim/labels는 새 추출의 입력이 아닙니다.

| 결과 | 기존64개 | 자동 밀집32개 |
| --- | --- | --- |
| 원문 선택 units / 해당 source | 59 / 35 | 22 / 16 |
| 후보 이웃 보유 units | 10 | 6 |
| 3source 가능한 anchor | 1 | 2 |
| degree / source_density 결정 수 | 2 / 2 | 4 / 4 |
| 새 agent | 0 / 0 | 0 / 0 |
| 예산 소진 | 아니오 | 아니오 |

이번 표본에서는 순서 변경의 개선 효과가 입증되지 않았습니다. 실제 새 profile이 없으므로 새 agent 질의도 실행하지 않았습니다.
주제 인용을 자유 텍스트로 복사하다 원문과 달라져 eligibility 계약에서64개 표본24건,32개 표본3건이 차단됐습니다.
자동 수정하거나 의미 판정을 통과로 바꾸지 않았습니다. 공통 후보는 NLI/조건·관계 감사에서도 실패했습니다.
기존 재작성 claim 실험과는 추출 개수와 검색 문자열이 달라 recall 수치를 직접 비교할 수 없습니다.

후속 구현은 주제 근거도 위치 선택으로 바꾸고, 최종 evidence에서 지시 대상 완결성을 검사한 뒤,
알려진 cross-source 공통 주장에 대한 검색 회수율을 측정해야 합니다. 이들은 아직 구현 완료가 아닙니다.

## 코드와 재현

- `factory/evidence_units.py`: 원문 범위 선택, 별도 eligibility, own-comment context, 재결합 검증.
- `providers/schema_visible.py`: 특정 단계만 schema 노출, cache identity 분리.
- `factory/evidence_core.py`: 원문 표현 우선 공통 명제, 각 원문→core 직접 지지. 필요할 때만 생성 제안1개.
- `factory/core_groups.py`: 조립 순서 비교, 3source·예산·직접 가입 불변조건.
- `experiments/evidence_units_probe.py`: 고정 표본·문맥 ablation·기능 조립·모델 미호출 replay.

실제 corpus·raw 결과·사후 평가·HTML은 Git 제외입니다. 최초 비공개 schema 실행은 코드 `d081e0f`,
schema 공개 실행은 `1b1dfd9`입니다. 다른 버전으로 기존 manifest를 덮어쓰지 않습니다.

한눈에 보는 private 결과는 `artifacts/evidence-units-overview-20261012.html`, 사후 평가는
`artifacts/evidence-units-evaluation-20261012.json`입니다. 두 probe 및64/32개 조립은 모델 재호출0으로 exact replay했습니다.

| 원시 결과 | SHA256 |
| --- | --- |
| 최초 probe | `5b044f3524a828fea733112b296e4325a7590bacc6b3edf217e75c6dee818849` |
| schema 공개 probe | `e880b51f49dc5acfc85003a58460c189793b7d3adbd2c2c0c517f48a3e3e4412` |
| schema 공개 baseline64 | `0eea670016c927be085bff9b66596d860a7a721f35c83725a0507c238b759508` |
| schema 공개 dense32 | `2d512774886c04895a9c145111b5d8b5074c302d59b7b1e0c7802c52a6e17df9` |

로컬 모델 서버와 pinned clustering/NLI 환경을 준비한 뒤 저장소 루트에서 실행합니다.
상세 설치·서버 실행은 [기존 로컬 모델 안내](../README.md)를 따릅니다. 아래는 원본 연구 데이터가 있는 개발 환경의 경로입니다.

```bash
PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -m experiments.evidence_units_probe \
  data/ubi-research-20261010.json \
  runs/automatic-factory-20261011-sourceonly64/report.json \
  runs/automatic-factory-20261011-full1000/report.json \
  runs/grounded-core-new-sample-20261012/report.json \
  --run-dir runs/evidence-units-20261012-visible \
  --phase verify --diagnostic-only --schema-visible
```

`verify`는 저장된 출력과 hash를 재계산하고 모델 호출을 금지합니다. 새 실행은 **새 run directory**에서
`--phase probe` → `--phase baseline64` → `--phase dense32` 순서입니다. 독립 clone에는 연구 데이터가 없으므로
위 경로가 바로 동작하지 않습니다. 코드 계약 검사는 합성 데이터만으로 `python -m unittest discover -s tests -q`로 실행합니다.

문자 변조 property test100개와 schema cache 분리 등을 포함해 Python301개, Node4개가 로컬 통과했습니다.
이는 코드 계약 검사이며 모델의 의미 정확도301개 통과라는 뜻이 아닙니다.

## 남은 승인 조건

1. 전체 댓글에서 판정한 eligibility가 **실제 저장·전달되는 evidence**에서도 성립해야 합니다.
2. 미해결 지시 대상과 수사 의문문 정책을 일반적으로 다뤄야 합니다. 특정 실패 단어만 차단하지 않습니다.
3. 실제3개 이상의 원문이 지지하는 core와 그 agent의 답변을 검증해야 합니다.
4. 개발 표본과 분리한 실제 평가·비교 기준·사용자 연구 전에는 품질 완료나 논문 결과로 승격하지 않습니다.
