# CommentScope — 지금까지 만든 것

**별도 배포 시연 앱:** [CommentMAS 시연 링크](https://commentmas.vercel.app) ·
[소스 및 실행 안내](apps/commentmas/README.md) · [공유 범위·검증 기록](apps/commentmas/IMPORT.md).
2026-11-24 사용자 요청으로 배포된 React/Python 앱을 `apps/commentmas/`에 추가했습니다.
기존 `src/commentscope`의 API·Factory·명세 상태는 유지합니다. 실제 댓글·키·개인 기록은 포함하지 않습니다.

**2026-11-18 인수인계:** 새 담당자는 [HANDOFF — 현재 상태·무료 실행·필요 자료](docs/HANDOFF.md) →
[현재 구현 구조와 Mermaid](docs/design/IMPLEMENTED_STRUCTURE.md)부터 읽습니다.
Agent 생성 이후의1:1/그룹·근거·성찰도 구현돼 있지만 실제 답변 유용성은 부족합니다.
999는 과거 canonical 댓글 수이며,일반 실행기의 기본1000 제한 전달 문제와
모듈의 명시적3000 설정을 구별합니다. 무료 재현과 다음 작업은 인계 문서에 있습니다.

**각자 AI로 GitHub 협업을 시작하려면:** [조원 시작 안내](docs/TEAM_START.md)의
담당 Issue·복사용 AI 프롬프트·무료 `/mvp` 실행·브랜치/PR 절차를 따릅니다.
구조 결정은 [구현 보존 기준과 설계 확정 경계](docs/IMPLEMENTATION_BASELINE.md)를 따르며,
구현 AI가 미결정 역할·API·합의 정책을 임의로 정하지 않습니다.
토론→합의→통합 Agent의 [DS-v2 상세 설계·구현 인계](docs/design/DEBATE_SYNTHESIS.md)는
검토안(DEC-029 proposed)이며 수락 후 담당 Issue로 구현을 배정합니다.
**M4 제출 준비도:** [최신 공식 전체 기준과 실제/합성/미구현 대조](docs/M4_PROTOTYPE_REVIEW.md).
기존 화면과 제한 실행은 있으나 자동 토론→최종 결론/합의 Agent는 아직 미구현입니다.
전체 흐름과 남은 구현, 팀원별로 전달할 수 있는 작업 묶음은 [MVP 완주·선택 인계](docs/MVP_IMPLEMENTATION_HANDOFF.md)에 있습니다.

**작업 정본:** [MVP 명세](docs/MVP_SPEC.md) → [작업·재개 절차](docs/SPEC_WORKFLOW.md).
구현 후보의 모듈·알고리즘·입출력·API·상태·비용·검증 사례는 [상세 설계](docs/design/README.md)에 있습니다.
제품 흐름은 **Explore → Converse → Reflect**이며, 현재 다음 작업은 관점 발굴·최종 답변의 유용성 검증이다.
`python tools/check_mvp_spec.py --resume`로 명세 버전·다음 작업·미결정·유료 실행 보류를 확인한다.
현재 상태와 작업 ID는 [추적표](docs/mvp-traceability.json)에 있다. 아래 과거 검증은 그 범위의 증거다.

**댓글에서 관점·근거를 검증해 Agent를 만들고 기존 제품 화면에 연결했습니다.**
선정 영상180댓글에서2개 Agent·실제1:1 질문8건/그룹4턴·성찰 수정/재열람을 확인했습니다.
관점 다양성과 이유·연구 설명·상호 대응 품질은 부족합니다. 전체MVP 완료는 아닙니다.

현재 저장소는 이 초안을 조원들이 받아 함께 고치는 공통 시작점입니다.

**무슨 모듈이 구현됐는지 보려면 [모듈 설명 — 구현·검증·남은 일](docs/MODULE_OVERVIEW.md)을 읽으세요.** 역할, 입출력, 담당 코드와 조원 분담을 한 문서에 정리했습니다.

**Factory 검증 계약과 이력:** [재개 설계](docs/FACTORY_RESTART_PLAN.md)에 G1~G4와 비용·복구 방식을 정리했습니다. 현재 실행 선택은 해당 계획·deployment로 확인하며 문서의 과거 모델 설정을 재사용하지 않습니다.

## 그래서 지금까지의 결론은?

| 궁금한 점 | 현재 답 |
| --- | --- |
| 무엇을 만들었나? | 댓글 입력 → 관점 후보 추출 → 후보 통합 → 원문별 지지 확인 → 이유·조건 정리 → Agent 생성 → 질문·근거 조회 코드 |
| 실제로 확인한 것은? | 최신 선정영상180댓글에서2개profile/각1출처,비교·1:1·그룹·원문·성찰의 제한 실행. 과거 UBI/999와 구별 |
| 이제 완성인가? | 연결된 개발 프로토타입이다. 관점 발굴·답변/상호 대응·용량 연결·홈/기록·지속 배포·사용자 QA가 남았다. |
| 다른 조원이 할 수 있는 일은? | 합성3과업 화면 확인,구조도/용량 재현,특정 모듈 수정과 결과 검토 |
| 모델 없이 실행되나? | 아래 합성 데모와 코드 검사는 가능하다. 실제 댓글 자동 분석에는 별도 자료와 모델 환경이 필요하다. |

## 코드 몰라도 수정 요청하기

이 저장소를 내려받아 코딩 에이전트에서 폴더를 연 다음 아래처럼 요청합니다. 수정할 내용만 바꿔 적으면 됩니다.

> README.md와 AGENTS.md를 읽어줘. 내가 원하는 변경은 [수정할 내용]이야. 기존 작업을 보존하고 별도 작업 브랜치에서 구현·검사한 뒤 GitHub에 PR까지 만들어줘. 결과는 비개발자가 이해할 말로 설명해줘.

[AGENTS.md](AGENTS.md)에 작업 브랜치 생성 → 수정 → 검사 → PR 제출 절차를 설정했습니다. 온라인 제출에는 GitHub 로그인과 저장소 쓰기 권한 또는 fork 권한이 필요합니다. 실제 작업은 에이전트에 변경을 요청했을 때 시작됩니다.

구체적인 절차는 [조원 시작 안내](docs/TEAM_START.md), 수정 위치는 [파이프라인 개발 안내](docs/PIPELINE_DRAFT.md)를 봅니다.

## 화면으로 확인하기

Python 3.12 이상에서 가상환경을 준비하고 저장소 루트에서 실행합니다.
GPU·로컬 모델·API 키는 필요 없습니다. 운영체제별 가상환경 준비는
[조원 시작 안내](docs/TEAM_START.md#2-처음-한-번-저장소와-무료-화면-확인)를 따릅니다.

```bash
python -m pip install -e .
python -m experiments.mvp_browser_fixture runs/my-first-preview --seeded
```

출력된 `origin` 뒤에 `/mvp`를 붙여 브라우저로 엽니다. 초기 의견 입력 → 관점 비교 →
1:1/그룹 → 원문 → Reflect 저장·새로고침을 확인합니다. 종료는 `Ctrl+C`입니다.
다시 실행할 때는 아직 없는 다른 `runs/` 경로를 사용합니다.

**이 화면은 합성 예시입니다.** 미리 만든 댓글·Agent·응답·판정을 사용하며 실제 클러스터링이나 모델 품질을 시연하지 않습니다. 실제 자료에서 확인한 현재 범위는 [인수인계](docs/HANDOFF.md)에 기록했습니다.

## 다음에 함께 할 일

1. [기존 호출·오류·비용 기준선](docs/design/BASELINE.md)과 상세 설계·추적표의 현재 작업을 따라 후보 계약을 구현하고 품질·비용을 검증합니다.
2. 이미 구현된 비교·그룹·성찰의 답변 유용성과 최종 게시 결과를 보완합니다.
3. 논의 중인 독립 홈/영상 진입/개인 기록과 지속 배포·초행 QA를 구별해 진행합니다. Figma 원본은 요청 범위에서 보존합니다.

저장소 루트의 `python tools/check_factory_draft.py`는 합성 자료로 연결·출처·집계 계약을 검사합니다. 실제 의미 품질 평가는 별도입니다.

[조원 시작 안내](docs/TEAM_START.md) · [상세 구현 현황](docs/TEAM_STATUS.md) · [API 계약](docs/COMPARE_BACKEND_API.md) · [검증 요약](docs/examples/backend-validation-summary.json)

실제 댓글·개인 대화·키·모델 파일·실행 장부는 공개 저장소에 포함하지 않습니다.
