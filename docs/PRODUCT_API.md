# 제품 개발 API와 실행

TASK-015/008/009/010, REQ-004~009. 개발용 `/mvp` 화면과 `/api/v1`의 현재 구현이다.
기존 `/`와 [M0 API](COMPARE_BACKEND_API.md), 팀 프론트와 Figma는 유지한다.

## M4 팀 QA와 평가 운영 계약

TASK-036·038, REQ-004~009, DEC-028·030. 기존 Factory가 채택한 모든 관점과 대화 프로토콜을 사용한다. 선정 영상은 운영자가 출처와 실제 대화를 확인한 뒤 등록 순서로 기본값을 정한다.

- 관점 이름은 검증된 핵심 주장으로 식별한다. 입장과 이유의 원문은 카드에서 접어 두고 비교 상세에서도 열 수 있다. 의견 revision별 비교가 확인된 경우에만 카드와 양쪽 근거 문장에 관계를 표시한다. 조회와 새로고침은 자동 생성 요청을 보내지 않는다.
- 같은 분석 범위의 고유 원댓글에서 좋아요를 합산한다. 복수 연결과 미연결은 별도 구간이고 좋아요 누락과 실제 0을 구별한다. 이전 저장 분석의 ID와 세션은 계속 열려야 한다.
- Converse에서 새 참가자를 고르고 1:1, 그룹 질문 또는 지원되는 자동 토론을 시작한다. 그룹의 사용자 질문은 응답할 참가자를 지정할 수 있다. 복구 가능한 일반 대화 실패는 사용자가 기록을 확인한 뒤 기존 방에서 새 질문을 보낸다. 검증 보류와 미정산 지출은 각 상태의 기존 계약을 따른다.
- 평가 서버는 등록된 분석, 같은 호스트의 HTTPS, 지속 SQLite, 고정 종료시각과 누적 지출 한도를 사용한다. 개발·Factory 시간창은 기존 계약을 따른다.

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

현재 `/mvp`는 기존 Figma의 세 과업을 구현한다. 관점 수·근거·처리 댓글 수는 API에서 읽으며
댓글이 여러 관점에 속하면 구성 비율에 중복해서 더하지 않는다. 원문은 drawer에서 읽고,
비교와 성찰의 강조 구간은 실제 의견 revision/구간을 사용한다. SVG·글꼴은 로컬 asset이다.

영상은 등록된 video ID의 썸네일에서 사용자가 눌렀을 때만 iframe으로 연다. iframe만
`strict-origin-when-cross-origin`을 사용해 앱 origin을 전달하며 기본 페이지의 `no-referrer`는 유지한다.
[YouTube의 임베드 식별 안내](https://developers.google.com/youtube/terms/required-minimum-functionality#embedded-player-api-client-identity)에 따른 설정이다.
모바일 player의 최소 높이는200px다. 브라우저 회귀의 미디어 요청은 전송 전에 fixture로 대체하며,
참조 헤더와 layout을 검사한 결과를 실제 YouTube 재생 성공으로 보고하지 않는다.

외부 HTTPS reverse proxy에서 실행할 때는 `serve --bind 0.0.0.0 --public-origin https://YOUR_HOST`를
명시한다. host/origin이 일치하는 요청만 허용한다. 기본 실행은 loopback이며 호스팅 계정이나
지속 배포 URL을 자동으로 생성하지 않는다. 공개 준비 시에도 비공개 실행 자료·키·장부를 서버의 정적 경로에 넣지 않는다.

공개 평가 서버는 동일 origin의 UI 파일 세 개를 검증된 Git 버전별로 게시한다. 원자료·모델 실행·누적 예산을 고정한 백엔드는 기준 UI 파일도 계속 검증한다. 재배포 검사는 기존 세션으로 인용한 원댓글까지 조회한다. [공개 QA와 배포 절차](M4_TEAM_QA_HOSTING.md)

## 선택 기능 Library

REQ-009, TASK-036/038. Before Use의 YouTube video URL 입력은 영상 ID로 등록 분석을 찾는다. 유효한 분석을 만나면 해당 영상의 Before Use를 바로 열며, 같은 영상은 화면과 초안을 유지한다. 잘못된 URL, 미등록 영상, 만료된 분석은 입력 아래에 안내하고 현재 영상과 의견을 유지한다. Library에서도 기존 분석과 개인 기록을 계속 열 수 있다.

등록 영상의 제목·포스터·플레이어·YouTube 링크는 현재 선택한 영상 ID를 따른다. Before Use에서는 실제 크기의 포스터가 로드된 뒤에도 페이지 안에 사진과 재생 버튼이 들어와야 한다. 원본 링크는 플레이어를 열기 전후와 작은 화면에서 사용할 수 있다. 고해상도 포스터가 없으면 작은 썸네일로 전환하며, 썸네일이 없어도 영상은 열 수 있다. Explore 첫 화면은 고유 댓글 중 최종 입장에 연결된 수를 기존 중복 없는 집계와 같은 분모로 표시한다. 합의가 성립하지 않은 토론 결론에서는 참가자가 선택된 일반 대화 선택창을 열 수 있다. 선택창을 열거나 취소하는 동안 종료된 토론 기록과 비용은 유지되며 새 질문을 제출해야 응답이 생성된다.

등록 분석 목록의 선택적 `GET /api/v1/analyses?video=<YouTube URL 또는 ID>`는 기존 수집기의 URL 해석을 사용해 일치 항목만 반환한다. 단일 값이 비어 있거나 잘못된 경우에는 `400 invalid_video_url`, 미등록은 빈 `analyses`, 만료 분석은 기존 `expired` 상태를 반환한다. 이 경로에는 댓글 수집·모델 호출·등록 변경이 없다. 새 영상의 전체 분석은 현재 별도 운영자 실행 계획이 필요하다.

첫 시작은 Before Use → Explore → Converse → Reflect이다. 상단 Library를 열고 닫거나 뒤로 가면 현재 화면과 입력이 유지된다. 등록 영상을 선택하면 해당 분석의 Before Use로 들어간다. [Figma 설계](https://www.figma.com/design/Q5oqIs2ekQIagiboAFX7Qc/MAS?node-id=823-3498) · [Figma 화면](https://www.figma.com/design/Q5oqIs2ekQIagiboAFX7Qc/MAS?node-id=825-3504)

`GET /api/v1/analyses`는 재사용 가능한 등록 분석 목록을 제공한다. 운영자는 서버 prepare의 `--additional-factory-run`을 반복해 이미 검증된 분석을 등록할 수 있다. 기본 영상과 추가 자료의 원문과 산출물을 같은 서버 계획에 고정한다. 시험 장부에 결합된 단일 Factory 시연은 해당 분석만 쓴다.

My records는 이 브라우저에 있는 세션 접근 정보로 기존 읽기 API를 호출한다. 각 세션의 기존 접근 권한, 만료, 출처 상태를 따른다. 다른 브라우저에서는 해당 기록에 접근할 수 없다. 저장 토론·성찰을 여는 경로는 모델을 호출하지 않으며, 합의 Agent의 기존 후속 질문 버튼은 Converse에서 이용한다.

같은 브라우저의 각 탭은 열어 둔 세션으로 복귀한다. 다른 탭에서 영상을 바꾸거나 새 리뷰를 시작해도 기존 탭을 새로고침하면 그 탭의 영상과 기록이 열린다. Before Use에서 Library로 현재 영상을 다시 선택하면 입력 중인 의견이 보존된다.

세션·일반 대화방·합의 Agent 대화방 생성과 의견·성찰 저장은 서버가 반영한 뒤 응답이 끊겨도 같은 입력을 다시 보낼 때 같은 `request_id`를 사용한다. 세션 생성은 최초의 접근 토큰도 재사용한다. 같은 입력의 재시도는 처음 만든 기록으로 돌아오며, 사용자가 바꾼 입력은 새 요청으로 처리한다. 탭의 재시도 정보에는 의견·성찰 본문을 저장하지 않는다.

Converse에서 같은 방·수신자에게 보낸 후속 질문의 응답을 잃으면 재전송은 최초 요청 ID와 방 버전을 함께 사용한다. 이 사이 Agent가 답했더라도 기존 질문과 답변을 보여 준다. 수신자나 질문을 바꾸거나 성공이 확인된 뒤 다시 작성하면 새 발언으로 접수한다.

작업 진행 상태, 토론 기록과 성찰을 여는 GET 요청은 해당 시점까지 커밋된 내용을 읽는다. 토론 작업이 다음 발언을 저장하는 동안에도 직전 상태를 조회할 수 있다.

## 공통 계약

클라이언트가 생성한 URL-safe 32-byte token(패딩 없는 43자)을 `X-Session-Token`에 전달한다.
서버는 token hash만 저장한다. HTTP 변경 요청은 같은 origin의 `application/json`이다.
모든 변경에 `request_id`가 필요하다. 같은 ID/본문은 기존 결과를 반환하고 다른 본문은409다.
사용자 의견·room·저장본에는 `expected_revision`을 사용한다. 충돌하면 최신 GET 뒤 명시적으로 다시 요청한다.
작업은202와 `job_id`를 반환하고 `GET /api/v1/jobs/{id}`로 완료를 확인한다. 원시 모델 출력은 공개하지 않는다.
다른 세션의 자원은404다. opinion500/2000자, 질문1000자 제한은 Unicode code point 기준이다.

분석 응답의 `composition[].count/likes`는 각 댓글을 한 구간에만 센다(관점 하나만 지지·여러 관점·기타).
각 `perspectives[].support_totals`는 `{comments, likes}`로, 다른 관점과 함께 지지한 댓글까지 해당 관점에 포함한다.
따라서 관점별 합계를 더하면 분석 댓글 수를 넘을 수 있다. 좋아요 수가 하나라도 불명확하면 `likes`는 null이다.

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

등록 분석의 관점 카드와 이유·조건 항목은 각 주장에 결합된 원댓글의 `source_ids`를 포함한다.
원문 열람은 기존 세션 출처 endpoint를 사용하며 출처 주소에는 원문이나 발언자의 정보가 없다.

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
Figma 화면 연결의 합성 회귀는 실제 모델/댓글 E2E 및 최종 사용자/품질 검증 TASK-012와 구별한다.
사용자 확인의 준비 절차는 [MVP 사용자 확인](MVP_USER_CHECK.md)에 있으며 아직 실제 참여자 결과는 없다.

오프라인 검사는 `python -m unittest discover -s tests`와 기존 Node UI 검사로 실행한다.
별도 Chromium이 있으면 다음 실제 브라우저 검사를 실행할 수 있다. provider는 합성이므로 비용은0이다.

```bash
node experiments/mvp_browser_check.cjs /PATH/TO/PYTHON /PATH/TO/CHROME runs/new-browser-check
```

`experiments.mvp_live_smoke`는 실행 중 서버에 명시적 `--live`로만 요청하며 정상 경로에서 최대9개 모델 요청을 한다.
CI는 이를 실행하지 않는다. 승인된 cycle/잔여/종료시각을 확인한 뒤에만 사용하며 실패 후 자동 재전송하지 않는다.


### 명시적 1출처 관점 모드 (TASK-026 / DEC-028)

[새 관점·토론 계약](design/SEEDED_PERSPECTIVE_DEBATE.md)의 bundle을 등록하면
`ProductApp`은 생성 callback 외에 `decision(stage,payload)`와 `decision_reservation()`을 요구한다.
기존 bundle은 기존 추출 대화와 API를 유지한다. 이 모드의 카드에는 admission policy와 실제
확인 댓글 수가 들어가며 모집단 대표성/관점 중복 해소를 보장하지 않는다.

메시지 `evidence_scope=seeded_provenance`, 각 point의 `origin`은 `original_comment`,
`ai_reasoning`, `external_evidence` 중 하나다. 댓글은 원문 인용/지지 수를 유지하고 새 문단의
`member_source_count`는0이다. 새 문단의 `requires`/`anchor_claim_ids`는 원댓글 claim을 가리킨다.
`external_evidence`는 준비된 https문헌/정확한 구간이며 새 웹검색 구현을 뜻하지 않는다.
허용되지 않은 문단은 숨기고 남은 답변은 partial/verification_hold로 기록한다.
작성과 문단 판정의 비용은 같은 room·계정에 합산하며 첫 호출 전 둘의 예약 여유를 확인한다.
외부 청구가 불명확하면 기존 needs_reconciliation 절차를 따르고 자동 재시도하지 않는다. 실서버가 생성 요청의 종료된 전송 오류와 미확정 과금을 함께 발견하면 `unconfirmed_provider_call`을 반환한다. 원댓글 읽기와 수동 성찰 저장은 계속된다. 호스트의 `tools/review_product_http.py`는 서버 중지 후 같은 장부·요청·종료 HTTP 오류·완료 체크포인트가 맞을 때 기존 예약 전액을 보수적으로 계상한다. 같은 요청의 실패 기록은 보존된다.

새 runtime v2의 보류는 검증된 한계 설명을 포함할 수 있다. 이 경우에도
`status=abstain`, `answerability=abstain`을 유지하며 answered 집계에 넣지 않는다.
설명 문단은 동일한 출처/문헌/typed 검사를 통과해야 하며 화면에도 보류 설명을 표시한다.

TASK-028의 [웹 연결 계약](design/SEEDED_WEB_INTEGRATION.md)에 따라 일반 `serve_mvp.py`는
새모드 bundle의 Jev deployment를 prepare에 동결하고 build에서 생성/판정 callback을 함께 연결한다.
legacy bundle에는 이 설정이나 Jev 호출을 추가하지 않는다. 생성/판정 비용과 알려진 실패 차감은
같은 기존 금융owner·room에 합산한다. 기존 동결 실행 파일은 변경하지 않으며 새 설정에는 새 plan이 필요하다.

등록 영상 전체의1회 생성과 같은 owner의 제품 대화는 `tools/prepared_video_trial.py`의
`prepare/run/serve`로 연결한다. `serve DIRECTORY --port 8767`은 loopback `/mvp`를 제공한다.
이 실행기는 공개 호스팅·품질 승인·종합 Agent를 자동 생성하지 않는다.
무료 새모드 브라우저 확인은 기존 검사 명령 마지막에 `--seeded`를 붙인다.
