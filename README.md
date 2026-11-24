# Re.View · CommentMAS

Re.View는 YouTube 댓글에서 관점을 찾아 근거가 있는 Agent를 만들고, 사용자가 이들과 대화한 뒤 자신의 생각을 돌아보게 합니다. 팀의 발표 사례는 SBS 주 4.5일제 영상의 댓글 1,217개와 관점 5개입니다. [발표 사이트 열기](https://commentmas.vercel.app/)

| 하려는 일 | 시작할 곳 |
| --- | --- |
| 새 영상 URL로 Agent 생성하기 | [실행 방법과 배포 설정](apps/commentmas/README.md#영상-url로-agent-생성) |
| 발표·QA 하기 | [Explore → Converse → Reflect 사용 안내](presentation/README.md) |
| 최종 버전 편집·실행하기 | [팀원이 공유한 React·Python 원본과 실행법](apps/commentmas/README.md) |
| 실제 배포와 동일한 화면 빌드하기 | [발표본 재현 및 대조 방법](presentation/README.md#발표본-재현) |
| 이전 CommentScope 개발·실험 확인하기 | [이전 구현·설계·검증 기록](README.legacy.md) |

2026년 11월 24일 발표본의 팀 소스 `4f151ee`로 빌드한 파일 88개는 당시 Vercel 파일과 SHA-256이 일치했습니다. Vercel은 브라우저 화면을 제공하고, `/api` 요청을 Python 서버가 실행되는 Cloud Run으로 전달합니다. Firebase가 사용자 인증을, Firestore가 방과 성찰 기록 저장을 담당합니다. [팀 소스 반입 PR](https://github.com/joowonkime/commentscope/pull/122) · [배포 연결 설정](apps/commentmas/frontend/vercel.json)
