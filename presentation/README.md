# 최종 발표본 사용 및 검증

팀원이 GitHub에 공유한 원본으로 SBS 주 4.5일제 영상의 댓글 1,217개와 관점 5개를 볼 수 있습니다. [발표 사이트](https://commentmas.vercel.app/) · [최종 소스](../apps/commentmas) · [팀 반입 이력](https://github.com/joowonkime/commentscope/pull/122)

| 화면 | 직접 해볼 수 있는 일 | 편집 위치 |
| --- | --- | --- |
| Explore | 첫 의견을 쓰고 **Save & explore perspectives**를 선택합니다. **Similar to me**, **New considerations**, **Most liked**로 관점을 비교합니다. **287 other opinions**에서 다섯 그룹 밖의 의견도 볼 수 있습니다. | [관점 카드와 비교 화면](../apps/commentmas/frontend/src/components.tsx) |
| Converse | **New chat**에서 1:1 또는 그룹을 고릅니다. 모두에게 묻거나 한 관점을 지정합니다. **Resume discussion**으로 토론을 이어 가고 **Evidence**로 답변 근거를 확인합니다. | [대화 UI](../apps/commentmas/frontend/src/ChatView.tsx) · [Agent와 대화 처리](../apps/commentmas/perspective_agents.py) |
| Reflect | 현재 의견을 직접 적고 **Review what changed**를 누릅니다. **Stayed**, **Changed**, **New considerations**, **Open questions**에서 해석을 검토합니다. **View this moment**로 발언을 다시 열고 해석을 수정하거나 저장할 수 있습니다. | [성찰 UI](../apps/commentmas/frontend/src/Reflect.tsx) · [성찰 API](../apps/commentmas/web_server.py) |

대화 기록과 성찰은 Firebase로 확인한 사용자 단위로 Firestore에 저장합니다. Vercel의 `/api`는 별도 Cloud Run 서비스로 연결됩니다. 이전 GCP VM의 웹 주소는 최종 사이트로 이동하며 해당 VM의 기존 Python API도 유지했습니다. [Vercel 라우팅](../apps/commentmas/frontend/vercel.json) · [Firebase 저장 코드](../apps/commentmas/firebase_backend.py) · [서버 배포 도구](../apps/commentmas/scripts/deploy_backend.py)

## 발표본 재현

Python 3.12 이상, Node.js 22.12 이상에서 저장소 루트 기준으로 실행합니다. Windows에서는 설치 환경에 따라 `python` 대신 `py -3`를 사용할 수 있습니다.

```bash
npm --prefix apps/commentmas/frontend ci
python presentation/check_release.py build
npm --prefix apps/commentmas/frontend run preview:presentation
```

브라우저에서 **http://127.0.0.1:4173/** 를 엽니다. 이 모드는 GitHub 소스를 직접 빌드하고, 인증·대화·성찰에는 공개 사이트의 운영 API를 사용합니다. 실제 질문·성찰 생성을 실행하면 모델을 호출할 수 있습니다. 로컬 주소와 공개 사이트의 브라우저 저장소는 별개입니다.

빌드 명령은 공개 번들의 체크섬을 확인한 뒤 Firebase 브라우저 설정 네 값을 읽어 빌드 프로세스에만 전달합니다. 운영자의 같은 설정을 환경 변수로 주면 외부 조회를 생략합니다. 운영 비밀키·댓글 덤프·개인 대화는 Git에 포함하지 않습니다. 자체 API와 독립 데이터로 개발하거나 배포하는 절차는 [팀 개발 안내](../apps/commentmas/README.md)에 있습니다.

| 확인하고 싶은 것 | 저장소 루트에서 실행 |
| --- | --- |
| 기존 로컬 빌드가 발표 당시 파일과 일치하는지 | `python presentation/check_release.py check-dist` |
| 현재 Vercel이 발표 당시 파일을 그대로 제공하는지 | `python presentation/check_release.py verify-live` |
| 오프라인 Python 회귀 테스트 | `apps/commentmas`에서 `python -m unittest discover -s tests` |
| UI 회귀 테스트 | `apps/commentmas/frontend`에서 `npm ci`, `npx playwright install chromium`, `npm run test:e2e` |

2026년 11월 24일 팀의 소스 커밋 `4f151ee`에서 빌드한 88개 파일이 Vercel과 일치했습니다. 새 브라우저에서 초기 화면의 인증, 관점 5개와 댓글 1,217개를 확인했습니다. 이전 VM 웹 주소를 차단하고 읽기 요청만 허용한 재열람 검사에서는 두 관점의 토론, 근거 버튼 8개, 기존 성찰 글을 다시 열었습니다. 앞선 운영 리허설에서 그룹 방 생성(201), 질문·성찰 생성 요청(202), 성찰 저장(201)도 확인했습니다. [파일별 체크섬](manifest.json)

GitHub 병합과 운영 배포는 각자 추적할 수 있습니다. 팀의 배포 도구는 Vercel CLI와 Google Cloud 권한을 사용합니다. 이번 전환에서 운영 Vercel·Cloud Run 재배포를 실행한 기록은 없습니다. [클라이언트 배포 코드](../apps/commentmas/scripts/deploy_frontend.py)
