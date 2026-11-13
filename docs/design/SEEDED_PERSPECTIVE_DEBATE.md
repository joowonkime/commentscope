# 1출처 관점 Agent와 토론 논거 확장

TASK-026 / DEC-028 accepted direction / REQ-001·002·003·005·006·008·009·010.
2026-11-13 사용자가 댓글1개에서 관점을 만들고 토론 중 논거/외부자료로 발전시키는 방향을 제안하고 구현을 지시했다.
기존 r5의3출처/과거 실패/실청구는 보존한다. 새 제품 정책을 구형 r5 통과로 재태깅하지 않는다.

## 생성과 불변 경계

새 opt-in `comment-seeded-perspective-20261113-v1`은 검증된 자기 입장/필수조건의 원문출처1개 이상으로
관점 입력을 구성한다. source hash·정확한 인용·귀속·조건·core 유형/충실도·필수 사실과 dependency 검사는 유지한다.
지지 수는 확인된 실제 댓글 출처 수다. AI가 논거를 추가하거나 다른 Agent가 동의해도 늘지 않는다.
출처가 적다는 사실을 명시하고 모집단 대표성/빈도로 소개하지 않는다. 같은 입장의 여러 문구를 서로 다른 관점 수로 승인하지 않는다.
이유나 개인 경험을 새 댓글 증거처럼 만들어 최소 지지를 채우지 않는다. 실제 작성자의 이력/성격을 생성하지 않는다.

정책 없는 기존 bundle/Factory/Runtime은 기존3출처/추출 답변을 유지한다. 새 정책은 닫힌 상수이며
클라이언트가 최소출처/승인값을 변경하지 못한다. 새 bundle/compiled/turn에 모드를 결합한다.
기존 private1source draft의 비노출 계약을 우회하지 않는다. 새로운 제품 계약으로 명시적으로 컴파일한다.
전체 pipeline에서도 core/F4 적격 진입과 최종 Compiler에 같은 최소출처 정책을 전달한다.
새 제품 모드의 `major_fact_ids`는 core 자체와 선언된 core dependency closure의 사실이다.
선택적 개인 경험/이유의 사실은 확인되지 않으면 해당 이유를 제외하며, 독립적인 가치 입장을 막는
필수 전제로 승격하지 않는다. 이유의 dependency가 실패하면 그 이유도 제외한다. 명시된 필수 사실을
삭제해 입장을 구제하지 않으며, legacy의 모든 factual argument를 major로 요구하는 정책은 보존한다.

## 발언의 세 출처

- `original_comment`: 기존 검증된 허용 claim을 Host가 그대로 렌더링한다. 원댓글 ID/quote·출처 수를 유지한다.
- `ai_reasoning`: 관점에 기초해 새로 만든 가치 논거·조건부 추론이다. 원작성자의 발언/경험이나 검증된 실증 사실로 표시하지 않는다.
- `external_evidence`: 준비된 topic 근거팩의 exact passage로 뒷받침한 새로운 실증 주장이다.
  URL/문서/취득·만료·원문구간을 Host가 연결한다. 모델이 URL/인용을 직접 작성하지 않는다.

새 생성 문단은 Sol이 작성하고 Jev의 bounded choice 관측으로 유형·귀속·관점/조건·제시근거 일치를 확인한다.
Jev는 새 문단의 경험적 내용이 reasoning으로 숨겨지거나, 문헌의 표본/수량/인과/시점/조건을 바꾸면 보류한다.
이는 모델 관측이며 독립 정확도나 확정 사실 인증이 아니다. confidence 임계값을 임의 도입하지 않는다.
코드는 등록 ID/구간·응답 전체성·expiry·중복/출처·paragraph별 origin을 검사한다.
새 문단은 AI/외부 출처 수0으로 남고 immutable 댓글 bundle을 수정하지 않는다.
검증이 보류된 새 문단은 게시하지 않는다. 재생성/자동fallback/통과할 때까지 재질문하지 않는다.

전체 원문을 보존하며, 이번 구현은 기존 source graph 전역 보류를 임의로 풀지 않는다.
먼저 complete한 source/core의 저장 결과를 새 제품 정책으로 별도 무료 재조립한다.
새 명확한 입장에 대한 일반적1source 사례와 조건/필수 사실 실패는 합성 회귀로 확인한다.

## Runtime·제품 연결

새 세션은 source별 입장·허용 댓글·현재 질문·최근2턴과 선택한 peer 메시지를 받는다.
peer/history는 토론 대상이며 자기 댓글이나 외부 사실의 근거로 승격하지 않는다.
새 문단은 최대3개/각600자,댓글 인용 최대3개,질문1000자/세션6턴,기존room18턴을 유지한다.
작성과 typed 검증은 별도 비용으로 같은room/계정장부에 합산한다. 두 호출의 예약 여유를 사전에 확보한다.
두 번째 호출 실패/만료/전송 중단 시 첫 호출 비용도 보존한다. 검증기 없는 새 모드는 시작 전에 거절한다.

ProductApp의1:1·그룹응답 경로는 새 bundle에 새 세션을 선택한다. API/기록/화면에서 세 출처를 표시하고,
원문 버튼은 댓글로,외부자료 링크는 준비된 https문헌으로 연결한다. 사용자 의견·Reflect는 댓글 지지가 아니다.
기존 제품 API·old bundle·다른room/Agent 이력·중복요청·revision·비용/회복 규칙을 유지한다.
현재 외부근거는 등록된 shared topic pack이다. 매 턴의 새 웹검색까지 구현했다고 보고하지 않는다.

## 검증과 유료 실행

먼저 source1/2/3/zero,unknown policy,조건·귀속·필수 사실/오인용,원문변조,새문단의출처위조,
미등록/만료문헌,peer근거차용,유형위장/범위변경 veto,보류/이력분리/문단검증누락을 무료 검사한다.
기존3출처 회귀와 새1출처 제품 기대값을 별도로 둔다. 합성 통과를 실제 대화 유용성으로 보고하지 않는다.

Factory 필수검사·관련 product/Node검사·양OS CI 뒤 동결checkout에서 제한 실행한다.
기존 CNBC96 snapshot/후보/원문/증서·UKRI11구간을 재사용하고 원본 실행/금융기록을 변경하지 않는다.
새3시간/최대48물리요청(작성/검증포함)·같은누적150계정/owner로 실제 대화만 별도 등록한다.
모든 산출 profile와유사/중복 가능성을 보고하고,순서/표본을 결과에맞춰 바꾸지 않는다.
질문/대상/source·문서/코드·모델/provider·요청/가격·상한/기한을 먼저 고정한다.
완료/오류/보류·모든청구·새추론과외부근거의인용·관점별유용성을 함께 검토한다.
새 기능의 실제 성공·2유용관점·초행QA·전체MVP는 검증 결과에 따라 별도로 판정한다.

## 구현 위치와 현재 증거

- `agents/seed_policy.py`, `grounded_inputs.py`와 `factory/minimal_agents.py`,
  `minimal_pipeline.py`, `pipeline_stages.py`: 명시적 admission 전파/필수 사실 closure/legacy 보존.
- `agents/seeded_runtime.py`: Sol JSON 생성 → Jev 1회/최대13 Choice → 문단별 게시/보류.
  Host는 source/문헌 ID·인용·expiry·최소지지·dependency를 검사한다.
- `product/analysis.py`, `product/app.py`, `product/mvp.js`: 정책에 따른 세션 선택,
  두 호출 예약/합산·실패 비용 보존·기록/출처 표시. 기존 생성/검증 ledger를 통합 사용한다.
- `tools/seeded_perspective_trial.py`: 저장 증서의 무료 rebuild와 별도3시간/48요청 제품 QA.
  실제모델 호출을 새로 실행해야 검증되는 도구이며, CLI 존재만으로 유용성을 승인하지 않는다.

2026-11-13 무료 회귀29개와 Node 출처/UI검사9개가 통과했다. 첫 무료 재조립은 선택적 경험까지
기존 major fact로 묶어1개만 나왔다. 새 계약대로 core 필수사실과 선택적 경험을 구별한 재조립은
기존 CNBC96에서 profile4개/확인댓글1·2·1·1개다. 이들은 모두 찬성 계열이며3개의 넓은 입장이
겹친다. profile 수를 구별되는 관점 수로 보고하지 않는다. 원문 전역 보류와 미평가 후보는
그대로 남아 있다. 재조립의 새 추론/청구는0이다. 전체 Factory939개는289.307초에 통과했다.
이후 대화 이력/peer의 중복 citation inventory를 입력에서 제외한 최종 변경은 관련 무료 회귀와
전체 Factory·양OS CI로 다시 확인한다. 실제 대화는 후속 검증이다.

## 첫 실제 실행과 일반 계약 수정

PR106/b8bfc26: Factory939(305.054s), Ubuntu2742(465.038s), Windows2742(654.244s,기존POSIX12skip), Node9 통과 후 실행했다.
실제7호출/0.056386856달러에서 첫 profile의 입장·추론·문헌3턴을 저장했고, 네 번째 생성이
없는 보편 생산성 수치를 제공하지 않고 문헌의 한계를 설명했다. 생성 schema는 이를 허용했으나
Host는 `abstain`에 content가 있으면 오류로 처리했다. 원 실행은 실패로 보존한다.

보류는 요청한 답을 제공하지 못했다는 뜻이며, 검증된 **한계 설명**을 제공할 수 있다.
새 runtime v2는 `abstain`+`missing_evidence/out_of_scope`에서 인용/설명 문단을 허용하되
동일한 ID·문헌·유형·귀속·범위·Jev 검사를 거친다. 설명에 요청한 미확인 사실을 섞으면 보류한다.
설명이 있어도 status/answerability는 `abstain`으로 남고 answered 수에 포함하지 않는다.
answered/partial은 내용이 필요하며 schema와 Host의 모든 상태 조합을 일치시킨다.

첫 why 응답의 두 새 문단은 Jev가 mixed/reasoning으로 판정해 게시되지 않았다.
숫자 'paragraph0/1' 참조 혼동은 경쟁 설명 중 하나다. `PARAGRAPHS.P000`처럼 닫힌 주소로
각 질문의 대상을 명시한다. 판정 종류·veto·confidence 규칙을 완화하거나 실제 개선을 추정하지 않는다.

실패 profile 질문을 다시 결제하지 않는다. 후속은 기존 grant의 시작/종료·48물리요청 분모·
계정·owner·opening 차감을 그대로 이어받고, 아직 실행하지 않은 나머지 profile 질문과
미실행 그룹만 등록한다. 변경 코드의 Factory·양OS CI 뒤 실행한다. 기존7요청은 상한에서
계속 차감되며 새48요청/새3시간 권한을 만들지 않는다.

수정 전 무료3검사에서 상태 계약/설명형 보류/문단 주소 실패를 재현했다. 수정 후
상태18조합·origin/reference 조합·ProductApp 설명형 보류·continuation 분모 초기화 거부를
포함한 관련73검사와 Node10이 통과했다. 기존 실제 생성4개는 새 schema/Host 형태 검사만
0호출로 확인했으며 새 Jev 의미 판정이나 유용성 개선으로 계산하지 않았다.

최종 기능/제한 검증과 남은 품질 항목은 [실제 결과](SEEDED_PERSPECTIVE_RUNTIME_RESULT.md)에 있다. 초기 실패·후속43호출 합산·21게시턴을 구별하며 전체MVP/구별되는관점2개 승인은 하지 않았다.
