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

## 2026-10-11 실제 전체 snapshot 실행: 기능 연결, 품질 실패

`runs/automatic-factory-20261011-full1000/`에서 수동 검수 입력 없이 끝까지 실행했습니다.
코드 기준은 `4287773`, 모델은 위 Qwen4B Q4_K_M이며 GPU offload는 `ngl99`입니다.
최종 결과는 이후 현재 loader의 source binding/replay 검사도 통과했습니다. 원본 출력은 변경하지 않았습니다.

| 항목 | 관측 결과 |
| --- | --- |
| 입력/선택 | 1,000개 / 중복1개 제외999개 |
| 추출 상태 | claims719 / uncertain279 / extraction_failed1 |
| 주장 후보 | 1,829개 |
| 자동 agent | 8개, 원문27개 반영: 선택 표본의2.7% |
| 미배정 주장 | 1,802개: 후보 부족830 / 묶음 미통과616 / 예산 소진 미검사356 |
| 의미 검사 | 2,000건, 예산 소진 |
| 관측 실행 간격 | manifest 생성→report 생성 약95분 |
| 추출 모델 요청 | 형식 재시도74회 포함1,073회; 요청 시간 합계약28분 |
| 묶음 검사 시간 | 기록된 요청 시간 합계약55분; 형식 재시도0 |

시간은 이 기기의 단일 실행 관측값입니다. 파일 I/O·embedding·서버 대기 등이 있어 요청 합계와 전체 간격은
다르며, 실행 도중 별도 작은 UI 검증도 수행했으므로 격리된 벤치마크가 아닙니다. ngl24 smoke와의 속도 우열을
통제 비교한 것이 아닙니다. 추출 실패1개는 문장이300자 상한에 다시 닿아 차단된 경우입니다.

묶음 출력 전 고정한 hash-order 표본 계획으로5개 묶음의18개 member, 미배정10개, zero-claim5개를
대화 assistant가 사후 점검했습니다. 모든 member의 원문 충실성·공통 주장 지지가 성립한 묶음은1/5이며,
두 조건을 모두 만족한 member는7/18입니다. **독립 gold나 전체 정확도 추정이 아닌 해당 표본의 평가 기록입니다.**
원본 묶음 배정은 수정하지 않았습니다. 이미 개발에 사용된 영상이라 미사용 데이터 평가도 아닙니다.

주요 실패는 부모의 상세 주장을 짧은 동의 답글의 독립 주장으로 승격한 것, 개인/일반 범위 혼합,
조건부 미래를 현재 사실로 연결한 것입니다. 같은 모델의 gate가 이 오류들을 통과시켰습니다.
상위8개 검색·표현 유형·순서·2,000건 예산이 coverage를 제한하므로 단순히 threshold를 낮춰 해결하지 않습니다.

실제 Chromium에서8개 agent에2개 질문을 보내 인용 펼치기·JSON/HTML 다운로드·모바일 overflow·새 탭 분리·
초기화를 검사했습니다. 질문1에는8개 모두 모델 감사 통과 답변을 냈지만, 오염된 claim 재사용과 한국어 오역,
배정 주장 범위를 넘는 상세 내용이 사후 검토에서 발견됐습니다. 질문2의 근거 없는 한국 지급액/시행연도 확정
요구에는8개 모두 `not_in_evidence`로 보류했습니다. **브라우저 기능 통과와 인용 ID 일치는 의미 정확도가 아닙니다.**

비공개 결과 위치:

- `artifacts/automatic-factory-20261011-summary.html`: 사용자가 먼저 볼 집계·실패·결과 링크.
- `runs/automatic-factory-20261011-full1000/overview-ko.html`: 원문과 미배정 목록. 원래 `overview.html`도 보존.
- `artifacts/automatic-factory-20261011-assistant-evaluation.json`: 고정 표본별 평가 및 추가 답변 점검.
- `artifacts/automatic-factory-20261011-full1000-browser.comparison.html`: 실제 질문/답변/인용.
- `artifacts/automatic-factory-20261011-full1000-browser.checks.json`: Chromium 기능 기록.

Python231개와 Node DOM계약4개, Windows/Linux CI는 통과했습니다. 실제 모델 품질은 실패했으므로
PR #21은 연구용 draft로 유지하고 main의 검증된 기본 경로로 승격하지 않습니다. 서버는 검증 후 종료합니다.

다음 교체 순서: (1) 독립 주장과 parent 참조 동의 관계를 분리하고, parent를 보지 않는 원문 gate 및
생성 claim을 증거로 취급하지 않는 답변 감사 비교, (2) author/general scope·시점·조건 호환성 필드,
(3) 검색 recall·예산 배분·중복 agent 측정, (4) 미사용 표본 평가 후 상호작용 연결.
이는 아직 구현·검증하지 않은 후속 실험입니다. 매 서비스 실행에서 사람이 승인하는 방식으로 되돌리지 않습니다.
