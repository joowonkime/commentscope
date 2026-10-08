# 단계별 구현 계획

상태: 0단계 완료, 1단계 구조·데이터 계약 설계 검토. 공개 GitHub 저장소는 `joowonkime/commentscope`입니다.
이번 단계의 구체적인 선택은 [구조 결정](ARCHITECTURE.md), 필드와 규칙은 [데이터 계약](DATA_CONTRACTS.md)에 기록합니다.

## 진행 방식

각 단계마다 범위를 정하고, 산출물을 만들고, 완료 조건을 확인한 뒤 변경 내용을 공유합니다.
이번 작업은 1단계 설계까지 진행합니다. 이후 단계는 사용자와 앞 단계 결과를 확인하면서 순서대로 진행합니다.
각 단계는 하나의 작은 PR을 기본으로 하되, 검토하기 크면 더 작은 PR로 나눕니다.
실행해 확인한 결과와 아직 검증하지 못한 사항을 구분해 기록합니다.

## 제안 구조

첫 구현은 Python 기반 단일 프로젝트와 로컬 JSON 저장을 제안합니다.
Python 3.12+와 JSON을 첫 구현의 기본값으로 선택했습니다. 근거와 적용 범위는 구조 결정 문서에 기록했습니다.
모델 provider, 모델명, embedding 모델, API 서버 및 UI 프레임워크는 해당 단계에서 결정합니다.

```text
commentscope/
├── docs/                  요구사항, 설계 결정, 실험 방법
├── src/commentscope/      2단계부터 생성
│   ├── contracts/         snapshot, claim, cluster, perspective 데이터 계약
│   ├── ingestion/         준비된 snapshot 로드, 검증, 정규화
│   ├── providers/         모델·embedding 호출 인터페이스
│   ├── factory/           추출, 후보 clustering, 검토, PerspectiveSpec 생성
│   ├── agents/            독립 증거·대화 상태, 답변 Auditor
│   └── api/               검증된 기능을 노출하는 API
├── tests/fixtures/        합성 댓글과 오류 사례
├── data/                  실제 연구 corpus; Git 제외
├── artifacts/             실행 결과·감사 로그; Git 제외
└── web/                   사용자 task 확정 후 UI 구현
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
| 3. Factory 기본 경로 | 모델 인터페이스, claim 추출, embedding, 후보 clustering, JSON 산출물 | 각 claim이 원문으로 추적됨; 상반된 stance의 혼합을 검사함; 모델 실패를 기록함 |
| 4. Cluster Review | accept/split/merge/rare/uncertain 처리, PerspectiveSpec 생성 | 서로 다른 원문 3개 이상의 지지와 coherence를 확인; claim 중복 배정 방지; 희귀 관점 보존 |
| 5. V0/V1/V2 검증 | 같은 corpus의 비교 실행, 표본 평가 양식, 2인 검토 결과 | coverage·coherence·separation·인용 지원·비용·지연을 비교; 실제 corpus 결과와 합성 테스트를 구분 |
| 6. 독립 Agent·Auditor | 독립 세션, 질문 라우팅, 답변 초안, 감사·수정·기권 | 다른 관점의 증거 사용 차단; 미승인 답변 노출 차단; 부족한 증거에서 기권 |
| 7. 사용자 흐름 | 최소 3개 연결 task, 비교·질문·원문 확인 UI | Factory 결과에 근거해 task 확정; 원문 복귀와 복구 가능한 오류 상태 검증 |
| 8. 연구용 배포 | 배포 URL, 실행 README, fallback, 평가 기록 | 준비된 표본으로 시연 재현; 실제 사용자 테스트 및 course deliverable 확인 |

M3의 Figma low-fi와 사용자 테스트는 별도 수업 산출물입니다. 모든 공학 단계를 마칠 때까지 이를 미루지 않습니다.
이 계획의 구현 순서가 M3/M4 제출 일정이나 최소 3개 연결 task 요건을 변경하지는 않습니다.

## 먼저 보존할 설계 제약

- 자동 수집 대신 준비된 DatasetSnapshot으로 시작합니다.
- 합성 fixture로 구조를 검증할 수 있지만 실제 다국어 분석 성능의 근거로 사용하지 않습니다.
- V0는 원문 embedding, V1은 구조화된 claim 기반, V2는 V1에 Cluster Auditor를 추가합니다.
- Cluster Auditor의 필요성과 연구 기여는 V0/V1/V2 비교 후 판단합니다.
- agent 수를 고정하지 않습니다. 미검증 후보를 확정된 Perspective Agent로 내보내지 않습니다.
- 답변 Auditor는 cluster 품질 검토와 별개의 책임입니다.
- Reflection의 구체적 구현 범위는 pipeline 검증 후 결정합니다.

## 미결정 사항의 처리 시점

| 항목 | 처리 시점 |
| --- | --- |
| GitHub 소유자·저장소·공개 범위 | 확정: `joowonkime/commentscope`, public |
| corpus 확보 방식과 사용 가능 범위 | 실제 연구 데이터 반입 전; 합성 fixture 작업은 먼저 가능 |
| provider·모델·키 소유자·실행 예산 | 실제 모델 호출 전; 지금 특정 provider에 고정하지 않음 |
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
