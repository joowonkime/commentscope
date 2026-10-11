# 수동 개입 없는 관점 에이전트 생성

서비스 실행 중 사람이 댓글을 분류·수정·승인하지 않습니다. 준비된 snapshot에서 자동으로 주장을 추출하고,
공통 주장에 대한 근거 검사를 통과한 묶음만 잠정 에이전트로 만듭니다. 개발·논문을 위한 사후 표본 평가는
이 실행 경로와 별개입니다. 자동 판정은 독립 품질 검증이나 사실 검증을 뜻하지 않습니다.

## 구현 경계

```text
DatasetSnapshot 최대 1000개
  → 중복 alias 제외, canonical source ID hash 순서의 고정 표본
  → 원문 구간 ID 선택과 독립 주장 추출
  → 다국어 embedding과 같은 표현 유형의 top-k 후보 검색
  → 공통 주장에 대한 각 구성원의 직접 근거 검사
  → 서로 다른 원문 3개 이상이면 잠정 agent
  → 기존 독립 AgentSession과 로컬 비교 UI
```

`factory/automatic_contract.py`는 프롬프트·출력 스키마·구간 binding 규칙,
`factory/automatic.py`는 후보 검색·묶음 생성·checkpoint·profile adapter,
`factory/automatic_cli.py`는 실행과 결과 출력을 담당합니다.
기존 `source_facets.py`의 UBI 주제 whitelist와 검수 파일을 사용하지 않습니다.
기존 검수 기반 demo는 비교 기준으로 보존합니다.

모델은 댓글마다 최대 4개의 주장을 추출하고 코드가 선택한 구간을 원문 offset에 연결합니다.
필요성·예측·가능성·평가·서술·희망을 구분하지만 이 라벨만으로 묶지 않습니다.
부정·대상·시간·제한 조건은 주장에 보존해야 하며, 이유가 다르면 개별 근거에 귀속합니다.
구간 분리는 문장/줄 경계의 기계적 분할이지 의미 분석이 아닙니다. 한 구간에 여러 주장이 있으면
claim별 scope와 답변 검사가 추가로 필요합니다.

## 자동 묶음 정책과 실패 처리

- cosine 0.55 이상, 표현 유형이 같은 다른 원문의 상위 8개 주장을 후보로 검색합니다.
  이 수치는 미보정 baseline 설정이지 품질 통과 기준이 아닙니다.
- 후보가 많은 anchor부터 검사합니다. anchor 자신을 포함한 모든 member가 동일한 공통 주장을
  직접 지지해야 합니다. A→B, B→C만으로 A→C를 인정하는 연결요소 병합은 하지 않습니다.
- 검사 요청마다 `unit_faithful`, `core_supported`, `compatible`이 모두 `supported`여야 합니다.
  형식 오류는 최대 한 번 재시도하지만 의미 거절을 통과할 때까지 재질문하지 않습니다.
- 추출 문장이 schema의300자 상한에 정확히 닿으면 잘림 가능성으로 거절합니다. JSON의 `finish_reason=stop`이어도
  문장이 완결됐다는 보장은 없습니다. 한 번의 형식 재시도 후에도 실패하면 해당 원문 추출을 보류합니다.
- 서로 다른 canonical 원문 3개 이상일 때만 `auto_accepted_unvalidated`입니다.
  한 claim은 최대 하나의 묶음에 배정합니다. 댓글의 서로 다른 claim은 서로 다른 묶음에 갈 수 있습니다.
  source 수는 작성자 수·독립된 사람 수가 아닙니다.
- 묶음마다 최대 9개 근거, 선택 구간 합계 최대 10,000자입니다. 원문 또는 부모 문맥이 4,000자를 넘으면
  자르지 않고 `context_budget_exceeded`로 보존합니다. 같은 관점이 여러 묶음으로 갈라질 수 있습니다.
- 기본 의미 검사 예산은 2,000개 edge이며 형식 재시도는 별도입니다. 예산 초과·미검사·거절·애매한 항목은
  보류합니다. 0 agent도 유효한 실행 결과이지만 품질 성공으로 보고하지 않습니다.
- 이웃이 부족한 항목은 `insufficient_neighbors_unverified`입니다. 검색 실패일 수 있으므로
  검증된 소수 관점이라고 단정하지 않습니다. full snapshot과 source별 disposition을 보존합니다.

이 구조는 제한된 후보에 대한 greedy support-star baseline입니다. 순서 민감도, top-k의 누락,
표현 유형 오분류, 의미적으로 비슷한 agent 중복, 같은 모델의 추출·검사 오류가 남습니다.
공통 주장에 대한 직접 지지를 요구하지만 모든 구성원이 모든 이유·조건을 공유한다고 주장하지 않습니다.

## 실행

README의 로컬 모델 설치/서버 실행 절차와 clustering extra 설치가 먼저 필요합니다.
모델 요청은 `127.0.0.1:8091`에만 보냅니다. 이미 받은 embedding으로 외부 연결 없이 실행하려면
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`을 환경변수로 설정합니다.
아래 모델 이름·revision·runtime은 실제 실행값을 기록해야 하며 서버 identity의 암호학적 검증은 아닙니다.

```bash
python -m commentscope.factory.automatic_cli build data/ubi-research-20261010.json \
  --run-dir runs/automatic-first --limit 64 --max-gate-calls 250 \
  --model-label Qwen3-4B-Instruct-2507-Q4_K_M \
  --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 \
  --runtime llama.cpp-b11541-cuda12.8-ngl24-ctx8192
```

전체 snapshot 처리는 새 `--run-dir`에서 `--limit 1000 --max-gate-calls 2000`으로 실행합니다.
PowerShell에서는 줄 끝 `\` 대신 한 줄 명령으로 실행하거나 PowerShell의 줄 연결 문법을 사용하세요.
추가 YouTube 수집이나 유료 API 호출은 하지 않습니다.

산출물은 `manifest.json`, immutable `call-*.json`, `embeddings.json`, `report.json`, `agents.json`,
`overview.html`입니다. HTML을 브라우저로 열면 각 agent의 공통 주장·개별 주장·배정 구간·전체 문맥과
미배정 항목을 볼 수 있습니다. 모든 파일은 원문/모델 출력이 포함된 비공개 연구 자료입니다.

완료 전 중단된 실행은 **동일 명령과 동일 디렉터리**로 재개할 수 있습니다. 입력·설정·모델 선언·코드가
바뀌면 새 디렉터리가 필요합니다. 완료 결과는 덮어쓰지 않습니다. 실패 응답도 재현을 위해 보존하므로
모델 장애 후 재측정하려면 새 실행을 만듭니다. 실행 중 snapshot 만료도 검사합니다.

생성된 결과에 직접 질문하려면:

```bash
python -m commentscope.factory.automatic_cli ask data/ubi-research-20261010.json \
  runs/automatic-first/report.json runs/automatic-first/agents.json \
  --question "이 관점의 핵심 주장과 조건을 근거에 맞게 설명해주세요." \
  --output artifacts/automatic-first-answer.json \
  --model-label Qwen3-4B-Instruct-2507-Q4_K_M \
  --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 \
  --runtime llama.cpp-b11541-cuda12.8-ngl24-ctx8192
```

기존 웹 UI에서도 검수 입력 없이 사용할 수 있습니다. `--automatic`일 때 두 번째 인자는 검수 파일이 아니라
factory의 `report.json`입니다. `--allow-unapproved`로 검수 경계를 우회하는 방식이 아닙니다.

```bash
python -m commentscope.agents.web data/ubi-research-20261010.json \
  runs/automatic-first/report.json runs/automatic-first/agents.json --automatic \
  --model-label Qwen3-4B-Instruct-2507-Q4_K_M \
  --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 \
  --runtime llama.cpp-b11541-cuda12.8-ngl24-ctx8192
```

`http://127.0.0.1:8765`에서 자동 생성 여부와 처리 범위를 확인합니다. agent가 0개이면 질문을 비활성화합니다.
자동 profile은 배정 구간과 claim scope만 모델에 전달합니다. 전체 원문은 인용의 문맥 확인용으로 보존하며,
부모 댓글이나 같은 댓글의 미배정 주장을 agent의 추가 지지 근거로 승격하지 않습니다.

## 품질 평가와 완료 조건

서비스의 무인 실행 여부와 모델의 의미 품질을 분리해 평가합니다.

| 측정 | 의미 |
| --- | --- |
| extraction status 전체 분포 | 실패/불명확/비주장/길이 제한이 얼마나 발생하는가 |
| covered unique sources / selected와canonical | 전체를 버리는 정책이 성공처럼 보이지 않는가 |
| 표본 claim 충실도 | 대상·부정·조건·시간·표현 강도를 보존하는가 |
| accepted 묶음 공통 주장 지지 | 모든 구성원에게 성립하지 않는 주장을 대변하지 않는가 |
| 보류 표본과 가까운 다른 묶음 | 유효한 관점 누락·과도한 분할·중복 agent가 있는가 |
| 추론 시간·요청 수·메모리·중단 복구 | 로컬 실행 비용과 운영 제약이 무엇인가 |

고정 개발 표본에서 문제를 분석한 뒤, 아직 조정에 쓰지 않은 평가 표본과 통과 기준을 먼저 고정해야 합니다.
assistant 평가와 모델 자체 판정은 독립 gold가 아닙니다. 논문에서는 감당 가능한 층화 표본을 별도 평가자가
검토해야 합니다. 사람의 평가는 학습/개발/연구 단계이지 매 영상의 서비스 승인 절차가 아닙니다.
현재 release 품질 기준은 미확정이며, 자동 실행 성공만으로 생성 MVP 품질 완료를 선언하지 않습니다.
