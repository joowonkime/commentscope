# CommentMAS 소스 반입 기록

2026-11-24 사용자가 현재 배포한 서비스를 `joowonkime/commentscope`의 `main`에 직접 push하도록 요청했다.
배포 링크는 https://commentmas.vercel.app 이다. 소스 공유 작업이며 이번 반입에서 배포나 모델 호출을 다시 실행하지 않는다.

## 기존 명세와의 관계

읽은 기준은 `commentscope-mvp-20261120-v84`와 `commentscope-detailed-design-20261119-v75`다.
관련 요구사항은 REQ-004(비교), REQ-005(1:1·근거), REQ-006(그룹), REQ-007(성찰),
REQ-009(화면·실행 URL), REQ-010(검증 범위의 추적)이다.
TASK-039의 팀 인계 문맥에 이 별도 앱의 실행 위치와 범위를 제공한다.

`apps/commentmas/`는 기존 `src/commentscope`와 별도로 실행하는 React/Python 프로토타입이다.
기존 Factory·제품 API·DEC-029/030·TASK-027의 계약이나 완료 상태를 변경하지 않는다.
새 앱의 최대 5개 관점·6개 자동 턴·Firestore 저장은 이 시연 구현의 설정이며 기존 제품의 확정 계약으로 승격하지 않는다.
최종 결론·합의 Agent나 전체 Factory 의미 품질의 완료를 주장하지 않는다.

## 포함·제외 범위

화면과 에이전트·수집/필터/그룹 코드, 합성 회귀 fixture, Firebase/Cloud Run/Vercel 배포 스크립트,
공개 프로젝트 ID·API 서버 주소, 비밀 값이 없는 환경변수 예시를 포함한다.

실제 `.env`·Firebase 웹 설정 파일·서비스 계정 키·CLI 인증 캐시·실제 댓글/분석 결과·개인 대화/회고·
스크린샷/실행 보고서·가상환경·`node_modules`·빌드 결과물은 포함하지 않는다.
따라서 새 clone은 운영 시연의 분석 자료와 키를 자동으로 갖지 않는다. 별도 제공된 분석 폴더를
`--data PATH`로 지정하거나 README의 수집→필터→그룹→Agent→웹 데이터 준비 단계를 실행해야 한다.

## 확인한 범위

- 기존 배포에서 제한된 실제 모델 E2E: 관점 비교, 1:1 후속 질문, 3-Agent 토론과 Pause/Resume,
  선택 응답, 원문·저장한 근거, 회고 분석·수정·저장·재열람, 모바일, 독립 브라우저의 기록 격리.
- 구현 회귀: Python 79개, 모의 API를 사용한 Playwright 3개, TypeScript/Vite 빌드.
- 비밀키 검사: 공개 HTML/JS/CSS·환경파일 경로 응답에서 운영 비밀키가 검출되지 않았고,
  OpenAI 키는 Cloud Run의 Secret Manager 참조로 설정된 것을 확인했다.

이 기록은 제한된 기능 검증이며 독립적인 답변 유용성 평가·초행 사용자 QA·기존 r5/G1~G4 통과 증거는 아니다.
실제 대화 원문과 토큰은 이 저장소에 첨부하지 않는다. 반입 전 복사본에서도 합성 회귀·빌드와
Git에 포함될 파일의 비밀키 검사를 수행한다.
