# Re.View 발표본과 개발 인계

팀이 2026년 11월 24일에 최종 발표용으로 선택한 웹사이트입니다. SBS 영상에서 만든 다섯 관점을 비교하고 대화한 다음, 대화 전후 자신의 의견을 돌아봅니다. [최종 발표 사이트](https://commentmas.vercel.app/)

| 화면 | 직접 해볼 수 있는 일 |
| --- | --- |
| Explore | 첫 의견을 입력하고 다섯 관점의 입장, 이유, 댓글 수와 좋아요를 읽습니다. **Similar to me**, **New considerations**, **Most liked**로 관점을 비교합니다. **287 other opinions**에서 다섯 관점 밖의 의견도 확인할 수 있습니다. |
| Converse | **New chat**에서 1:1 또는 그룹을 고릅니다. 그룹에서는 모두에게 묻거나 한 관점을 지정합니다. **Resume discussion**으로 관점 간 답변을 이어 가고 **Evidence**에서 근거를 볼 수 있습니다. |
| Reflect | 대화 뒤 현재 의견을 직접 적습니다. AI가 제안한 **Stayed**, **Changed**, **New considerations**, **Open questions**를 살펴보고, 연결된 발언으로 돌아가거나 해석을 수정하고 저장할 수 있습니다. |

## 발표본 실행

브라우저에서 위 사이트를 열면 설치가 필요 없습니다. 같은 화면을 자신의 컴퓨터에서 확인하려면 **Python 3.12 이상**, **Node.js 22.12 이상**을 설치하고 저장소 루트에서 실행합니다. Windows에서 Python 명령 이름이 `py`라면 `python`을 `py -3`로 바꿀 수 있습니다.

```bash
python presentation/release_client.py prepare
cd presentation/frontend
npm ci
npm run preview:presentation
```

브라우저에서 **http://127.0.0.1:4173/** 를 엽니다. Git에 보관한 화면이 실행되고 `/api` 요청은 발표 사이트로 전달됩니다. 이 미리보기에서도 대화·성찰 생성을 실행하면 운영 API와 모델을 사용할 수 있습니다. 인증과 대화 기록은 접속한 브라우저와 사이트 주소에 연결되므로 공개 사이트와 로컬에서는 별도의 사용자로 시작할 수 있습니다.

`prepare`는 Git에 있는 HTML, JS 템플릿, CSS, 이미지, 폰트를 사용합니다. 첫 실행에서는 현재 공개 중인 번들에서 Firebase 브라우저용 설정값 하나를 읽어 원래 JS를 복원하고 88개 파일의 체크섬을 검사합니다. 복원이 끝나면 같은 체크아웃에서 다시 실행할 때 기존 파일을 재사용합니다. 공개 번들의 주소가 바뀌었으면 해당 Firebase 프로젝트의 공개 웹 키를 `REVIEW_FIREBASE_WEB_API_KEY` 환경 변수로 전달할 수 있습니다. 모델 키는 이 과정에 필요하지 않습니다. 준비해 둔 로컬 파일이 있어도 인증과 서비스 기능은 운영 API에 의존합니다.

| 저장소 루트에서 실행할 명령 | 확인하는 대상 |
| --- | --- |
| `python presentation/release_client.py check` | 저장된 정적 파일과 설정값을 뺀 JS 템플릿. 네트워크 접근 없이 검사합니다. |
| `python presentation/release_client.py verify-live` | 현재 공개된 HTML부터 글꼴까지 88개 경로의 실제 바이트. 배포가 달라지면 실패한 경로를 출력합니다. |

## 편집과 테스트

| 팀 개발 전달본 | 담당하는 동작 |
| --- | --- |
| [components.tsx](frontend/src/components.tsx), [App.tsx](frontend/src/App.tsx) | 초기 의견, 관점 필터, 카드, 화면 전환과 방 선택 |
| [ChatView.tsx](frontend/src/ChatView.tsx), [Reflect.tsx](frontend/src/Reflect.tsx) | 대화의 참여자와 근거 표시, 전후 의견 비교와 해석 피드백 |
| [collect_comments.py](collect_comments.py), [filter_comments.py](filter_comments.py), [group_comments.py](group_comments.py), [perspective_agents.py](perspective_agents.py) | 댓글과 답글 수집, 주제 적합성 필터링, 관점 발굴·배정, 근거가 있는 Agent 구성과 응답 |
| [web_data.py](web_data.py), [web_server.py](web_server.py), [llm_client.py](llm_client.py) | 표시용 자료 준비, 방·비동기 작업·성찰 API, 모델 호출 |

전달받은 React 소스의 빌드는 `index-Dr0TFNcZ.js`입니다. 발표본은 `index-pAus9dvm.js`를 사용하며 익명 Firebase 인증과 서버의 `/api/profile` 저장 요청을 확인했습니다. 팀은 발표 시점의 서버 함수 소스·배포 커밋을 공유받지 못했습니다. 이 저장소에 병합된 변경을 Vercel로 자동 반영하는 연결도 확인되지 않았습니다. [발표본 파일과 체크섬](release/manifest.json)

개발 시 다음 명령은 합성 데이터와 대역 응답으로 실행됩니다. 브라우저 테스트는 자체적으로 로컬 개발 서버를 시작합니다. 실제 모델 키나 원본 댓글 파일 없이 그룹 선택, 부분 실패 후 재시도, 근거 복원, 작은 화면의 레이아웃을 확인할 수 있습니다.

```bash
cd presentation
python -m unittest discover -s tests
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

실제 데이터로 전달본을 개발할 때는 담당자가 별도로 보유한 분석 폴더와 서버용 모델 설정이 필요합니다. 분석 폴더에는 `01_filter/filtered.json`, `02_group/groups.json`, `03_agents/agents.json`이 들어갑니다. `presentation`에서 `python web_server.py --data <분석폴더>`를 실행한 뒤 `frontend`에서 `npm run dev`를 실행합니다. 로컬 API는 8000번, 편집 중인 화면은 5173번 포트를 사용합니다. 원본 댓글 덤프, 개인 대화, 팀의 .env 파일은 전달 대상에서 제외했습니다.

2026년 11월 24일 Chromium에서 공개 사이트와 4173번 미리보기를 각각 새 사용자로 열어 익명 인증 뒤 초기 API 응답 200, SBS 댓글 1,217개와 관점 5개를 확인했습니다. 앞서 공개 사이트에서 그룹 방 생성(201), 질문 접수(202), 성찰 생성(202), 저장(201)과 연결된 발언으로 돌아가기를 확인했습니다. 기존 GCP 웹 주소는 발표 사이트로 이동하며 기존 Python AI API는 독립적으로 운영됩니다.

## 배포 파일의 라이선스

브라우저 배포본에 포함된 React, Firebase JavaScript SDK, Inter, Geologica의 라이선스는 [licenses](release/licenses)에 있습니다. 공개 리소스의 원본 경로와 해시는 [manifest.json](release/manifest.json)에 기록했습니다.
