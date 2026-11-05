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

새 실행은 HTTP-only256MB profile을 동결한다. 실제 역할별 영수증/고유 요청/비용과 부분 실패를 기록한다.
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
기존 실패와 장부·원문·모델 캐시는 보존했다. 디스크 기준을 낮추거나 다른 사용자 파일을 삭제해 우회하지 않는다.
오프라인 검사는 transport/선별/과금·기록 계약의 증거이며 G1 또는 전체 MVP 완료가 아니다.
