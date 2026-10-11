# 단계별 구현 계획

현재 상태: 공식 API 수집, 소표본 검수, 개발용 agent와 로컬 비교/질의 UI까지 구현했습니다.
아래 단계 표는 완료 순번이 아니라 전체 계획입니다. 3~5단계의 자동 품질 검증을 마쳤다고 보고하지 않습니다.
요구사항 Section16.4에 따라 검수 지원 입력으로 6~7단계의 개발 경로를 먼저 연결했습니다.
공개 GitHub 저장소는 `joowonkime/commentscope`이며 main을 공통 연구 프로토타입 기준선으로 관리합니다.
이번 단계의 구체적인 선택은 [구조 결정](ARCHITECTURE.md), 필드와 규칙은 [데이터 계약](DATA_CONTRACTS.md)에 기록합니다.

## 현재 상태 요약

- 구현/실행 확인: snapshot 검증·공식 API 1,000개 표본, 검수 묶음→개발 agent 2개, 독립 질문/감사/인용 비교 로컬 UI.
- 부분 구현/미승인: 자동 claim/cluster 형성·검수 도구. 실제 최신 입력은 assistant가 검수한 21개 중 11개를 두 agent에 연결.
- 미완료: 정식 관점 승격, 전체 corpus 자동 품질, agent 간 상호작용, Reflection, 브라우저 사용자 검증, 독립 논문 평가.
- 코드 회귀: Python210개/JS 최소 DOM3개. 모델 의미 정확도 점수가 아님.
- 완료율 하나로 표현하지 않습니다. 실행 가능한 사용자 경로와 연구 검증 여부를 [README](../README.md)의 표로 구분합니다.

## 진행 방식

2026-10-10 사용자 정정: 핵심은 **유의미한 주장을 가진 댓글 cluster를 충실히 대변하는 agent 생성**입니다.
Debate는 후속 활용이며, 서로 대립하는 입장·균형 잡힌 진영·흥미로운 토론을 만들기 위해 데이터를 맞추지 않습니다.
반대편이 없어도 의미 있는 cluster이며, 같은 결론의 서로 다른 이유/조건도 보존합니다.
여러 세부 주장이 하나의 충실한 공통 claim으로 표현 가능하면 불필요하게 분리하지 않습니다.

각 단계마다 범위를 정하고, 산출물을 만들고, 완료 조건을 확인한 뒤 변경 내용을 공유합니다.
내부 구현은 순서대로 진행하되, 자동 clustering 완성을 기다리느라 전체 사용자 경로를 막지 않습니다.
검수 지원 입력을 사용하는 개발 경로와 자동 pipeline의 원시 성능을 명확히 구분합니다.
각 단계는 하나의 작은 PR을 기본으로 하되, 검토하기 크면 더 작은 PR로 나눕니다.
실행해 확인한 결과와 아직 검증하지 못한 사항을 구분해 기록합니다.

## 제안 구조

Python 3.12+ 단일 프로젝트와 로컬 JSON 저장을 사용합니다. 근거와 적용 범위는 구조 결정 문서에 기록했습니다.
현재 로컬 모델은 Qwen3-4B-Instruct-2507 Q4_K_M/llama.cpp이며 UI는 Python HTTP 서버와 HTML/JS/CSS입니다.
모델 identity는 운영자 선언이고, 현재 선택이 품질 검증 완료나 향후 교체 금지를 뜻하지 않습니다.

```text
commentscope/
├── docs/                  요구사항, 설계 결정, 실험 방법
├── src/commentscope/      실행 코드
│   ├── contracts/         snapshot, claim, cluster, perspective 데이터 계약
│   ├── ingestion/         준비된 snapshot 로드, 검증, 정규화
│   ├── providers/         모델·embedding 호출 인터페이스
│   ├── factory/           추출, 후보 clustering, 검토, PerspectiveSpec 생성
│   └── agents/            독립 증거·상태, Auditor, web.py 및 비교 UI assets
├── experiments/           연구 비교/진단 실행기, 성공 품질 기본값과 구분
├── tests/fixtures/        합성 댓글과 오류 사례
├── data/                  실제 연구 corpus; Git 제외
├── artifacts/             실행 결과·감사 로그; Git 제외
└── runs/                  비공개 로컬 UI 세션·질문·감사 checkpoint; Git 제외
```

빈 구현 폴더를 미리 만들지 않고 필요한 단계에서 생성합니다.
데이터 흐름은 `DatasetSnapshot → ClaimUnit → CandidateCluster → ClusterReview → PerspectiveSpec`입니다.
각 단계가 원본 comment ID를 보존하며, agent와 UI는 이 결과를 소비합니다.

## 순서와 완료 조건

| 단계 | 산출물 | 다음 단계로 넘어가기 전 확인 |
| --- | --- | --- |
| 0. 저장소 | 독립 Git, 요구사항 기준본, 작업 계획, PR/Issue 템플릿 | 추적 파일과 제외 규칙 확인; GitHub 원격 연결 및 첫 push 확인 |
| 1. 구조·데이터 계약 | 엔터티 필드, 단계별 입출력, 오류 처리, 스택 결정 기록 | 다중 claim, reply 문맥, 중복, 다국어, rare/uncertain 사례를 계약으로 표현할 수 있음 |
| 2. 최소 실행 골격 | 패키지, CLI, snapshot 검증·정규화, 합성 fixture, 자동 검사 | 깨진 source ID·parent 관계 검출; 원문과 provenance 보존; 문서의 명령으로 재실행 가능 |
| 2.5. 공식 API 수집 | 개발자용 collect-youtube CLI, bounded 표집, reply 연결 | key·영상 준비 후 소량 live 수집; 실제 개수와 partial 상태 확인 |
| 3. Factory 기본 경로 | 모델 인터페이스, claim 추출, embedding, 후보 clustering, JSON 산출물 | 각 claim이 원문으로 추적됨; 상반된 stance의 혼합을 검사함; 모델 실패를 기록함 |
| 4. Cluster Review | accept/split/merge/rare/uncertain 처리, PerspectiveSpec 생성 | 서로 다른 원문 3개 이상의 지지와 coherence를 확인; claim 중복 배정 방지; 희귀 관점 보존 |
| 5. V0/V1/V2 검증 | 같은 corpus의 비교 실행, 표본 평가 양식, 2인 검토 결과 | coverage·coherence·separation·인용 지원·비용·지연을 비교; 실제 corpus 결과와 합성 테스트를 구분 |
| 6. 독립 Agent·Auditor | 독립 세션, 질문 라우팅, 답변 초안, 감사·수정·기권 | 다른 관점의 증거 사용 차단; 미승인 답변 노출 차단; 부족한 증거에서 기권 |
| 7. 사용자 흐름 | 최소 3개 연결 task, 비교·질문·원문 확인 UI | Factory 결과에 근거해 task 확정; 원문 복귀와 복구 가능한 오류 상태 검증 |
| 8. 연구용 배포 | 배포 URL, 실행 README, fallback, 평가 기록 | 준비된 표본으로 시연 재현; 실제 사용자 테스트 및 course deliverable 확인 |

M3의 Figma low-fi와 사용자 테스트는 별도 수업 산출물입니다. 모든 공학 단계를 마칠 때까지 이를 미루지 않습니다.
이 계획의 구현 순서가 M3/M4 제출 일정이나 최소 3개 연결 task 요건을 변경하지는 않습니다.

## 먼저 보존할 설계 제약

- 개발자가 공식 API로 준비한 DatasetSnapshot을 사용합니다. 공개 앱에서 임의 URL을 자동 수집하는 범위는 포함하지 않습니다.
- 합성 fixture로 구조를 검증할 수 있지만 실제 다국어 분석 성능의 근거로 사용하지 않습니다.
- V0는 원문 embedding, V1은 구조화된 claim 기반, V2는 V1에 Cluster Auditor를 추가합니다.
- Cluster Auditor의 필요성과 연구 기여는 V0/V1/V2 비교 후 판단합니다.
- agent 수를 고정하지 않습니다. 미검증 후보를 확정된 Perspective Agent로 내보내지 않습니다.
- 답변 Auditor는 cluster 품질 검토와 별개의 책임입니다.
- Reflection의 구체적 구현 범위는 pipeline 검증 후 결정합니다.

## 논문을 위한 검증 계획 (아직 수행 결과 아님)

1. 현재 UBI 표본은 개발용 한 영상입니다. 개발 과정에서 본 댓글을 독립 test set처럼 보고하지 않습니다.
2. 주제가 다른 추가 영상까지 포함하여 dataset/sampling/date/hash를 고정하고, raw corpus의 배포 가능 범위와 연구 사용 조건을 먼저 확인합니다.
3. 팀원 2명이 독립적으로 소규모 표본의 eligibility, claim/이유/조건, claim–source 충실성, 같은 관점으로 대표 가능한지 라벨링합니다. 의견 불일치와 adjudication을 남깁니다.
4. V0(raw embeddings), V1(structured claims), V2(V1 + reviewer)를 같은 데이터/평가 기준으로 비교합니다. 임계값은 개발셋에서 정하고 평가셋에 맞춰 조정하지 않습니다.
5. 클러스터 단계는 근거 충실성, 혼합 주장 비율, 과도한 분할/합병, meaningful-claim coverage, rare 보존, 비용/지연을 평가합니다. 단순 cluster 수와 silhouette만으로 '제대로 됨'을 주장하지 않습니다.
6. agent 단계는 자기 cluster 근거 범위 준수, 이유/조건 보존, 미지원 질문 기권, 원문 인용 정확성을 별도로 평가합니다. 단일 요약/단일 agent와 비교하되 실험 조건을 통제합니다.
7. debate 활용과 사용자 이해/관점 탐색 효과는 별도 연구 질문입니다. 설득력·대립 정도를 원문 대표성의 대체 지표로 삼지 않습니다.

현재 V0 탐색 결과는 실패 사례를 찾는 개발 증거이며, 논문의 정확도 수치·인간 평가·다국어 품질·새로움의 입증은 아닙니다.

## 미결정 사항의 처리 시점

| 항목 | 처리 시점 |
| --- | --- |
| GitHub 소유자·저장소·공개 범위 | 확정: `joowonkime/commentscope`, public |
| corpus 확보 방식과 사용 가능 범위 | 공식 API로 실제 1,000개 확보; downstream 연구/공개 사용 조건과 추가 영상은 별도 확인 |
| provider·모델·키 소유자·실행 예산 | 로컬 Qwen/llama.cpp 실행 확인; 유료/외부 추론·공유 배포는 별도 결정 |
| 다국어 품질 정책과 출력 언어 계약 | 데이터 계약과 추출 설계 단계 |
| 최종 사용자 task와 Reflection 범위 | Factory 검증 이후 |

## 1단계 Issue

[Issue #1](https://github.com/joowonkime/commentscope/issues/1)

제목: `Design snapshot-to-perspective contracts`

목표: DatasetSnapshot, Comment, ClaimUnit, CandidateCluster, ClusterReview, PerspectiveSpec의 필드와 불변조건을 설계합니다.

완료 조건:

- 필수·선택 필드와 ID 관계가 명확합니다.
- 하나의 댓글이 여러 claim을 갖는 예시가 있습니다.
- 원문과 번역, 원문 언어와 출력 언어를 구분합니다.
- 문맥용 reply와 관점을 지지하는 evidence를 구분합니다.
- rare/uncertain 및 누락된 reply 문맥을 표현합니다.
- reviewer의 split/merge 전후 source ID를 추적할 수 있습니다.
- 구현할 첫 테스트 목록이 있습니다.

이 Issue에서는 모델 호출이나 UI를 구현하지 않습니다.

## 2단계 Issue

[Issue #3](https://github.com/joowonkime/commentscope/issues/3): snapshot 검증·정규화 CLI와 S01–S12 자동 검사를 구현합니다.
1단계 PR #2는 main에 반영했습니다. 다음 단계는 현재 구현의 검토 후 별도 브랜치로 진행합니다.

## 공식 수집 경로

[Issue #5](https://github.com/joowonkime/commentscope/issues/5): 공식 API collector와 실행 안내.
2단계 PR #4 이후 공식 API 수집을 구현했고 실제 UBI 영상에서 1,000개 표본을 확보했습니다.
100/1,000개 실행과 한계는 YOUTUBE_COLLECTION.md에 기록했습니다. 전체 댓글을 확보했다는 뜻은 아닙니다.
사용자 선택으로 수집 경로를 구체화했으며, 요구사항 기준본 자체를 소급 변경하지 않았습니다.
