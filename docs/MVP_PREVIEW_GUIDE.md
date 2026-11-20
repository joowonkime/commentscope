# CommentScope MVP 사용법

**Explore → 자동 토론 → 최종 결론·합의 Agent → Reflect**를 브라우저에서 확인하는 팀 검토용 안내입니다.
Python 3.12 이상과 브라우저가 필요합니다. 예시 댓글과 모델 응답을 함께 제공하며 API 키와 GPU는 필요 없습니다.
[검증 브랜치와 PR #119](https://github.com/joowonkime/commentscope/pull/119)

## 1. 코드 받기

Git 없이 확인하려면 ZIP을 내려받아 풀고, 그 폴더에서 터미널을 엽니다. [검토 브랜치 ZIP](https://github.com/joowonkime/commentscope/archive/refs/heads/feat/mvp-automatic-debate-20261120.zip)

Git으로 받으려면 아래 명령을 실행합니다.

```bash
git clone --branch feat/mvp-automatic-debate-20261120 https://github.com/joowonkime/commentscope.git commentscope-preview
cd commentscope-preview
```

## 2. 실행하고 브라우저 열기

운영체제에 맞는 명령을 실행합니다.

**Windows PowerShell**

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m experiments.mvp_browser_fixture runs/team-consensus --automatic-debate
```

**macOS · Linux**

```bash
python3 --version
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/python -m experiments.mvp_browser_fixture runs/team-consensus --automatic-debate
```

터미널에 출력된 `origin` 뒤에 **`/mvp`**를 붙여 엽니다. 주소가
`http://127.0.0.1:8767`로 출력됐다면 브라우저에는 `http://127.0.0.1:8767/mvp`를 입력합니다.
포트 번호는 실행마다 달라질 수 있습니다. 사용하는 동안 터미널을 켜 두고, 끝나면 `Ctrl+C`로 종료합니다.

## 3. 화면에서 전체 흐름 확인하기

1. **처음 열기.** 초기 의견에 `Safety checks matter, but their cost depends on the risk.`를 적고 **Save & explore perspectives**를 누릅니다. 빈 의견으로도 시작할 수 있습니다.
2. **Explore.** **Compare with my view**에서 한 관점과 초기 의견을 비교합니다. 비교 창을 닫고 두 관점 카드의 체크박스를 선택한 뒤 **Converse with selected perspectives**를 누릅니다. 관점 한 개를 선택하면 1:1 질문이 열립니다.
3. **자동 토론.** `어떤 위험에서는 안전 검토가 필요하며 어떤 예외를 둘 수 있나요?`를 입력하고 **자동 토론 시작**을 한 번 누릅니다. 두 관점의 입장 발언 2개와 상호 응답 2개가 자동으로 게시됩니다. **원문**과 **응답 대상**을 눌러 근거와 답한 발언을 확인할 수 있습니다.
4. **최종 결론.** 상단 **토론 결론 보기** 또는 기록 끝에서 공통 주장, 수락한 관점, 조건, 남은 이견을 확인합니다. 예시에서는 두 관점이 수락한 공통 주장 1개로 별도 합의 Agent 1개가 만들어집니다. [토론 결론과 합의 Agent 화면](images/mvp-preview/debate-result.png)
5. **합의 Agent에 질문.** **계보 원문**으로 근거 댓글을 열고, **합의 Agent에 질문하기**를 누릅니다. 새 방에 `What exactly was agreed and what remains uncertain?`을 입력한 뒤 **Start conversation**을 누릅니다. [합의 Agent 후속 답변 화면](images/mvp-preview/synthesis-agent-followup.png)
6. **Reflect.** **Reflect on your own view**를 눌러 참고할 발언을 선택하고 현재 의견을 적습니다. **Analyze my reflection**에서 제안을 확인하거나 직접 내용을 작성한 뒤 **Save my reflection**을 누릅니다. 새로고침 후 **Reflect → 성찰 보기 · 저장본**으로 돌아옵니다. 제안에서 채택한 관련 대화 링크로 같은 발언을 열 수 있습니다. [성찰 재열람 화면](images/mvp-preview/reflected-after-reload.png)

## 4. 합의가 없을 때와 진행 중인 상태 확인하기

같은 화면에서 다른 결론을 확인하려면 아래에서 원하는 결과의 명령 한 줄을 실행합니다.
Windows PowerShell에서는 `python` 대신 2절의 `.\.venv\Scripts\python.exe`를,
macOS·Linux에서는 `./.venv/bin/python`을 사용합니다.

```bash
python -m experiments.mvp_browser_fixture runs/team-no-consensus --automatic-debate --debate-result no-consensus
python -m experiments.mvp_browser_fixture runs/team-hold --automatic-debate --debate-result hold
```

출력된 주소의 `/mvp`에서 두 관점을 선택하고 토론을 시작합니다.

| 확인할 경우 | 화면에서 볼 동작 |
| --- | --- |
| 합의 없음 | **토론 결론 · 합의 없음**에서 이견과 발언을 읽고 Reflect로 이동합니다. 합의 Agent는 생성되지 않습니다. |
| 검증 보류 | **토론 결론 · 검증 보류**에서 검증된 기록을 확인할 수 있습니다. 합의 Agent는 생성되지 않습니다. |
| 진행 중 새로고침 또는 빠른 연속 클릭 | 같은 토론 기록으로 돌아갑니다. 새로고침이나 연속 클릭이 토론을 두 번 시작하지 않습니다. |
| 일시정지 · 재개 | 진행 중 **Pause**를 누르면 현재 처리를 마친 뒤 멈춥니다. **Resume**으로 이어갑니다. |
| 종료 | **End chat** 이후에도 이미 게시된 발언과 저장된 결론을 대화 목록에서 다시 열 수 있습니다. |

## 5. 자주 막히는 지점

| 증상 | 확인할 것 |
| --- | --- |
| `No module named commentscope` | 위 설치 명령과 서버 실행에 같은 Python을 사용합니다. 저장소 루트에서 설치했는지도 확인합니다. |
| Windows에서 스크립트 실행이 제한됨 | PowerShell에서 위의 `.\.venv\Scripts\python.exe` 명령을 그대로 사용합니다. 가상환경을 활성화할 필요가 없습니다. |
| Ubuntu·Debian에서 `ensurepip is not available` | 설치된 Python 버전에 맞는 `venv` 패키지를 준비한 뒤 가상환경을 다시 만듭니다. [개발 환경 안내](TEAM_START.md#2-처음-한-번-저장소와-무료-화면-확인) |
| `--automatic-debate`를 인식하지 못함 | 1절의 PR 브랜치나 검증한 코드 ZIP을 사용 중인지 확인합니다. |
| 화면에 1:1 대화만 열림 | Explore에서 관점 두 개를 체크하고 `--automatic-debate`로 실행한 서버 주소에 접속합니다. |
| 브라우저에서 접속할 수 없음 | 코드가 실행 중인 터미널의 `origin`을 복사해 `/mvp`를 붙입니다. GitHub에서 보는 검토 페이지와 실행 주소는 별개입니다. |
| `FileExistsError`로 서버 시작 실패 | `runs/team-consensus-2`처럼 아직 없는 새 경로를 지정합니다. 저장·새로고침 확인은 같은 서버와 브라우저에서 진행합니다. |

## 6. 검증 범위와 개발 자료

검증 브랜치의 Chromium에서 합의 23개, 합의 없음 18개, 검증 보류 17개 확인 항목을 통과했습니다.
합의가 있는 실행은 같은 초안에 대한 검증된 수락 2개, 공유 주장 1개, 별도 Agent 1개를 서버에 저장했고, 그 Agent가 후속 질문에 답했습니다. 합의 없음과 검증 보류의 생성 Agent 수는 0개였습니다. [검증한 코드의 Ubuntu·Windows CI](https://github.com/joowonkime/commentscope/actions/runs/44640328901)

이 실행은 합성 예시를 쓰는 로컬 MVP로 유료 호출은 0회입니다. 실제 영상에서의 답변·합의 품질,
큰 댓글 입력의 처리, TA가 접속할 공개 주소와 운영 검증은 별도입니다.

- 소스 변경과 작업 분담은 [팀 개발 시작 안내](TEAM_START.md)를 봅니다.
- 자동 토론 API, 계층 구조, 브라우저 자동 검증 명령은 [구현 및 통합 안내](design/DEBATE_IMPLEMENTATION.md)를 봅니다.
