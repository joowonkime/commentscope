# 수동 개입 없는 관점 에이전트 생성

서비스 실행 중 사람이 댓글을 분류·수정·승인하지 않습니다. 준비된 snapshot에서 자동으로 주장을 추출하고,
공통 주장에 대한 근거 검사를 통과한 묶음만 잠정 에이전트로 만듭니다. 개발·논문을 위한 사후 표본 평가는
이 실행 경로와 별개입니다. 자동 판정은 독립 품질 검증이나 사실 검증을 뜻하지 않습니다.

## 최신 직접 지지 판정 비교

필드 생성 대신 기존 로컬 NLI 모델로 같은34개 사례를 비교했습니다. 합성 정상7/7유지·오류8/9차단,
실제 정상5/7유지·오류는 단방향10/11, 양방향11/11차단입니다. 실제 정상 중 anchor self를 제외하면1/3유지입니다.
현재/미래 혼합과 정상 물가 주장2개 거절이 남아 사전 기준에 실패했습니다. 기본0.2와 실험 frame0.3 모두 변경하지 않았고
새 agent를 만들지 않았습니다. [판정 정책·수치·재현 명령](LOCAL_NLI_COMPARISON.md#최신-원문-span과-claim-비교),
ADR-020을 참고하세요. 전체 claim 동치를 공통 관점 탐색의 정답으로 채택하지 않습니다.

## 호환성 필드 실험 (2026-10-11, 기본 미채택)

실제 원문 범위·시점·조건 혼합을 줄이기 위해 `claim_frame.py`와 offline
`experiments/claim_frame_probe.py`를 추가했습니다. 비교 규칙은 코드에 있지만 분류값은 여전히 모델 예측입니다.
기본 실행은0.2를 유지합니다. 실패한 새 필터는 `build`에 `--experimental-frame-guard`를 명시한 경우에만0.3으로 실행됩니다.

고정 합성16사례는 공개 fixture `tests/fixtures/claim-frame-cases.json`이며,
기존 실제 개발18member는 이전 assistant 평가와 비교했습니다. 양성은 원문 충실성과 공통 주장 지지가 모두 supported인7개입니다.
합성 기대값은 첫 실행 전에 고정했고 두 번째 실행에서도 바꾸지 않았습니다. 기대값은 모델에 전달하지 않습니다.
실제 표본은 이미 확인한 개발 자료이며 assistant 판단은 독립 사람 gold가 아닙니다.

| 방식 | 합성 정상 유지 | 합성 오류 차단 | 실제 개발 정상 유지 | 실제 개발 오류 차단 |
| --- | --- | --- | --- | --- |
| 한 요청의 전체 필드 분류 | 3/7 | 8/9 | 5/7 | 11/11 |
|4개 작업으로 분해한 현재 실험 모듈 | 0/7 | 9/9 | 0/7 | 11/11 |

첫 방식은 should/will 혼합을 놓쳤고, 수동태 미래 예측·조건부 권고·가능성 재표현을 잘못 거절했습니다.
분해 방식에서는 단순 문장도 status=unclear/mixed로 분류해 전부 차단했습니다. 정상 보존0인 음성 차단100%는
의미 식별 성공이 아닙니다. 같은 anchor 거절이 여러 edge를 함께 막으므로 각 음성을 독립적으로 맞혔다고 해석하지 않습니다.
필드별 표현을 나눠 요청하는 것만으로 해결된다는 가설도 이번 결과에서 지지되지 않았습니다.

private 원시 결과(원본을 수정하지 않음):

- `runs/claim-frame-probe-20261011/report.json`: SHA256 `2c765dabda9af06a25d4583d49c46787a7ec15ed6b42e45d9c56584deaacee91`
- `runs/claim-frame-probe-20261011-v2/report.json`: SHA256 `510f8072b5c31e7cd2e275a7d7a2c88b3e2d77e5b10ad9e7de49910714fd9a65`

모델은 기존 Qwen3-4B-Instruct-2507 Q4_K_M/llama.cpp b11541/loopback8091, ngl99/ctx8192/parallel1입니다.
새 수집·유료 API·댓글 외부 전송 없이 기존 snapshot을 사용했습니다. 합성/실제34쌍은 필터 진단이며
새 cluster/agent 생성 실험이 아닙니다.0.3의64개/1,000개 통합 실행은 진행하지 않았습니다.
이후 기본 미채택/loader 보완은 진단의 모델 요청을 바꾸지 않으며 실제 실행 manifest의 code hash는 그대로 보존합니다.
기존 전체0.1 bundle8개,0.2 소표본 bundle0개는 현재 loader로 다시 확인했습니다.

재현 진단(README의 모델 서버 선행, 로컬 비공개 baseline/평가 파일 필요):

```bash
python experiments/claim_frame_probe.py data/ubi-research-20261010.json \
  runs/automatic-factory-20261011-full1000/report.json \
  artifacts/automatic-factory-20261011-assistant-evaluation.json \
  --run-dir runs/claim-frame-probe-new
```

필터는 원문/claim 각각4요청을 사용하며 같은 입력은 cache 재사용합니다. 조건 비교와 형식 재시도는 추가입니다.
edge 예산을 실제 모델 요청 수/비용으로 읽으면 안 됩니다. 기본 미채택으로 이 추가 호출은 기본 실행에 발생하지 않습니다.
다음은 프롬프트를 계속 늘리기보다, 실패한 필드 분류를 작은 대체 classifier와 같은 입력으로 비교할지 결정하는 단계입니다.
대체 모델 성능은 아직 측정하지 않았으며 어떤 모델도 해결책으로 승인하지 않았습니다. 정상 유지/오류 차단 둘 다 확인한 뒤
새 미사용 표본, 그 다음 통합 실행으로 진행합니다. 기존 한국어 답변 의미 변화와 source reason300자 경계 문제도 미해결입니다.

## 구현 경계

```text
DatasetSnapshot 최대 1000개
  → 중복 alias 제외, canonical source ID hash 순서의 고정 표본
  → 원문 구간 ID 선택과 독립 주장 추출
  → 다국어 embedding과 같은 표현 유형의 top-k 후보 검색
  → 자기 span만 보는 별도 원문 충실성 검사
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
0.2부터 parent 텍스트는 추출·검사 모델에 전달하지 않습니다. 독립 명제가 없는 동의/참조는
`context_dependent`로 보존하며 독립 주장 수를 늘리지 않습니다. 실제 endorsement 관계 추출은 아직 없습니다.

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
- 묶음마다 최대 9개 근거, 선택 구간 합계 최대 10,000자입니다. 자기 원문이 4,000자를 넘으면
  자르지 않고 `context_budget_exceeded`로 보존합니다. 0.1은 부모 길이도 검사했지만0.2는 부모를 전달하지 않습니다.
  같은 관점이 여러 묶음으로 갈라질 수 있습니다.
- 기본 의미 검사 예산은 2,000개 edge이며 형식 재시도는 별도입니다. 예산 초과·미검사·거절·애매한 항목은
  보류합니다. 0 agent도 유효한 실행 결과이지만 품질 성공으로 보고하지 않습니다.
- 0.2는 각 member를 공통 주장 없이 먼저 원문 검사합니다. 실패 시 common gate를 호출하지 않습니다.
  같은 member 검사는 cache를 재사용합니다. edge2,000건이 모델 요청2,000회라는 뜻은 아니며,
  source/common 각각의 요청 및 형식 재시도를 합산해야 비용을 알 수 있습니다.
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
자동 profile의 답변 생성에는 배정 구간만 전달합니다. 제목·claim label이 답변에 잘못된 내용을 심지 않도록 제외하고,
원문 감사와 claim 범위 감사를 두 요청으로 분리합니다. 둘 중 하나라도 실패하면 수정 또는 보류합니다.
전체 원문은 인용의 문맥 확인용으로 보존하며,
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

이 실행 당시 정한 다음 교체 순서: (1) 독립 주장과 parent 참조 동의 관계를 분리하고, parent를 보지 않는 원문 gate 및
생성 claim을 증거로 취급하지 않는 답변 감사 비교, (2) author/general scope·시점·조건 호환성 필드,
(3) 검색 recall·예산 배분·중복 agent 측정, (4) 미사용 표본 평가 후 상호작용 연결.
이 중 입력/감사 분리는 아래0.2 실험에서 구현했습니다. 나머지는 후속 실험이며,
매 서비스 실행에서 사람이 승인하는 방식으로 되돌리지 않습니다.

## 2026-10-11 원문 격리 회귀 결과

Factory0.2의 부모 입력 제거·별도 원문 검사는 `01cf6cf`, 답변 범위 감사의 독립 지침 보완은 `b46d09d`입니다.
실패했던0.1 report/agents는 그대로 보존하며 현재 loader에서도 동일한8개 profile로 읽힙니다.

| 검사 | 실제 결과 | 해석 |
| --- | --- | --- |
| 기존 배정 주장27개 원문 검사 | 15통과 / 12거절 | 동일 로컬 모델 판단이며 정답 수가 아님 |
| 이전 assistant 라벨18개와 대조 | 충실9/9유지, 오류7/8차단, 불명확1개는 통과 | unit 충실성만 비교; 공통 주장/전체 정확도 평가 아님 |
| 부모 내용 전이7개 | 7개 모두 거절 | 기존 실패 회귀 개선, 독립 평가 아님 |
| 기존27 source + 고정 hash 추가16 재추출 | 43 source → claims34 / uncertain9 → 주장91개 | 문맥 의존 label은0건; 모든 새 claim을 검수하지 않음 |
| 고정64 source 통합 실행 | 주장123개 / edge61건 / agent0개 / coverage0 | 예산 미소진; 품질 성공 아님 |
| 기존8 agent에 일반 설명 질문 | A002/A003/A004 공개, 나머지5개 보류 | 공개3개가 모두 정확하다는 뜻이 아님 |
| 근거 밖 한국 지급액/시행연도 질문 | 8개 모두 보류 | 이 질문에 한정된 회귀 |

짧은 동의3개는 재추출에서 모두 빈 claim이 됐습니다. 다른 전이 사례에서도 부모의 개인 경험 복사가 사라졌지만,
사용자명을 주제어로 오해한 새 주장, mode 오류, 선행 문맥이 빠진 span은 남습니다. 조건부 자동화 예시를
무조건적 주장으로 인정한 오류도 원문 gate에서 남았습니다. 원문 감사 이유26/27건이300자 출력 상한에 닿아
설명 문장이 잘리거나 깨졌으므로 그 자유 서술을 신뢰할 수 있는 근거로 쓰지 않습니다.

64개 실행은 동일 snapshot/고정 hash 선택이며 실행 코드는01cf6cf입니다. 원문 검사 대상은 중복을 제외한14개
claim, common gate 호출41건, 원문 거절 edge20건입니다. 실험을 같은 로컬 서버에 함께 실행했으므로 시간은
격리 성능 비교에 쓰지 않습니다. 전체1,000개0.2 재실행은 하지 않았습니다.

답변 감사 첫 수정은 scope 지침에 source 지침이 남아8개 모두 보류했습니다. 독립 지침으로 수정한 뒤 다시
8개 모두 실행했습니다. A002의 인플레이션 답변은 사후 읽기에서 원문과 부합했지만, A003의 생활 수준 과장·
소비 유도 해석 추가와 A004의 취직→직장 유지 변화는 감사에서 통과했습니다. 한국어 생성·scope 검증과
정상 답변 과잉 거절은 미해결입니다. 과거8개 bundle을 고정한 답변 회귀이지 새0.2 factory가8개를 만든 것은 아닙니다.

재현 명령(새 디렉터리 필요):

```bash
PYTHONPATH=src python experiments/source_isolation_probe.py data/ubi-research-20261010.json \
  runs/automatic-factory-20261011-full1000/report.json --run-dir runs/NEW-source-isolation-probe
```

기존 배정을 진단 대상으로 쓰는 offline probe이며 서비스 source 선택/승인 입력이 아닙니다. 모델 선언은 baseline의
metadata를 계승하므로 동일 로컬 모델/runtime에서만 비교합니다. 추가16개도 같은 개발 corpus라 미사용 gold가 아닙니다.
Python235개·Node4개 및 Windows/Linux CI는 통과했습니다. 새 브라우저 시각 검사는 하지 않았고 실제 모델 질의는 CLI로 수행했습니다.

비공개 산출물: `runs/source-isolation-probe-20261011/report.json`,
`runs/automatic-factory-20261011-sourceonly64/overview.html`,
`artifacts/source-isolation-runtime-20261011-v2.json`,
`artifacts/source-isolation-runtime-20261011-outside.json`,
`artifacts/source-isolation-evaluation-20261011.json`.
다음은 scope·시점·조건의 명시적 호환성, 한국어 실현 오류 평가, 그 후 검색 recall/예산/중복 분석입니다.
