# GPT-6.1 Sol 검증과 외부 임베딩 실행

TASK-005/006, REQ-001/002/003/008/010, DEC-007. 사용자 지시: 검증의 정확성과 로컬 RAM 문제를 줄이기 위해
`gpt-6.1-sol`을 사용한다. 모델 선택을 구현하되 성능 합격을 미리 주장하지 않는다.

## 현재 경계와 선택

기존 생성/대화는 GPT-5.2, 의미 관측은 GPT-5.2/Jev, 검색은 로컬 MiniLM, 사실 검사는 로컬 DeBERTa NLI였다.
새 opt-in 실행에서는 GEN-1/GEN-2/GEN-3는 기존 GPT-5.2, J1/J2/J3/J4/F0는
OpenRouter `openai/gpt-6.1-sol`/OpenAI standard, R0는 `openai/text-embedding-3-small`/OpenAI로 고정한다.
Jev/로컬 NLI 판정을 새 결과에 섞지 않는다. 로컬 코드의 ID/span/DAG/예산/조립/벡터 산술은 유지한다.
이 실행 경로는 torch/transformers·모델 파일·GPU를 로드하거나 요구하지 않는다. 과거 경로와 산출물은 보존한다.

현재 공식 model/API와 provider metadata를 확인했다. Sol은1050000 context, standard 입력/출력$2/$10 per1M이다.
272k 초과 tier와 cache-write를 포함한 보수 상한은 입력$5/출력$15 per1M으로 고정한다.
reasoning low, host headroom1024, temperature 미전송, strict JSON, 자동 fallback/재시도0이다.
임베딩은8192 context/input,1536 dimensions, 입력$0.02/1M·출력0이다. 판매가격은 실행 직전 다시 대조한다.

## 역할별 계약

기존 source/후보/논거/owner/core 범위·귀속·조건/의존 guard를 유지한다. 각 stage family를 명시적인
generation/verification/interaction 역할로 배정하고 등록되지 않은 stage를 dispatch 전에 거부한다.
J4-L/K는 같은 blind source inventory/실제 core/고정 선택지를 JSON enum으로 받아 host에서 비교한다.
확률을 만들거나 Jev 응답으로 위장하지 않는다. source/core 변경·관측 누락·declared graph 불일치는 계속 보류한다.
60% 선별 활용·verified_subset 정책은 유지하며 실패 source 전체를 보류한다. 공통필수사실을 지워 구제하지 않는다.

F0는 기존의 동결 문서·정확한 passage/claim/scope로 supported/refuted/conflicting/insufficient와 근거 ID를 받는다.
모델의 기억/검색이나 댓글 수를 사실 근거로 삼지 않는다. API model/provider/deployment/adapter identity를
별도 remote identity로 저장하며 로컬 weights hash나 NLI logits를 조작하지 않는다. 한국어 원문도 그대로 보존한다.
기존40건의 기대값을 바꾸지 않고 새 모델로 한 번 측정한다. 과거 NLI9/10 결과를 새 모델의 성적으로 승계하지 않는다.

R0는 전체 원문을 UTF8 기준6000byte 이하의 연속 구간으로 나눠 남김없이 전송한다. 최대32구간/64kB로 묶고
응답 index·개수·모델·1536차원·유한수·nonzero를 확인한다. 길이 가중 평균 후 정규화해 원래 ID에 복원한다.
검색 벡터는 지지/동치/사실 승인이 아니다. snapshot/모델/전처리/전체 요청과 원래 구간을 결합한다.

## 비용·기한·복구

기존 총$50·기존 확정/보수 차감·원래scope$8 money owner와 종료시각을 유지한다. 새 model role authorization은
원래 돈의 소유자를 참조하며 원본 cycle을 수정하거나 돈을 초기화하지 않는다. 첫 검증 subcap$0.50을 둔다.

새 chat budget만 opt-in `wire-bound-input-0.1` 예약을 쓴다. context를 허위로 줄이지 않는다.
도구/플러그인/이미지가 없는 system+user2메시지와 strict schema를 실제 wire로 직렬화해 UTF8 byte 상한을 계산한다.
기존8192 framing margin·최대출력(추론 포함)·모든 가격 class/tier의 상한을 합해 요청 전에 예약한다.
전체 요청이 context에 맞는지 확인하고 실제 usage가 bound를 초과하면 정산 후 다음 dispatch를 막는다.
기존 최대context 예약 경로·보수 차감은 바꾸지 않는다. unknown chat 비용은 계속 전체 예약을 잡고 중단한다.

embedding은8192×실제 batch item 수의 전체 입력 상한으로 예약한다. 알려진 usage.cost는 그대로 정산한다.
공식 embedding 응답이 cost를 주지 않고 유효한 model/index/vector/token usage만 줄 경우, 명시한 정책으로
예약 **전체액을 보수 차감**하고 원본/가격/요청/응답 hash를 감사 증거로 남긴다. 실제 청구액으로 표시하지 않는다.
식별/usage/범위가 불명확하면 unknown 상태를 유지한다. 새 요청·재개로 예약/과거 비용을 없애지 않는다.

새 v2 실행은 별도 `http_api` profile을 동결한다. 최소 여유 RAM256MB·commit1GiB,
디스크 floor1GiB와 다음 요청 기록용64MiB를 검사한다. 기존 local/mixed1536MB·디스크6GiB와
HTTP-only v1의 디스크6GiB는 과거 plan의 의미를 유지한다. 실제 역할별 영수증/고유 요청/비용과 부분 실패를 기록한다.
완료 checkpoint만 같은 plan에서 재사용한다. 단계 사이에는 fresh source/판정/응답을 사용하고 이전 bundle을 섞지 않는다.
G1→실제24→별도96과 전체Agent/원문 검토를 유지한다. 확장 전 새 실제 비용을 확인한다.

## 정상·부정 검증

- 정상: 제공 문서가 뒷받침하는 영어/한국어 사실·빈 전제가 타당한 가치 이유·전체 원문 chunk 복원.
- 부정: 다른 날짜/수량/주체·근거 ID 발명·부모/인용 차용·전제 누락/오연결·잘못된 역할/model/provider.
- 비용: wire/schema/추론/output 전부 포함, NaN/중복 embedding index·usage 누락·가격 tier 상승·미정산 재호출 차단.
- 기존 로컬 identity/영수증을 remote로 이름만 바꿔 승인하지 않는다. 코드/오프라인/제한 실행/전체 품질을 구별한다.

참조: [OpenAI Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[OpenAI embeddings](https://developers.openai.com/api/docs/models/text-embedding-3-small),
[OpenRouter embedding API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request).

## 구현과 현재 증거

- 실행 진입점: `experiments.remote_factory_pipeline`. `authorize`는 원래 authorization의 money owner·종료시각을
  참조하는 역할 변경 기록을 작성한다. `prepare`는 모델·가격·자료·코드·장부·subcap을 동결하며 `run`만 추론한다.
- `providers.remote_verification`은 명시적 stage registry, wire 예약, 외부 임베딩의 분할·검증·정산을 담당한다.
  등록되지 않은 stage는 유료 dispatch 전에 거부한다. 출력 용량과 reasoning은 기존 allocator를 한 번만 거친다.
- `factory.remote_fact_records`는 실제 API 원본과 논리 출력의 일치, claim/scope/문서/기한/모델 결합을 검사한다.
  기존 local/NLI record는 별도 validator를 유지한다. 새 graph-chat protocol은 Jev 확률·기록을 받지 않는다.
- `minimal_factory_review`는 이 실행의 새40건 성적을 재생한다. 기존 NLI benchmark를 새 모델의 증거로 사용하지 않는다.
  G2/G3는 같은 역할·코드·자료를 쓴 이전 gate의 전체 원문 검토를 다시 계산한 뒤에만 준비할 수 있다.

2026-11-06 첫 실제 시작은 RAM2479MB로 HTTP-only256MB 기준을 통과했지만 C드라이브216326144byte로
기존6GiB 디스크 보호 기준에서 API 전 중단했다. 새 유료 호출0건·비용$0이며 새 모델 정확성은 아직 미측정이다.
이는 당시 v1 실행의 결과다. 기존 실패와 장부·원문·모델 캐시는 보존했다.
오프라인 검사는 transport/선별/과금·기록 계약의 증거이며 G1 또는 전체 MVP 완료가 아니다.

## API 전용 저장 공간 — v2

사용자가 지적한 6GiB는 API 요구량이 아니라 이전 공통 profile의 값이었다. 모델을 저장하지 않는 경로에
새 버전의 정책을 적용하며 원래 plan은 수정하지 않는다. 모델·prompt·원문·의미 기준·비용·기한은 그대로다.

- 최소 host 디스크 여유1GiB를 OS와 완료/정산 기록용으로 남긴다. 실제 실행 volume도 확인한다.
- 한 번의 worker 응답은 기존2,000,000byte 상한이다. SQLite 원본, request/result, checkpoint,
  원본/논리 출력의 중복과 JSON pretty-print를 고려해 다음 호출 전에64MiB 추가 여유를 요구한다.
  이는 저장량의 실측값이 아닌 보수 여유이며 큰 합성 영수증을 실제 저장해 회귀 검사한다.
- private 실행 디렉터리의 모든 파일 크기를 합산한다. plan에 고정한1GiB 실행 기록 한도에서
  다음 요청 여유를 남길 수 없으면 **유료 dispatch/intent 전에 중단**한다. 다음 단계는 새 실행이므로 별도 기록한다.
- 최종 aggregate/Agent/output 저장은 실제 UTF8 JSON 크기를 계산해 디스크와 실행 기록 한도를 먼저 검사한다.
  이미 받은 영수증·비용·완료 checkpoint는 보존하고 초과 시 다음 호출을 중단한다. 자동 삭제·재호출은 없다.
- 감시는 계속10초마다 실행하며 부족 시 현재 요청의 정산과 checkpoint를 마친 뒤 새 요청을 차단한다.
  commit/관측 실패·저장 실패 기준은 유지한다.1GiB 정책을 local 모델 실행에 넘기면 거부한다.

정상: RAM512MB·디스크2GiB의 API 실행은 통과하고 로컬 실행은 계속 거부한다.
부정: 디스크 floor/다음 기록 여유 부족·실행 기록 초과·관측 실패는 호출 전 차단한다.
과거6GiB plan은 새 정책으로 이름만 바꾸어 재개하지 않고 새 plan·코드·정책으로 동결한다.

실제 첫 임베딩 응답은 OpenAI provider와1536차원/2입력/28token이 맞았으나 model이 provider 표기
`text-embedding-3-small`이어서 v1 adapter의 vendor-prefixed ID 검사에서 중단했다. 비용$0.00000056은
응답 검증 전에 정상 정산됐다. embedding deployment0.2는 두 정확한 ID(`openai/text-embedding-3-small`,
`text-embedding-3-small`)만 허용한다. 다른 모델/반환된 다른 provider·차원/index/usage 검사는 유지한다.
이전 실패와 비용은 보존하며 새 역할 binding/plan의 첫$0.50 한도에서 이미 쓴 금액을 뺀다.

오프라인 저장 스트레스:1,900,000byte payload를 worker → SQLite → request/result → checkpoint → aggregate로 저장한
합계는19,042,633byte(약18.2MiB)였다. 요청당64MiB 여유 안에 들어왔으며 실제 네트워크/과금은0건이다.

## 명시적 재개와 만료

사용자가 중단 뒤 `이어 진행`을 명시하면 새 버전의 role authorization에 재개 요청과 별도 실행 window를 기록한다.
원본 money owner 파일/hash·원래 종료시각·상한$8·기존 모든 차감은 유지한다. 새 window는 원래 한 window의
길이 이하(최대7시간)이며 요청 직전에도 남은 시간을 검사한다. 원본 파일이나 과거 plan의 시간을 덮어쓰지 않는다.
재개 요청이 없거나 window가 누락/변조/초과하면 만료된 실행은 계속 거부한다. 새 파일/hash가 새 예산을 만들지 않는다.

첫$0.50 검증 한도는 이전 실제 임베딩$0.00000056을 차감한$0.49999944로 이어간다. 원래 공유$50와
money owner의 누적 상한을 모두 유지한다. 새 코드/authorization/plan으로 동결하며 다른 실행의 응답은 삽입하지 않는다.

댓글 snapshot·근거 문서의 기한은 실행 window와 별개다.2026-11-09 재개 시 실제 댓글 snapshot은
2026-11-08에 만료됐으므로 G2/G3에 그대로 쓰지 않는다. 유효한 고정fact40(11월11일까지)과 합성G1을 먼저 실행한다.
실제 댓글의 새 snapshot/표본/분모/참조 검토는 별도 기록하며 기존999/755 평가의 성공으로 바꾸지 않는다.

## 내용이 동일한 고정 표본의 재검증

전체999 모집단을 새 표본으로 바꾸는 결정과, 이미 고정한24/96 문항을 현재 조회 자료로 재검증하는 작업을 구별한다.
기존1,000ID를 공식 API로 다시 조회한998개 중, 고정24·96 표본과 그 부모·영상 문맥 packet은120/120 동일했다.
조회 불가2개는 이 고정 표본 밖이다. 새 snapshot의 실제 raw/canonical 개수는998/997로 기록하며999로 표시하지 않는다.

`--scope-refresh-file`은 G2/G3에만 사용할 수 있다. binding은 원래 snapshot SHA, 새 snapshot SHA,
실제 조회 receipt 파일 SHA들을 가진다. 원래 고정 표본을 바꾸지 않으며 모든 선택 source packet을
원래 원문·부모·영상 문맥과 완전히 비교한다. 새 snapshot은 유효해야 하고, 모든 원문/부모/수량/게시일은
명시적으로 조회한 receipt와 일치해야 한다. 요청 ID 전체가 원래 ID와 같고 미조회된 문항을 채워 넣지 않는다.
조회 시점·30일 이내 만료·영상 metadata도 검사한다. 원래 snapshot의 TTL을 수정하지 않는다.

고정24/19·96/74와 기존r5 기준은 유지한다. 범위 안의 누락/변경, 부모 문맥 변경, 오래된/변조된 receipt는 거부한다.
scope와 새 자료/receipt는 plan의 입력 hash에 고정한다. G3는 G2와 같은 refresh binding을 써야 한다.
이 경로는 G4의999/755 전체 평가나 새 의미 분모의 승인이 아니다. 이전 model 응답도 재사용하지 않는다.

## 2026-11-09 첫 원격 실행의 관측

새 Sol 고정40건은 지원10/10·비지원 오승인0/30, 정확한 세부 라벨39/40이었다.
41요청 비용$0.155939560이며 전체 Factory 합격이 아닌 사실 부품 증거다.
첫 G1은253요청/$0.530922280으로 자동2Agent·각3유효출처·6실제응답·binding error0을 완료했다.
전수 원문 검토에서16개 요건 중15개를 만족했지만 mandatory 지지2개가 검색에서 누락돼 정식 합격은 실패다.
리뷰는 assistant의 전체 출력 대조이며 독립 사람 gold가 아니다. 실패 원본과 비용을 보존한다.

이후 동치 표현 검색 수정은 새 G1에 적용해 검증한다. 기존 결과를 새 코드의 합격으로 승계하지 않는다.
사실 부품은 그 부품의6개 코드·모델·자료 SHA가 모두 일치할 때만 호환 증거로 재사용하며,
관점/지지/논거/Agent/runtime 모델 응답은 새 실행에서 다시 생성한다.
