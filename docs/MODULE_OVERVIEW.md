# CommentScope 모듈 설명 — 무엇을 만들었고 무엇이 남았나

2026-10-28 현재 상태와 재개 순서는 [Factory 재개 설계](FACTORY_RESTART_PLAN.md)를 먼저 본다. 아래는 모듈 안내와 이전 검증 범위를 유지한 설명이다.

기준일: 2026-10-25. 프로젝트를 처음 보는 조원도 현재 구현과 다음 작업을 이해하기 위한 안내다. 세부 검증 기록은 [상세 현황](TEAM_STATUS.md), 개발 인터페이스는 [파이프라인 안내](PIPELINE_DRAFT.md)를 참고한다.

## 지금까지의 결론

**댓글에서 관점을 묶고 그 근거를 가진 Agent를 만드는 코드 초안과, 두 관점에게 질문하고 원문을 확인하는 백엔드를 구현했다.** 기존 UBI 영상 하나에서 Agent 2개·각 유효 지지 댓글 3개와 실제 6응답·HTTP 연결을 확인했다.

전체 댓글에서 관점을 충분히 올바르게 찾아 자동 생성한다는 품질 검증은 미완료다. 지금의 공유물은 조원이 받아 수정할 수 있는 개발 초안이다. GitHub `main`에 코드와 실행 안내가 있으며, CI 통과는 코드 검사 결과다.

## 전체 흐름

댓글·부모 원문 → 관점 후보 추출 → 후보 통합·원문별 지지 판정 → 작성자별 이유·조건 정리 → 주요 사실 검사 → Agent 구성 → 질문·답변·원문 조회

아래는 기능별 구분이다. 실제 처리는 필요한 검사를 연결해 실행하며, 질문을 받을 때마다 댓글 분석 전체를 다시 수행하지 않는다.

## 구현된 주요 모듈

| 모듈 | 하는 일 | 입력 → 출력 |
| --- | --- | --- |
| **1. 댓글 입력·원문 관리** | 댓글을 수집·읽기·검사하고, 원문·부모·출처 ID와 중복 관계를 보존한다. | 댓글 snapshot → 분석용 출처 목록 |
| **2. 관점 후보 추출** | 원문에서 주장과 필수 조건을 추출해 관점 후보를 만든다. | 출처별 원문 → 후보 주장·근거 구간 |
| **3. 클러스터링·지지 집계** | 유사 후보를 찾고 같은 의미인지 검사해 통합한다. 각 원문이 후보를 지지·반대하는지, 조건부·불확실한지 구분해 집계한다. | 후보·원문 관계 → 관점 묶음·지지 수·보류 |
| **4. 논거 분해** | 공통 입장과 작성자별 이유·필수 조건·양보·추가 제안을 구분한다. 다른 작성자나 부모의 이유를 자기 이유로 가져오지 않도록 검사한다. | 지지 원문 → 출처별 논거·역할·의존 관계 |
| **5. 사실 검사** | 사실 주장과 필수 사실 전제를 제공된 근거 문서와 대조한다. 확인이 부족하거나 충돌하면 보류한다. | 사실 주장·근거 문서 → 지지·반박·불충분 판정 |
| **6. Agent 생성** | 후보·지지·논거·검사 결과를 묶어 각 Agent의 핵심 입장과 허용 근거를 구성한다. | 검사된 후보 묶음 → bundle·Agent 프로필 |
| **7. Agent 대화** | 같은 질문에 관점별로 답한다. 자기 근거와 이력을 분리하고 허용 주장만 선택하며, 근거가 없으면 보류한다. | Agent 입력·질문 → 출처가 붙은 답변 또는 보류 |
| **8. API·로컬 화면** | 초기 의견 저장, 최대 두 관점 선택, 질문 전달, 응답·원문·부모 조회를 연결한다. | 화면의 요청 → 세션·답변·출처 응답 |
| **9. 평가·실행 관리** | 활용률·후보 보존·집계 오류를 검사하고 호출 장부·체크포인트·자원 보호를 관리한다. | 실행 기록·출력·검토 → 검사 보고·재개 지점 |
| **10. 로컬 모델 실행** | [공통 실행 모듈](LOCAL_RUNTIME.md)로 모델·서버·기동 설정을 분리한다. 소형 모델의 실제 품질·자원 검증은 별도다. | 고정 deployment·요청 → 모델 응답·자원/종료 기록 |

embedding 유사도만으로 지지를 확정하지 않는다. 부모 댓글은 문맥 해석에 쓰며 답글 작성자의 근거를 대신하지 않는다. 댓글이 주장을 지지한다는 판정과 그 주장이 외부 사실로 참이라는 판정도 별도로 다룬다.

## 어디까지 검증됐나

| 확인 범위 | 현재 의미 |
| --- | --- |
| 코드·합성 검사 | 파이프라인 연결, 입력 계약, 출처 소유권, 근거 부족 보류와 집계 규칙을 검사한다. 합성 파이프라인 검사 명령을 제공한다. |
| 제한된 실제 자료 | 기존 영상의 두 Agent와 각 지지 3개를 검토하고 실제 6응답·HTTP 경로를 확인했다. 최종 응답은 답변 3건·적절한 보류 3건이다. |
| 사실 검사 고정 표본 | 40건에서 지원 9/10·비지원 오승인 0/30을 기록했다. 실제 Agent의 필수 사실 검사는 별도로 필요하다. |
| 전체 자동 분석 품질 | 고정 의미 댓글 755개 중 453개 이상을 올바른 공유군집에 활용한다는 목표는 미달성이다. G2/G3 후보 보존 및 G4 전체 검증이 남아 있다. |
| 독립 평가 | 개발에 참여한 Codex의 원문 대조를 독립 사람 평가로 간주하지 않는다. 검증기 자체의 일반 정확도와 과거 수정 전체의 효과는 미입증이다. |

모델 자체검사가 통과해도 논거의 유형·조건·역할을 잘못 해석한 사례가 있었다. 실제 원문·부모·후보·논거를 함께 대조해야 한다. 실행 성공이나 CI 성공만으로 의미 품질 완료를 선언하지 않는다.

## 조원이 지금 확인할 수 있는 것

Python 3.12 이상에서 저장소의 `src` 폴더로 이동해 실행한다. 추가 패키지·GPU·모델·API 키가 필요 없다.

```bash
cd src
python -m commentscope.agents.team_demo --session-dir ../runs/team-demo
```

브라우저에서 http://127.0.0.1:8766 을 열어 두 관점을 선택하고, 입장·이유·비용을 질문한다. 원문 버튼으로 근거를 확인한다. **합성 댓글·Agent와 정해진 응답을 쓰는 연동 데모**이며 실제 클러스터링이나 Qwen 추론을 실행하지 않는다.

저장소 루트에서는 다음 명령으로 합성 파이프라인의 연결·출처·집계 계약을 검사한다.

```bash
python tools/check_factory_draft.py
```

실제 댓글·모델 파일·실행 장부는 Git에 포함하지 않는다. 따라서 clone만으로 기존 실제 실험 자료가 생기지는 않는다. 모델을 바꾸면 모델·실행 설정·표본·결과를 따로 기록하고 같은 기준으로 재평가한다.

## 담당 모듈을 고칠 때 볼 코드

| 담당 영역 | 대표 코드 |
| --- | --- |
| 댓글 입력·출처 | [ingestion](../src/commentscope/ingestion), [framed_corpus.py](../src/commentscope/factory/framed_corpus.py) |
| 후보 추출 | [minimal_claims.py](../src/commentscope/factory/minimal_claims.py) |
| 통합·소속 판정 | [candidate_consolidation.py](../src/commentscope/factory/candidate_consolidation.py), [raw_membership.py](../src/commentscope/factory/raw_membership.py), [minimal_membership.py](../src/commentscope/factory/minimal_membership.py) |
| 논거·조건 | [owned_arguments.py](../src/commentscope/factory/owned_arguments.py), [source_arguments.py](../src/commentscope/factory/source_arguments.py) |
| 사실 검사 | [fact_checks.py](../src/commentscope/factory/fact_checks.py), [nli_fact_records.py](../src/commentscope/factory/nli_fact_records.py) |
| Agent 구성 | [minimal_agents.py](../src/commentscope/factory/minimal_agents.py), [grounded_inputs.py](../src/commentscope/agents/grounded_inputs.py) |
| 대화·API | [grounded_runtime.py](../src/commentscope/agents/grounded_runtime.py), [grounded_web.py](../src/commentscope/agents/grounded_web.py) |
| 평가·체크포인트 | [acceptance.py](../src/commentscope/factory/acceptance.py), [comment_utilization.py](../src/commentscope/factory/comment_utilization.py), [checkpoint_calls.py](../src/commentscope/providers/checkpoint_calls.py) |

[minimal_pipeline.process](../src/commentscope/factory/minimal_pipeline.py)가 핵심 단계를 연결한다. 모델 호출은 어댑터로 제공한다. 단계별 파일과 입출력은 나뉘어 있지만 공통 출처 ID·필드·판정 의미를 공유하므로 인터페이스 변경 시 연결 코드도 함께 수정해야 한다.

## 남은 일과 분담

- **Factory 품질 검증:** 후보 추출부터 Agent 생성까지 실제 자동 출력의 오가입·누락·조건 손실·논거·사실 오류를 검사하고 개선한다. 고정된 전체 댓글을 새로 분석해 완료 목표를 충족한 결과는 아직 없다.
- **조원 프론트 연결:** 영상 입력·관점 선택·질문·원문 버튼을 [현재 API](COMPARE_BACKEND_API.md)에 연결하고 화면 흐름을 함께 확인한다. Figma 원본 변경은 팀과 합의한다.
- **독립 검토·사용자 테스트:** 실제 원문과 결과를 별도 검토자가 대조하고 [사용자 과업](COMPARE_BACKEND_USER_TEST_TASKS.md)을 수행한다.
- **후속 기능:** 별도 온라인 Auditor의 답변 수정, 사용자 성찰, Single-Agent 비교 연구와 배포가 남아 있다. 생성 단계의 검사와 온라인 대화 감사는 범위가 다르다.

조원은 [시작 안내](TEAM_START.md)의 요청 문장을 에이전트에 전달하면 된다. [AGENTS.md](../AGENTS.md)는 코딩 에이전트의 브랜치·검사·PR 협업 절차를 정한 지침이며, 제품의 관점별 Agent는 위 6번 모듈에서 구성한다.
