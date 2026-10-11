# 검수 묶음에서 근거 기반 에이전트 응답까지

## 프로젝트 목표와 이번 범위

프로젝트/논문 대상은 clustering 자체가 아니라 댓글에 근거한 관점 에이전트 시스템입니다.
요구사항 Section16.4도 먼저 수동/검수된 입력으로 end-to-end 경험을 확인하고 관점 형성을 자동화하는 순서를 명시합니다.
이번에는 추가 clustering 실험 대신 기존 검수21개에서 개발용 프로필을 만들고 독립 질문·답변·근거 검사·비교 화면까지 연결했습니다.

```text
기존 댓글 snapshot + assistant 검수 결과
             ↓ 출처/만료/원문/중복/배정 재검증
DevelopmentPerspectiveBundle (정식 PerspectiveSpec과 별도)
             ↓ 근거 3개 이상 계열만, 수는 동적
각 AgentSession: 자기 evidence + 자기 history만 접근
             ↓ 인용된 문장 단위로 답변
구조 검사 → 별도 로컬 Auditor 요청
             ↓ 문제 있으면 최대 한 번 수정
검사 통과한 개발용 답변 / 답변 보류
             ↓
질문별 비교 HTML + 원문/부모 문맥 열람 + JSON/checkpoint
```

현재 입력에서는 필요성7개와 도입 예측4개가 각각 하나의 개발용 에이전트가 됩니다.
가능한 이점2개 및 보류8개는 에이전트로 만들지 않습니다. 2라는 수를 코드에 고정하지 않았습니다.
계열 제목은 강한 공통 명제나 모든 작성자의 동일한 입장을 뜻하지 않습니다. 각 조건·이유는 개별 원문에 귀속됩니다.

## 모듈과 계약

- `agents/profiles.py`: snapshot과 검수 artifact를 재검증하고 개발용 bundle 생성. source/citation은 호스트가 고정.
  동일 source의 중복 alias는 거절하고 3개 미만/보류 상태는 non_agents에 남깁니다.
- `agents/runtime.py`: 각 세션은 profile을 복사하고 자신의 근거만 요청에 전달. 질문/대화는 근거가 아니며 다른 agent의
  결과를 공유하지 않습니다. 같은 기저 모델을 별도 evidence/state로 사용하는 것이지 서로 다른 모델을 학습한 것이 아닙니다.
- `agents/demo.py`: build/ask CLI 및 저장된 비교 HTML. bundle을 매번 source에서 재계산해 변경을 검사합니다.
  파일/출처/유효기간 오류는 실행 전에 거절합니다. CLI에서 연결 실패는 보류 결과로 노출하고 임의 fixture 응답으로 대체하지 않습니다.

`--allow-unapproved`는 개발 경로 진입에만 쓰이며 인간 승인으로 변환하지 않습니다.
bundle artifact_kind=development-perspective-bundle-0.1, agent status=development_only_not_approved,
human_approved=false, accepted_perspectives=0입니다. 기존 accepted cluster→PerspectiveSpec 계약은 그대로 유지합니다.
추가된 것은 실험 명세와 runtime이지 승인 gate 우회로 production agent를 발행하는 기능이 아닙니다.

## 응답 및 Auditor

모델은 answerability(grounded/partial/not_in_evidence), 최대2개 points(text/evidence_id), missing_information을 반환합니다.
답변 branch는1개 이상 인용 문장을 요구하고 abstention branch는 points=[]만 허용합니다.
조건부 답변에는 한계 설명을 요구하지만, 이 미검사 자유문 설명은 JSON에만 남기고 사용자 답변으로 표시하지 않습니다.
질문에 없는 외부 사실·수치·다른 agent 의견을 근거로 사용하지 않도록 제한합니다.

각 point는 한 개의 자기 근거를 인용해야 합니다. 존재/소속/형식 검사는 코드로, 원문과의 의미 지원 및 질문 관련성은
별도 모델 요청으로 검사합니다. 모두 supported일 때만 model_audit_passed_development_only로 표시합니다.
revise/unclear/형식 오류가 있으면 한 번만 다시 생성하고, 여전히 실패하면 답변은 보류합니다.
한 문장만 실패해도 전체 답변을 통과시키지 않습니다. 거절된 초안은 JSON에 남지만 최종 HTML 답변/후속 대화에는 넣지 않습니다.

Auditor도 같은 Qwen4B의 별도 요청입니다. **독립 평가가 아니고, 오승인·과도한 거절 모두 가능합니다.**
UI는 정식 승인/정확성 보장과 구분한 개발용 상태를 표시합니다. 이 단계의 모델 검사 통과 수를 충실성 정확도로 보고하지 않습니다.
모델의 설명문도 내부 판단 과정의 증명으로 취급하지 않습니다. 원문과 출력, 검사·수정 기록을 확인 가능한 형태로 남깁니다.

## 실행과 재현

README11단계 명령으로 실행합니다. Python 기본 설치 외에 새 라이브러리/외부 API는 필요하지 않습니다.
로컬 Qwen 서버 실행은 README의 기존 안내를 사용합니다. build는 모델 호출이 없고 ask만 localhost:8091을 호출합니다.
기본 transport는 proxy/redirect를 허용하지 않습니다. 서버의 실제 모델 identity는 운영자 선언이며 원격 증명은 없습니다.

각 실행은 새 경로에 저장합니다. bundle/snapshot/검수 hash, 만료, prompt 본문/hash, generation/audit schema,
runtime 코드 hash, 모델/revision/설정, 질문/agent별 checkpoint, 원시 생성·검사·재시도·시간·token 사용량을 보존합니다.
최대6개 질문, 최근2개의 자기 대화, 생성 최대2회, 요청 max_tokens1200입니다. 프롬프트가 길면 모델 실패로 보류될 수 있습니다.
여러 --question은 같은 실행에서의 후속 질문입니다. 별도 ask 명령은 새 세션이며 자동 resume/세션 영속 복원은 아직 없습니다.

개발 비교 화면은 출력 JSON에 `.html`을 붙인 파일입니다. 파일을 브라우저에서 열면 됩니다.
위 CLI 결과는 정적 파일입니다. **직접 입력하는 로컬 서버는 이후 추가한 README12단계 `agents.web`을 사용합니다.**
실제 댓글을 담은 화면과 JSON은 Git에서 제외합니다.
원문 링크는 허용된 YouTube HTTPS URL만 표시하고, 모든 질문/답변/원문 HTML은 escape합니다.
부모 댓글이 있으면 문맥 전용으로 표시하며 단독 지지 근거로 인용할 수 없습니다.

## 2026-10-11 실제 실행

- 프로필2개: 필요성7개, 도입 예측4개. 검수된21개 중 희소2/보류8개는 비에이전트 상태로 유지.
- 같은 질문3개를 각 에이전트에 순서대로 전달: 관점 설명 / 모두 찬성·80% 소멸만이 도입 조건인지 / 한국 지급액·연도·물가율.
- 첫 실행은 필요성 에이전트가 근거가 있어도 빈 partial 답변을2회 반환해 차단. 도입 예측 에이전트만 첫 질문에 답변.
  초기 구현은 commit67e226a, 실행 `artifacts/development-agents-20261011-comparison.json`에 보존.
- 보완 실행은 answerability 분기 grammar로 빈 답변 방지, 의견 전달과 정책 사실성 입증을 구분한 지시, 짧은 출력 한도를 함께 적용.
  여러 요소 변경이므로 단일 원인 효과나 일반 성능 개선을 주장하지 않음.
- 최신 `artifacts/development-agents-20261011-comparison-v2.json` 및 `.json.html`: 총6회 응답 중 첫 질문2개는 모델 검사 통과,
  두 번째 질문2개는 수정 후 보류, 세 번째 질문2개는 근거 부재로 보류. 승인 관점은0, 개발용 실행 에이전트는2.
- assistant가 표시된4문장을 원문과 대조: M01/M02의 필요성·이유와 M03/M05의 예측·조건을 유지하고 각 agent의 근거만 사용.
  이는 자체 검수이지 독립 정답 평가가 아님. 세 번째 질문의 국가별 수치 생성은 하지 않았음.
- 두 번째 질문의 보류는 전부 올바른 감사라고 주장할 수 없음. 특히 M05에는 조건이 있고 답변에도 남아 있는데 Auditor가
  조건이 없다고 설명하는 오류가 있었음. 질문의 잘못된 전제를 원문 지원 검사와 혼동하는 과도한 거절이 남음.
  거절된 초안을 최종 답변으로 공개하지 않았지만, Auditor 의미 정확성이 검증된 것은 아님.
- 코드 테스트195개 통과. 실제 원문/결과/checkpoint/검수는 비공개. 추가 댓글 수집·외부 추론 API·새 모델 다운로드0.

## 로컬 비교/질의 UI 추가 (2026-10-11)

README12단계에서 모델 서버와 UI 서버를 각각 실행하고 `http://127.0.0.1:8765`를 엽니다.
관점 카드 → 공통 질문 → 생성·검사 진행 표시 → 독립 답변 비교 → 인용 원문 펼치기 → 후속 질문/내보내기를 연결했습니다.
JSON 다운로드에는 거절 초안과 전체 검사 기록이 포함되고, 화면/HTML에는 최종 공개 답변만 표시합니다.
독립 evidence/state, 최대1회 수정, 정식 승인0을 유지하며 감사 프롬프트/모델은 바꾸지 않았습니다.

실행 기록은 `runs/agent-ui/<실행ID>/`에 자동 저장합니다. 새 대화는 메모리 초기화이며 파일 삭제가 아닙니다.
서버에는 외부 호스팅이나 로그인/공유 기능이 없습니다. 모델·앱 모두 loopback, 동시 질문1개, 세션당6질문입니다.
보관 만료/원문 변경/중복 제출/세션 격리/연결 오류를 코드로 검사합니다. 상세 구조는 ADR-016을 참조합니다.

실제 HTTP 연동 검증 (구현 commit `772a4e8`):

- 최초 full-GPU 설정은 현재 여유 VRAM 부족으로 모델 시작 실패. `local-agent-ui-20261011-smoke.json`은
  이 상태의 6개 연결 오류/보류 기록이며 의미 평가 결과가 아닙니다. 성공 출력으로 대체하지 않았습니다.
- 기존 모델/context8192를 유지하고 ngl24/batch128/ubatch128/threads6으로 GPU 사용량을 줄여 재실행.
  모델·프롬프트 품질 개선 실험이 아니라 실행 환경 조정입니다. 다른 프로세스 종료/새 모델 다운로드/외부 추론은 없었습니다.
- `local-agent-ui-20261011-smoke-v2.json`은 UI 초기 구현, `...-v3.json`은 reset 오류 복구·실패 로그·bundle byte hash 보완 후
  서버를 재시작해 실행한 최종 코드 결과입니다. v3의 runtime/web 코드 hash와 현재 코드, HTML 재생성 바이트를 대조했습니다.
- 최종 3질문×2agent: 관점 설명 2답변 통과, 조건 후속 질문은 필요성 agent 보류/예측 agent 통과,
  원문에 없는 한국 지급액·연도·물가율은 둘 다 보류. 공개된6문장(중복 포함)을 assistant가 인용 원문과 대조했습니다.
- 조건 후속 질문의 필요성 agent는 인용한 댓글에 없는 AI/AGI·장기 조건을 넣어 거절됐습니다.
  해당 질문의 다른 지지 문장도 함께 보류하는 all-or-nothing 정책은 유지합니다. 이 사례의 차단이 감사 일반 정확성 증명은 아닙니다.
  감사 이유에도 오류가 남습니다. 해당 원문은 UBI 필요성을 말하지만 감사 이유 일부는 그것도 없다고 설명했습니다.
  판정 방향이 맞아도 설명 전체를 신뢰하지 않습니다. 자체 검수 기록은 `artifacts/local-agent-ui-20261011-assistant-review.json`입니다.
- 실제 모델 요청 시간 합172.50초(서버 로딩/HTTP polling 등 제외), 총17개 모델 요청. 단일 개발 실행이며 성능 benchmark가 아닙니다.
- v3 SHA256 `7131251373ab54871095e1ef4371fd31cb4f8bf9903277e06dcb338e9e7ce27c`.
  파일은 ignored `artifacts/`, 세부 checkpoint는 ignored `runs/agent-ui/`. 보관 만료는 기존 snapshot에서 상속합니다.
- Python210개 + Node 최소 DOM 계약3개 통과, wheel에 HTML/JS/CSS 포함 확인. 실제 브라우저 시각/키보드 QA는 미수행.
  점검 후 모델/UI 서버는 종료했습니다. 웹 질의는 README12단계로 다시 실행합니다.

## main 통합 후 생성 완료 여부 재검증 (2026-10-11)

### 무엇을 실제 실행했는가

1. PR #18을 `a3ead01`로 main에 merge. 누적 PR #6은 merged, #7~#17은 main ancestry 확인 후 통합 참조로 closed.
   collector Issue #5 완료. 브랜치·커밋·원문·실패 기록은 삭제하지 않음. main push CI Ubuntu/Windows 통과.
2. 기존 공식 API1,000개 snapshot을 다시 validate/normalize(567root+433reply, canonical999).
   새로운 댓글 수집은 하지 않음. `main-acceptance-20261011-normalized.json`에 보존.
3. 기존 assistant 검수21개에서 bundle을 새 경로 `main-acceptance-20261011-agents.json`에 생성.
   필요성7/예측4의 개발 agent2개, 희소2/미배정8개 유지. 생성은 출처 검증과 코드 조립이며 새 LLM 공통 주장 합성/별도 모델 학습 아님.
4. 실제 Chromium153.0.8010.12에서 키보드로3질문 제출. 실제 로컬 Qwen 호출17회. 최초 질문은 두 agent 인용 답변,
   조건 후속 질문은 필요성 보류/예측 답변, 한국 수치 질문은 둘 다 not_in_evidence. 표시6문장(중복 포함)을 assistant가 원문 대조.
5. 인용 펼치기·HTML/JSON 다운로드·새 탭의 빈 세션·대화 초기화·390px 모바일 가로 넘침 없음 확인.
   최종 browser 실행97.00초, page error0, 외부 네트워크 요청0. 이는 자동화된 브라우저 수용 검사이지 사용자 연구/전체 접근성 인증 아님.

처음 browser 실행은 마지막 초기화 검사에서 문자열 eval이 CSP에 차단됐습니다. 그전 실제 질의/다운로드는 완료됐지만
검사 전체를 실패로 보존했습니다. `wait_for_function`의 문자열 식을 함수 식으로 수정하고 새 세션에서 전부 재실행해 통과했습니다.
앱 보안 정책·모델·생성/감사 프롬프트는 변경하지 않았습니다. 스크린샷은 assistant가 직접 확인했습니다.

### 생성 부분이 끝났는가

| 완료 조건 | 판정 |
| --- | --- |
| 검수 지원 묶음 → 출처가 고정된 개발 profile → 독립 모델 세션·근거 답변 | 개발 기능으로 동작 확인 |
| 원시 댓글 → 올바른 관점 자동 발견·검증 → 정식 PerspectiveSpec | 미완료 |
| 임의 영상·전체1,000개에서 자동 생성 품질 보장 | 미완료 |

자동 쪽도 기존12개 회귀를 실제 재실행했습니다. 계약10/12, 사전 assistant type/polarity/topic 전체 일치6/12.
개인 목표를 예측으로, 희망을 이점으로 읽거나 인용문을 변형하는 오류가 남았습니다. 기존 사례 반복이며 독립 평가셋이 아닙니다.
현재 연결된 `source_facets` 경로는 AI·자동화/UBI 전용 분류와 최대24개 입력의 개발 실험입니다.
모든 주제에서 의미 있는 공통 주장을 찾아내는 범용 agent factory나 전체 corpus 자동화가 완료됐다는 뜻이 아닙니다.

자동 재실행 결과는 **진단 branch**에만 남겼습니다. agent 입력은 **기존 검수 artifact**를 사용했습니다.
원시 분류 실패를 고쳐 쓴 뒤 자동 성공으로 계산하지 않았으며 `human_approved=false`, `accepted_perspectives=0`을 유지합니다.

### 결과 위치와 재현

- 한눈에 보는 로컬 보고서: `artifacts/main-acceptance-20261011-overview.html`.
- 실제 브라우저 다운로드: `artifacts/main-acceptance-20261011-browser-v2.comparison.json` 및 `.html`.
  JSON SHA256 `a5821bfdfa01b062b9c995f5039acfe0c89b72041f81fd181cd990d04362777c`.
- 브라우저 검사/화면: 같은 prefix의 `.checks.json`, `.initial.png`, `.first-answer.png`, `.final.png`, `.mobile.png`.
- 자동 회귀: `artifacts/main-acceptance-20261011-auto-regression.json` 및 `.json.html`.
  SHA256 `80dd13bb4a6a9d4e2fdff3838a565ba2f884d04851ec2ecab43cd604f43312c2`.
- 새 bundle SHA256 `b34925000c404b5eb04a05f83642258125278333107f76b2071233bed1bde096`으로 기존 검수 기반 bundle과 동일.
- 공개한 재실행 도구 `experiments/browser_agent_smoke.py`는 선택적 Playwright 설치가 필요. 앱의 필수 dependency는 늘리지 않음.
  설치/실행은 README12 참조. 원문·출력·이미지는 Git 제외, 만료 상속. 검사 후 모델/UI 서버 종료.

## 아직 남은 기능

- 실제 비개발자 팀원의 Windows/WSL 실행·사용성 및 전체 접근성 검증(Chromium 기본 동작/화면은 확인).
- 승인된 claim-level PerspectiveSpec, 복합 주장 분해와 정식 관점 승격.
- 에이전트 간 반문·토론의 메시지 경계와 다른 에이전트 발언을 새 근거로 오인하지 않는 검사.
- Reflection의 최소 기능 및 최소3개 연결 task 범위 확정.
- 독립적인 사람 검수, 새 질문/댓글·다국어 평가, 응답 충실성/관점 이해에 대한 시스템 전체 연구 평가.

현재 완성한 것은 기존 수집/검수 결과에서 시작하는 로컬 관점 비교·질의 앱입니다. 완전 자동 영상→agent,
공개 웹서비스, 에이전트 간 토론 또는 전체 MAS/논문 검증 완료로 보고하지 않습니다.
