# 관점 비교·질의 API — M0

기존 `commentscope.agents.grounded_web`의 로컬 HTTP API를 재사용한다.
이 문서는 프론트 연동 자료이며 Figma에 자동 반영하지 않는다.
현재 실제2 Agent·6응답·HTTP 검증은 [전달 자료](COMPARE_BACKEND_DELIVERY.md)에 기록돼 있다.
현재 M0 검증은 합성 fixture와 모의 provider로 수행했다. 실제 댓글 기반 Agent 생성·품질 승인을 뜻하지 않는다.

| 요청 | 입력 | 결과 |
| --- | --- | --- |
| `POST /api/session` | `ids` 선택, `initial_opinion` 선택 | 201, `token`과 세션 상태 |
| `GET /api/state` | `X-Session-Token` 헤더 | 초기 의견, 관점 목록, 선택, 질문/답변, 실행 상태 |
| `POST /api/ask` | 세션 헤더, `question`, `request_id` | 202, 실행 상태. 이후 state 조회 |
| `POST /api/source` | 세션 헤더, `source_id` | 선택 근거의 원문 객체 |

```json
{"ids":["P1","P2"],"initial_opinion":"기회가 생기더라도 전환 기간의 지원이 필요하다고 생각한다."}
```

`P1/P2`는 형식 예시다. 실제 `profiles[*].candidate_id`를 사용한다.
ids는0~2개, 생략하면 이용 가능한 앞2개를 선택한다. 검수된 Agent2개가 실제 존재해야 최종 경로를 시연할 수 있다.
초기 의견은 문자열·최대500 Unicode code points이며 공백·줄바꿈을 포함한 원문을 보존한다. 생략은 빈 문자열, null/다른 타입/초과는400이다.
유효하지 않은 초기 의견으로는 세션이나 파일을 생성하지 않는다.

세션 상태에는 기존 필드에 `initial_opinion`이 추가된다. 같은 값은 세션의 `manifest.json`에도 저장된다.
로컬 개발 화면의 초기 의견 입력란은 선택한 관점으로 새 대화를 만들 때 이 필드를 전송한다.
초기 의견은 현재 Agent의 댓글 근거·사실·이력 입력에 삽입하지 않는다. 사용자 의견 대비 동의/차이 자동 판정은 아직 구현되지 않았다.

```json
{"question":"이 관점이 중요하게 여기는 이유와 조건은 무엇인가요?","request_id":"question-1"}
```

선택된 Agent마다 같은 질문을 처리한다. 현재 구현은 순차 실행하며, 한 Agent의 답변을 다른 Agent에게 자동으로 넘기지 않는다.
`request_id`와 질문이 같으면 재요청 시 중복 추론하지 않고, 같은 ID의 다른 질문은409다.
`job`은 `idle/running/done/error`, `rounds[*].answers[*]`에 Agent별 `candidate_id/status/answerability/limitation/points/required_premises`가 있다.
`points[*].citations.comment_evidence[*].source_id`를 원문 조회에 전달한다.

```json
{"source_id":"인용에 반환된 canonical source ID"}
```

새 Factory bundle은 인용된 자식의 부모 원문을 별도 `source_contexts`에 결합한다. 해당 원문 조회에는 선택 필드 `PARENT_CONTEXT_ONLY: {id, text}`가 추가된다. 부모는 문맥 참고로 별도 표시하며 지지 투표·자식의 이유·모델 근거 항목에 추가하지 않는다. 부모 정보가 없는 기존 bundle의 응답은 같다.

세션 헤더·동일 origin·JSON body·기존 입력 재검증을 유지한다. 부분 실패 때 사용자에게 성공한 전체 라운드로 게시하지 않고 이력을 되돌린다.
모델 원문 응답을 그대로 UI에 게시하지 않는다. 기존 `quality_gate_passed/human_approved` 상태를 기계 테스트 통과만으로 true로 바꾸지 않는다.
현재 앱의 세션 만료·동시 실행·질문 수 제약은 기존 동작이며, 최종 통합 사용성 검증은 M3에서 기록한다.

서버 명령은 기존 `python -m commentscope.agents.grounded_web <bundle> --experimental`이다.
현재 검토된 실제 bundle 경로와 고정 HTTP 재현 명령은 [전달 자료](COMPARE_BACKEND_DELIVERY.md)를 따른다. 전체 UI·전체 Factory 품질 검증과는 구분한다.
