# GitHub에서 각자 AI로 CommentScope 개발하기

2026-11-19 / TASK-030 / REQ-009·010. 처음 받은 팀원과 코딩 AI의 시작 안내다.
상태·품질 근거는 [인수인계](HANDOFF.md), 구조와 Mermaid는
[현재 구현 구조](design/IMPLEMENTED_STRUCTURE.md), 작업 정본은
[MVP 명세](MVP_SPEC.md)·[추적표](mvp-traceability.json)를 따른다.
구현 담당자는 [구현 보존 기준과 설계 확정 경계](IMPLEMENTATION_BASELINE.md)를 먼저 확인한다.
현재 구조 설명과 미래 기능의 확정 설계는 다르다. 담당 AI가 미결정 구조를 정해 구현하지 않는다.

## 1. 팀원에게 그대로 전달할 메시지

> 공통 저장소는 https://github.com/joowonkime/commentscope 입니다.
> 최신 main을 자기 PC에 clone하고, 저장소 폴더를 코딩 AI에서 열어 주세요.
> 먼저 docs/TEAM_START.md와 docs/HANDOFF.md를 읽고 무료 /mvp 화면을 확인해 주세요.
> 아래 시작 프롬프트에 본인 담당 Issue 링크를 넣으면 됩니다.
> 구현은 작업 브랜치에서 하고, 관련 검사 후 main 대상 PR로 전달합니다.
> API 키나 실제 댓글 없이도 합성 화면·코드 수정·대부분의 검사가 가능합니다.
> 담당 범위와 완료 조건은 Issue에, 구현·검사 결과는 PR에 남겨 주세요.

소유자는 함께 push할 팀원을 저장소의 Collaborators로 초대한다.
초대 대신 본인 fork에서 작업하고 원 저장소로 PR을 보내도 된다.
이 안내만으로 GitHub 로그인이나 쓰기 권한이 생기지는 않는다.
ZIP을 받았다면 보존하고 Git 이력이 있는 새 checkout을 clone한다.

## 2. 처음 한 번: 저장소와 무료 화면 확인

Python 3.12 이상을 사용한다. 아래는 터미널 명령이며 AI에 실행을 맡겨도 된다.

~~~bash
git clone https://github.com/joowonkime/commentscope.git
cd commentscope
python -m venv .venv
~~~

Ubuntu/Debian에서 `ensurepip is not available`로 실패하면 현재 Python에 맞는
venv 패키지(예: Python 3.12의 `python3.12-venv`)가 필요하다.
코딩 AI가 환경 오류를 확인해 준비한 뒤 가상환경 생성을 다시 수행한다.
모델/데이터 문제로 해석하거나 로컬 LLM을 설치하지 않는다.

가상환경 활성화는 운영체제에 맞게 하나만 실행한다.

~~~bash
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate
~~~

이후 저장소 루트에서 실행한다. PowerShell 활성화가 제한되면
`.venv\Scripts\python.exe`를 아래 `python` 대신 직접 사용한다.

~~~bash
python -m pip install -e .
python tools/check_mvp_spec.py --resume
python -m unittest discover -s tests -p test_mvp_spec.py
python -m experiments.mvp_browser_fixture runs/my-first-preview --seeded
~~~

마지막 명령은 서버이므로 터미널을 켜 둔다. 출력된 `origin` 뒤에 `/mvp`를 붙여 연다.
종료는 `Ctrl+C`다. 다시 실행할 때는 아직 없는 다른 `runs/` 경로를 사용한다.
GPU·로컬 모델·OpenRouter 키·clustering/openjev 추가 의존성은 이 실행에 필요 없다.
댓글·관점·생성/판정 응답은 모두 합성이고 유료 호출은 0건이다.

초기 의견에 `Safety reviews should be required.`를 적고 관점 비교 → 1:1/그룹 →
원문 조회 → Reflect 직접 수정·저장 → 새로고침 재열람을 확인한다.
이는 화면/API 흐름 확인이며 실제 댓글의 분석·토론 품질 평가는 아니다.

## 3. 지금 있는 것과 새로 정해야 하는 것

| 대상 | 현재 상태와 작업 시작점 |
| --- | --- |
| 관점·Agent 생성 | 등록 snapshot → Factory → 불변 bundle. [구조](design/IMPLEMENTED_STRUCTURE.md), TASK-027 품질 보완 |
| 사용자 대화·그룹 | 1:1·2~3Agent opening/reply·원문·성찰 API와 /mvp 구현. 실질 반박/대응 품질 부족 |
| 합의·통합 Agent | 미구현. [DS-v1 상세안](design/DEBATE_SYNTHESIS.md)의 DEC029 수락 후 TASK032~037로 구현 |
| 댓글 용량 | 과거 999는 데이터 수. 일반 prepare 등의 기본 1000 전달 결함이 남음. [무료 진단](examples/check_snapshot_capacity.py) |
| 최종 프론트 | 기존 확인 화면은 있음. 최종 Figma 최신화·홈/URL/개인 기록·합의 화면은 별도 작업 |
| 실제 실행 자료 | 실제 댓글·키·DB·장부는 Git에 없음. [비공개 인계 경계](HANDOFF.md#4-넘겨야-할-것과-따로-관리할-것)를 따름 |

현재 발언은 자기 관점·허용 댓글·준비 문헌·최근 자기 발언 2개·직전 상대 발언을 입력으로
Sol이 생성하고 Jev 관측/Host 검사 후 게시한다. 댓글/AI 추론/외부 근거를 구별한다.
토론 기록 저장은 Agent의 입장·bundle을 갱신하지 않는다. 기존 그룹을 합의·통합 기능으로 보고하지 않는다.
Figma 파일도 이 안내로 변경되지 않는다.

## 4. 분담은 Issue로 정하고 계약부터 공유

먼저 [Implementation step Issue 양식](https://github.com/joowonkime/commentscope/issues/new?template=implementation.md)에
목표·담당자·관련 TASK/REQ/DEC·변경 범위·완료 조건·확인 방법을 적는다.
GitHub Issue 번호와 명세의 TASK ID는 다른 식별자다. 관련 TASK가 없으면 새 변경의 계약과
TASK를 기록하고 시작한다. Issue를 만든 것만으로 미결정 설계나 유료 실행이 승인되지는 않는다.
구현 Issue에는 적용할 확정 설계의 절·기준 commit/PR와 구조 변경 유무를 적는다.
필요한 계약이 비어 있으면 설계 변경안을 먼저 정리하고 수락 근거가 생긴 뒤 그 범위를 구현한다.
기존 계약 안의 수정은 다시 승인받지 않는다.

다음은 작업을 나누는 예시이며 인원·담당자를 확정한 표가 아니다.

| 작업 | 첫 산출물 | 주요 경계 |
| --- | --- | --- |
| Factory·용량 | 1001/2000/3000 합성 입력의 prepare→등록 실패 재현과 수정 | 기존 source/parent/hash·지지 정책 보존. 실제 3000 실행은 별도 |
| 토론 품질 | 상대 쟁점에 대한 응답과 문단 제거 후 최종 답변의 완료 조건 | seeded_runtime.py, Controller. 최종 답변이 질문에 응답하는지 별도 확인 |
| 합의·통합 | [DS-v1 계약/합성/인계](design/DEBATE_SYNTHESIS.md)의 검토와 수락 후 담당 구현 | 기존 Agent 보존. AI 발언을 댓글 지지로 더하지 않음. 계약 후 구현 |
| 프론트 | 확정 Figma 화면과 [현재 API](PRODUCT_API.md)의 대응표 | 기존 3과업·출처 origin·partial/abstain·job/오류 상태를 표시 |
| 통합·QA | 공통 API/명세 조율과 시나리오 밖 동작 점검 | 새로고침·중복 클릭·다른 Agent·빈 결과·실패·저장 복원 |

팀에서 공통 API·명세를 조율할 담당자 한 명을 정한다. 여러 사람이 토론/통합을 맡아도
같은 `product/app.py`나 API를 동시에 각자 바꾸지 않도록 Issue에 수정 예정 파일을 적는다.
공통 API 변경은 요청/응답 예시·상태·오류·revision/idempotency를 작은 계약 PR로 먼저 맞춘다.
프론트는 기존 API와 합성 fixture로 진행할 수 있다. 미구현 API의 mock은 개발용으로 표시한다.
새 기능이 실제 동작한다고 표시하거나 정해지지 않은 endpoint를 각자 발명하지 않는다.

`--resume`의 TASK-027은 현재 주 작업이다. 별도 담당 Issue를 받았다면 그 계약·관련 TASK를 읽고
작업한다. 모든 팀원이 TASK-027에 중복 착수하거나 전역 `next_task`를 각자 바꾸지 않는다.
새 활성 작업은 SPEC_WORKFLOW의 규칙대로 조율해 기록한다.

## 5. 각자 AI에게 붙여 넣을 시작 프롬프트

아래 두 대괄호를 실제 담당 Issue와 완료 조건으로 바꾼다.
담당 Issue가 아직 없으면 범위와 확인 가능한 완료 조건을 먼저 작성한다.

~~~text
이 저장소에서 내 담당 작업을 구현해줘.
담당 Issue: [GitHub Issue URL]
이번에 끝낼 동작과 완료 조건: [구체적인 입력 → 기대 결과]

1. README.md, AGENTS.md, docs/TEAM_START.md, docs/HANDOFF.md를 읽어줘.
   docs/MVP_SPEC.md → docs/SPEC_WORKFLOW.md를 읽고
   python tools/check_mvp_spec.py --resume을 실행해줘.
   docs/IMPLEMENTATION_BASELINE.md와 Issue의 확정 설계 절·기준 commit/PR,
   관련 TASK/REQ/DEC, design_refs, 현재 구조 및 API를 대조해줘.
2. 현재 구현/제안/미구현과 이번 담당 범위를 짧게 정리해줘.
   지정 Issue가 주 작업 TASK-027과 다르면 그 담당 범위를 따라줘.
   다른 담당자의 코드, Figma, 비공개 실행 자료와 미커밋 변경을 보존해줘.
3. 최신 main에서 작업 브랜치를 만들어줘. 기존 수정이 있으면 보존하고
   별도 checkout/worktree를 써줘. 다른 사람의 미병합 PR을 시작점으로 삼지 마.
4. 정해진 구조·계약 안에서 구현해줘. 필요한 역할/API/자료형·저장·합의 정책이
   미결정이면 설계 변경안을 먼저 제안하고 새 구조로 구현하거나 자가 승인하지 마.
   기존 수락 근거가 있으면 연결하고 재승인을 요구하지 마.
   공통 명세·TASK 상태의 변경은 통합 담당자와 조율해줘.
5. 합성 fixture로 현재 화면을 확인하고, 동작 변경에 필요한 실패 재현과
   관련 검사를 수행한 뒤 구현해줘. 테스트 기대값을 결과에 맞춰 낮추지 마.
   API 키·로컬 모델 없이 진행하고 별도 실행 계약 없는 유료 호출은 하지 마.
6. 내 변경만 commit/push하고 main 대상 PR을 만들어 Issue를 연결해줘.
   PR에는 변경 동작, 관련 ID, 실행한 검사, 조원이 확인할 방법,
   미검증 항목과 다음 작업을 적어줘. 명시된 병합 권한을 따라줘.
7. 중단/완료할 때 branch·commit·PR·검사 결과·남은 실패를 기록해줘.
   CI 성공, 합성 확인, 실제 모델 품질과 전체 MVP 완료를 구별해줘.
~~~

기존 폴더나 GitHub 로그인이 없으면 AI가 clone·환경 준비부터 수행하면 된다.
AGENTS.md를 자동 인식하지 않는 AI에도 위처럼 직접 읽도록 요청한다.

## 6. 하루의 작업은 Issue → 브랜치 → PR → main

Issue를 본인 담당으로 표시하고, 시작할 때 공통 파일/계약을 확인한다.
처음 작업 브랜치는 깨끗한 checkout의 최신 main에서 만든다. 예시:

~~~bash
git fetch origin main
git switch -c feat/issue-123-short-name origin/main
~~~

이미 자기 작업 브랜치가 있으면 이어서 쓴다. 미커밋 변경을 덮어쓰지 않는다.
main의 변경은 자기 브랜치에 merge 또는 팀의 rebase 방식으로 반영하고 충돌을 해결한다.
다른 사람의 작업 브랜치를 강제로 갱신하지 않는다.

로컬에서는 변경에 맞는 검사를 실행한다.

| 변경 | 검사 시작점 |
| --- | --- |
| 명세/작업 상태 | `python tools/check_mvp_spec.py`, `python -m unittest discover -s tests -p test_mvp_spec.py` |
| Factory | 위 검사와 `python tools/check_factory_draft.py`, 관련 회귀 |
| 대화/API/저장 | 관련 `test_product_*.py`, `test_seeded_runtime.py` 등 실제 변경 모듈의 검사 |
| 화면 | 합성 `/mvp`, `node --check src/commentscope/product/mvp.js`, `node --test tests/product_provenance_smoke.cjs` |

Node는 화면의 JS 검사를 할 때 필요하다. 단순 문서 변경에 새 동작 테스트를 만들지 않는다.
필수 CI는 Ubuntu·Windows Python 3.12 검사와 JS/합성 자료 검사를 실행한다.
자동 병합은 팀/사용자의 명시된 권한이 있는 PR에만 적용한다. CI 성공은 토론의 의미 품질이나
새 기능 범위의 승인이 아니다.

PR이 병합된 뒤 다음 사람이 최신 main에서 이어간다. 마지막 PR/Issue에는 다음을 남긴다.

~~~text
담당 Issue / TASK·REQ·DEC:
branch / commit / PR:
구현한 동작 / 실행한 검사:
실패·보류·미검증 / 다음 한 작업:
유료 실행 여부·별도 승인된 비용:
~~~

실제 댓글·키·개인 대화·세션 token·DB·장부는 Issue/PR에 붙이지 않는다.
여러 PC가 같은 팀 잔액을 독립된 새 장부로 지출하지 않도록 실제 모델 검증은
정해진 공통 실행 환경에서 별도 계획으로 관리한다.

## 7. 이번 안내의 확인 범위

2026-11-19에 새 Python 3.12 가상환경에서 기본 editable 설치·명세 검사·관련 18검사,
`--seeded` 서버의 `/mvp` HTTP200을 확인했다. 이 WSL의 표준 venv 생성은 ensurepip 부재로
실패해 위 환경 주의에 기록했고, 별도 가상환경과 기존 pip의 `--python`으로 준비해 확인했다.
시스템 패키지나 로컬 모델을 설치하지 않았다.

동일 합성 서버에서 비교2건·그룹4턴·1:1/후속2턴·성찰 수정/저장 revision2·재열람을
확인했다. 합성 생성9회·합성 판정6회이며 실제 모델/유료 호출은0건이다.
이 결과는 새 AI 협업이나 실제 토론·통합 Agent의 품질을 검증한 결과가 아니다.
