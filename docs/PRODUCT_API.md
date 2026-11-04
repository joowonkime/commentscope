# 제품 개발 API와 실행

TASK-015/008/009/010, REQ-004~009. 개발용 `/mvp` 화면과 `/api/v1`의 현재 구현이다.
기존 `/`와 [M0 API](COMPARE_BACKEND_API.md), 팀 프론트와 Figma는 유지한다.

## 실행

Python 3.12 이상에서 저장소 루트로 이동하고 `python -m pip install -e .`를 실행한다.
모델 없이 화면과 API를 확인하려면 다음 명령을 사용한다. 새 디렉터리 이름을 지정한다.

```bash
python -m experiments.mvp_browser_fixture runs/my-product-preview
```

출력된 로컬 주소 뒤에 `/mvp`를 붙여 접속한다. 모든 댓글·관점·응답이 합성인 개발 확인용이다.
의견 입력 → 관점 비교 → 관점 하나 또는 둘 선택 → 대화 → 원문 → 성찰 분석/직접 작성 → 저장을 수행한다.
같은 브라우저에서 새로고침하면 세션과 저장본을 다시 불러온다. 원래 저장본은 수정 후에도 DB에 남는다.

실제 모델 서버는 개인 Factory 산출물, **이미 승인된 동일 cycle**, 공유 지출 정책과 키가 필요하다.
저장소에 실제 댓글·개인 대화·키·장부를 추가하지 않는다. 새 서버도 cycle 비용을 초기화하지 않는다.

```bash
python tools/serve_mvp.py prepare runs/my-bounded-product \
  --factory-run runs/EXISTING_FACTORY_RUN \
  --cycle-file runs/EXISTING_CYCLE/cycle.json \
  --session-ttl-seconds 86400 --room-maximum-usd 1
python tools/serve_mvp.py serve runs/my-bounded-product \
  --experimental --key-file /PRIVATE/KEY_FILE --port 8767
```

`prepare`는 추론하지 않는다. 전체 자동 profile을 현재 compiler로 검증하고 입력·구현·가격 상한·cycle을 동결한다.
`serve`도 질문 전에는 추론하지 않는다. 호출은 기존 OpenRouter runner와 공유 예산 장부를 거친다.
만료된 cycle은 새 생성을 막지만 실행 중인 서버의 기존 기록 읽기와 수동 저장은 가능하다.
변경된 코드/원본/동결 계획은 재사용을 거부한다. 유료 서버는 파일 진입점으로 실행한다.

## 공통 계약

클라이언트가 생성한 URL-safe 32-byte token(패딩 없는 43자)을 `X-Session-Token`에 전달한다.
서버는 token hash만 저장한다. HTTP 변경 요청은 같은 origin의 `application/json`이다.
모든 변경에 `request_id`가 필요하다. 같은 ID/본문은 기존 결과를 반환하고 다른 본문은409다.
사용자 의견·room·저장본에는 `expected_revision`을 사용한다. 충돌하면 최신 GET 뒤 명시적으로 다시 요청한다.
작업은202와 `job_id`를 반환하고 `GET /api/v1/jobs/{id}`로 완료를 확인한다. 원시 모델 출력은 공개하지 않는다.
다른 세션의 자원은404다. opinion500/2000자, 질문1000자 제한은 Unicode code point 기준이다.

아래 `{session}`은 `/api/v1/sessions/{sid}`, `{room}`은 `/api/v1/rooms/{rid}`이다.
각 요청의 전체 필드는 [상호작용 계약 I-02](design/INTERACTIONS.md#i-02-리소스와-api)를 따른다.

| 동작 | 현재 endpoint |
| --- | --- |
| 등록 분석/세션 | `GET /api/v1/analyses`, `POST /api/v1/sessions`, `GET {session}` |
| 의견 저장 | `PUT {session}/opinions/initial`, `PUT {session}/opinions/current` |
| 관점 비교 | `POST {session}/comparisons` |
| 대화 생성/읽기 | `POST {session}/rooms`, `GET {room}?after_seq=N` |
| 대화 실행/질문 | `POST {room}/start`, `POST {room}/messages` |
| 제어 | `POST {room}/control`의 pause/resume/next_round/close/acknowledge_error |
| 성찰 분석 | `POST {session}/reflection-analyses` |
| 사용자 성찰 저장/수정/읽기 | `POST {session}/reflections`, `PUT/GET {session}/reflections/{id}` |
| 작업/원문 | `GET /api/v1/jobs/{id}`, `GET {session}/sources/{source_id}` |

비교는 실제 사용자 구간·허용 claim·필수 전제와 인용을 연결한다. 빈 의견은 생성 없이 비교 불가다.
같은 입력 revision의 완료된 비교/성찰은 새로운 request_id에도 재사용한다. 의견 수정은 이전 분석을 stale로 만든다.
1:1은 한 Agent, 그룹은2~3Agent다. 그룹은 각 Agent의 opening/reply 후 사용자 입력을 기다린다.
다른 Agent 발언은 문맥이며 근거는 각자의 allowlist에서 host가 복원한다. 게시된 발화당 원문을 조회할 수 있다.
pause는 현재 호출 뒤 멈추고 resume은 미게시 턴부터 진행한다. close 이후 늦게 도착한 응답은 게시하지 않는다.
room별18턴/동결 금액 한도와 전역 단일 모델 호출을 적용한다. 부분 실패는 이전 게시를 보존하며 자동 재시도하지 않는다.

성찰의 `stayed/changed/newly_learned/worth_more_thought`는 모두 빈 배열이 가능하다.
AI 제안과 사용자 `user_items`는 별도다. 사용자는 제안 채택·수정·수동 작성으로 저장할 수 있다.
`analysis_job_id`는 분석을 사용하지 않으면 null이다. 관련 대화는 실제 소유 message ID만 허용한다.
저장·열람·poll·원문 조회는 모델을 호출하지 않는다. 성찰 읽기는 관련 대화 이동용 room/seq 참조를 제공한다.

## 검증 범위와 남은 연결

이 서버의 분석은 `experimental`, `quality_gate_passed:false`, `semantic_reliability:not_assessed`다.
모델이 과거에 자동 생성한 합성 snapshot의 bundle도 개발 자료로 등록할 수 있다. 실제999개 댓글의 품질 합격과 구별한다.
host의 ID·인용·소유권 검사는 의미 귀속·답변 적절성·모델 설명의 정확도를 보증하지 않는다.
Agent는 현재 전체 allowlist를 사용하며 retrieval8 후보 설계는 미구현이다.
재시작 시 queued job은 취소하고 실행 중 job은 needs_reconciliation으로 남긴다. 자동 유료 재전송/복구 UI는 없다.
충돌 응답은 오류 코드를 제공하며 최신 revision 상세는 GET으로 얻는다.
source가 만료된 bundle로 서버를 새로 시작하는 read-only 모드는 아직 없다.
개발 화면은 팀 프론트 통합 TASK-011과 최종 사용자/품질 검증 TASK-012를 대체하지 않는다.

오프라인 검사는 `python -m unittest discover -s tests`와 기존 Node UI 검사로 실행한다.
별도 Chromium이 있으면 다음 실제 브라우저 검사를 실행할 수 있다. provider는 합성이므로 비용은0이다.

```bash
node experiments/mvp_browser_check.cjs /PATH/TO/PYTHON /PATH/TO/CHROME runs/new-browser-check
```

`experiments.mvp_live_smoke`는 실행 중 서버에 명시적 `--live`로만 요청하며 정상 경로에서 최대9개 모델 요청을 한다.
CI는 이를 실행하지 않는다. 승인된 cycle/잔여/종료시각을 확인한 뒤에만 사용하며 실패 후 자동 재전송하지 않는다.
