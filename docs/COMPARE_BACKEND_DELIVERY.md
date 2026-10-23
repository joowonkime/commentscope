# 실제 관점 비교·질의 백엔드 전달 자료

2026-10-23 현재 계약의 실제 댓글→두 Agent→질문→HTTP 경로를 검증했다.
검증 범위는 기존 UBI 영상 하나다. 전체 Factory 품질, 기존 r5 G3/G4, 조원 프론트 화면, 실제 참가자 사용자 테스트는 이 결과로 완료하지 않는다.

## 전달하는 산출물

- 실행용 원본 bundle: `runs/compare-backend-20261023-v1/M2-endorsement-runtime-v3/artifacts/bundle.json`
- 전체 Factory·원문별 생성 기록: `M1-explicit-endorsement-v1/artifacts/output.json`
- 집계 원문 6건 검토: `M2-endorsement-source-audit-v1/report.json`
- 최종 Agent 내용 2건 검토: `M1-explicit-endorsement-v1/agent-input-reviews.json`
- 실제 6응답·직접 검토: `M2-endorsement-runtime-v3/artifacts/runtime.json`, `answer-reviews.json`
- 실제 HTTP 요청/응답 25건: `M3-endorsement-http-v1/http-exchanges.json`, `report.json`

위 상대 run 이름은 모두 `runs/compare-backend-20261023-v1/` 아래다. bundle은 자동 Factory 결과를 수정 없이 내보냈다. 검토 라벨은 모델 입력에 포함하지 않는다.

| 실제 관점 | candidate_id | 검토된 canonical 지지 |
| --- | --- | --- |
| UBI가 상황에 따라 바람직할 수 있다는 호의적 입장 | `MC0a3c01f8658ead9b0f2e959e4a640792f5f9701eab0f8a01a14e42e3cae98398` | 3 |
| 기본 생활은 UBI로, 추가 욕구는 노동 소득으로 충당하자는 규범적 설계 | `MCa2c15086adcf3fb06615ff987bd2e50a90ae784a3258d36cdba2fff1418806a7` | 3 |

두 관점은 대립 찬반이 아니다. 실제 비교는 `different`였다. 두 번째는 제안 원문 하나와 정확한 부모 제안에 명시적으로 동의한 답글 둘이다. 답글의 자기 동의 행위는 own-only NLI로, 지시 대상은 canonical 부모 연결로 각각 확인했다. 부모의 이유를 답글 작성자의 이유로 옮기지 않았다.

실제 질문은 각 Agent에 입장, 이유·조건, 자료에 없는 정확한 비용·사고 감소율의 세 가지를 보냈다. 입장 2건과 출처가 있는 이유 1건은 답했고, 추가 이유가 없는 경우와 없는 수치는 3건 보류했다. 답변은 허용된 주장 원문을 선택해 출력한다. 새로운 설명 문장이나 번역을 생성하는 대화기는 아니다. 이유·조건의 명시적 영어/한국어 질문에는 해당 역할만 선택하게 제한하며, 일반 질문 의도 전체의 정확성을 검증한 결과는 아니다.

## 모델 호출 없이 HTTP 경로 다시 확인

프로젝트 루트에서 다음을 실행한다. 결과 폴더는 매 실행마다 아직 없는 새 이름이어야 한다.

```bash
export PYTHONPATH=src:.
commentscope_python=/home/taeng/.venvs/commentscope-clustering/bin/python
"$commentscope_python" runs/compare-backend-20261023-v1/reproduce_actual_http.py prepare runs/compare-backend-20261023-v1/M3-http-local-replay-v1 --source-run runs/compare-backend-20261023-v1/M2-endorsement-runtime-v3
"$commentscope_python" runs/compare-backend-20261023-v1/reproduce_actual_http.py run runs/compare-backend-20261023-v1/M3-http-local-replay-v1
```

실제 HTTP 서버를 일시 실행하여 선택·질문·조회한다. 응답은 원래 ledger까지 검증된 실제 Qwen 완료 응답만 재사용한다. 요청이 다르면 실패하며 새 추론이나 모의 답변으로 대체하지 않는다. 초기 의견·원문·부모·세션/이력 분리·동일 request_id 중복 실행 방지를 검사하고 서버를 종료한다.

## 프론트 연동

[API 계약](COMPARE_BACKEND_API.md)의 세션 생성·질문·상태·원문 조회를 사용한다. 실제 ID는 `/api/state`의 profiles에서 가져온다. 질문은 선택된 두 Agent에 동일하게 전달되며 각 이력은 별도로 유지된다. 초기 의견은 원문대로 저장하고 Agent 근거로 승격하지 않는다.

새 질문을 사용하는 로컬 개발 서버는 기존 Qwen 서버가 port8091에서 실행 중이어야 한다.

```bash
export PYTHONPATH=src:.
/home/taeng/.venvs/commentscope-clustering/bin/python -m commentscope.agents.grounded_web runs/compare-backend-20261023-v1/M2-endorsement-runtime-v3/artifacts/bundle.json --experimental
```

이는 새 추론이 발생하는 개발 명령이다. 위의 고정 HTTP 재현 명령은 Qwen 서버 없이 완료 응답만 재사용한다. `--experimental`, 기존 품질 상태 및 `human_approved=false`는 전체 제품의 독립 품질 인증을 뜻하지 않는 기존 경계를 유지한다. 고정 bundle은 snapshot 사용 기한인 2026-11-08까지 유효하다.

[모듈 분담](COMPARE_BACKEND_GUIDE.md#모듈-경계와-조원-공유)과 [사용자 테스트 과업](COMPARE_BACKEND_USER_TEST_TASKS.md)을 조원에게 공유할 수 있다. Figma 원본은 변경하지 않았다. 실제 화면 변경과 참가자 테스트는 별도 작업이다.
