# 클러스터링 → Agent 생성 공동 개발 초안

기준일: 2026-10-24. 이 브랜치는 조원이 읽고 수정할 수 있는 개발 초안이다. 전체 댓글에서의 클러스터링 품질과 MVP 완료를 주장하지 않는다. 기존 실험 코드도 포함하므로 모든 모듈이 최종 채택된 것은 아니다.

## 먼저 실행하기

Python 3.12 이상에서 저장소 루트를 기준으로 실행한다. pip 설치·GPU·모델·API 키가 필요 없다.

```bash
git clone https://github.com/joowonkime/commentscope.git
cd commentscope
python tools/check_factory_draft.py
```

이 명령은 **실제 파이프라인 코드에 합성 댓글과 미리 작성한 모델 응답을 넣어** 연결·출처 소유권·보류·집계 계약을 검사한다. 실제 Qwen 추론이나 실제 댓글 품질 평가는 아니다. 상세 항목은 `--verbose`로 확인한다. 생성되는 `runs/`는 Git에서 제외된다.

화면/API는 별도 확인한다.

```bash
cd src
python -m commentscope.agents.team_demo --session-dir ../runs/team-demo
```

브라우저: http://127.0.0.1:8766. 이 화면은 합성 Agent를 사용하는 API 연동 데모이며, 클러스터링을 실행하지 않는다. [API 계약](COMPARE_BACKEND_API.md)을 참고한다.

## 한 번의 파이프라인에서 무엇을 만드나

전체 연결 진입점은 [minimal_pipeline.process](../src/commentscope/factory/minimal_pipeline.py)다. 질문마다 Factory를 재실행하지 않고, 생성된 bundle을 대화 런타임에 넘긴다.

| 단계 | 입력 → 출력 | 주로 수정할 파일 |
| --- | --- | --- |
| 원문 등록 | snapshot → canonical 출처·부모 문맥 | `ingestion/`, `factory/framed_corpus.py` |
| 후보 추출 | 출처별 원문 → 관점 후보·출처 연결 | `factory/minimal_claims.py` |
| 후보 통합 | 후보·embedding → 같은 의미 후보 통합 | `factory/candidate_consolidation.py` |
| 소속 판정 | 원문·후보 → 지지/반대/보류 관계 | `factory/raw_membership.py`, `raw_membership_verification.py`, `minimal_membership.py` |
| 논거 분해 | 지지 원문 → 자기 이유·조건·양보·추가 요청 | `factory/owned_arguments.py`, `source_arguments.py` |
| 사실 검사 | 사실 주장·제공된 근거 문서 → 확인/보류 | `factory/fact_checks.py`, `nli_fact_records.py` |
| Agent 구성 | 후보·관계·논거·검토 → map·bundle·profiles | `factory/minimal_agents.py`, `agents/grounded_inputs.py` |
| 대화 연결 | bundle·질문 → 허용 주장 답변 또는 보류 | `agents/grounded_runtime.py`, `grounded_web.py` |

표의 파일은 `src/commentscope/` 아래다. embedding은 유사 후보를 찾는 데 쓰며, 유사도만으로 유효 지지를 확정하지 않는다. map에 나타나는 클러스터와 대화 가능한 Agent의 승인 조건도 다르다.

`process()` 반환값에서 먼저 볼 항목:

- `candidates`, `memberships`: 후보와 출처별 판정.
- `arguments`, `cores`, `audits`: 출처 소유 논거와 검사 기록.
- `agent_inputs.map`, `agent_inputs.bundle`, `agent_inputs.compiled.profiles`: 지도, 런타임 입력, Agent 입력.
- `errors`, `capacity_holds`: 처리 실패·문맥 용량 때문에 보류한 항목.

`save(name, value)` 콜백으로 중간 산출물을 저장할 수 있다. `quality_gate_passed=False`는 실행 완료만으로 의미 품질을 승인하지 않는다는 뜻이며, 테스트 통과만으로 True로 바꾸지 않는다.

## 모델 실행과 연결되는 경계

`process()`는 모델 서버를 직접 띄우지 않는다. 호출자가 다음 콜백을 제공한다.

| 경계 | 역할 |
| --- | --- |
| `runner.call(stage, request)` | system·data·schema·max_tokens 요청 실행; output·raw·errors 등 실제 응답 반환 |
| `embed(stage, texts_by_id)` | 출처/후보 ID별 embedding 반환 |
| `inspect(request)` | 요청 해시·입력 토큰·문맥 적합 여부 확인 |
| `fact_check(request)` | 근거 문서에 대한 사실 검사 결과 반환 |

정확한 호출 예시는 [test_minimal_pipeline.py](../tests/test_minimal_pipeline.py)의 `ScriptedRunner`와 `MinimalPipelineTests.process`에 있다. 이 runner는 테스트용이며 실제 모델 어댑터가 아니다.

현재 전체 Factory 검증에서 선택한 설정은 `discovery_mode='free'`, `membership_mode='raw'`, `verification_contract=raw_membership_verification.ALIGNED`다. 함수 기본값과 다르므로 명시해야 한다. `contextual`·`shared`는 별도 실험 경로이며, 실험을 구분해서 기록한다.

[experiments/minimal_factory_pipeline.py](../experiments/minimal_factory_pipeline.py)는 작성자 환경의 고정 실행 계획·ledger·모델 경로를 사용하는 연구 실행기다. 필요한 `runs/`와 실제 자료는 공개 저장소에 없으므로 clone 직후 실행할 수 있는 명령으로 취급하지 않는다. 조원이 실제 모델을 붙이려면 위 콜백의 어댑터와 비공개 입력을 별도로 준비해야 한다.

## 현재 확인 범위와 남은 일

- 합성 검사: 후보 추출부터 Agent 2개·출처별 논거·각 3질문까지의 연결, 원문 소유권, 보류, 고정 분모 집계 계약.
- 제한된 실제 자료: UBI 한 영상에서 Agent 2개·각 유효 지지 3개와 실제 6응답/HTTP 경로 확인. [현황과 검증 한계](TEAM_STATUS.md) 참고.
- 전체 Factory 목표: 고정 분모 755에서 453개 이상 활용, G2 12/19·G3 45/74 후보 보존, 집계 지지 전수 유효, 최소 Agent 2개·각 지지 3개와 기존 사실·내용·실행 검증. **전체 달성은 미완료**다.
- 새 전체 검증 실행은 첫 embedding 이후 모델 시작 전 메모리 commit 여유 검사에서 중단됐다. 이는 공동 코드 수정의 선행 조건은 아니다.

평가 계약은 [factory-acceptance-r5.json](../tests/fixtures/factory-acceptance-r5.json)과 [acceptance.py](../src/commentscope/factory/acceptance.py)를 따른다. 합성 검사 결과를 실제 활용률로 보고하지 않는다. 모델 판정도 독립 정답으로 간주하지 않으며 실제 원문·부모·후보 대조가 필요하다.

## 조원이 수정하는 방법

최신 `main`에서 개인 작업 브랜치를 만든다. 코딩 에이전트는 [AGENTS.md](../AGENTS.md)와 [조원 시작 안내](TEAM_START.md)의 절차를 따른다.

```bash
git switch main
git pull --ff-only
git switch -c feat/my-factory-change
# 위 표의 담당 모듈 수정
python tools/check_factory_draft.py
git add <수정한_파일>
git commit -m "Describe the pipeline change"
git push -u origin feat/my-factory-change
```

PR 대상은 `main`으로 지정한다. 제목과 본문에 수정 단계, 기대하는 동작, 실행한 검사, 실제 모델 검증 여부를 적는다. 쓰기 권한이 없으면 fork로 참여한다. 소유자는 Settings → Collaborators에서 조원 계정을 초대할 수 있다.

팀 분담 예시는 후보 추출/통합, 원문별 소속·논거, Agent/runtime·프론트 연결이다. 출력 필드·출처 ID·판정 의미를 바꾸면 연결 단계와 테스트도 함께 수정한다. 실제 댓글·ledger·모델 응답은 기존 정책대로 Git에 올리지 않는다.
