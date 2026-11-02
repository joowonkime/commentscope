# OpenRouter Factory 개발 검사

로컬 LLM을 실행하지 않고 기존 Factory 요청을 OpenRouter에 전달한다.
`providers/openrouter.py`의 Client와 Runner는 기존 요청·응답·장부·체크포인트
형식을 사용하며, 원문·프롬프트·JSON schema를 유지한다. API 키는
`OPENROUTER_API_KEY` 환경변수에서만 읽고 계획이나 호출 파일에 저장하지 않는다.

`openrouter_factory_probe`는 **기존 합성 요청 8개를 실행하는 개발 검사**다.
`openrouter_factory_pipeline`은 별도 계획으로 **전체 G1 관점→Agent→고정 질문**을
실행한다. 실행 완료는 의미 품질 승인이 아니며, 해당 원격 모델로 새 G1~G4 검증이 필요하다.

## 비용을 계산하고 실행하기

모델과 제공자 endpoint의 현재 context 길이·가격·`structured_outputs` 지원을
OpenRouter 모델 API에서 확인해 별도 deployment JSON에 기록한다.
다음은 2026-11-02에 실제 8건을 실행한 설정이다. 제공자 상태는 바뀔 수 있다.

```json
{
  "version": "openrouter-chat-completions-0.1",
  "model": "qwen/qwen3-30b-a3b-instruct-2507",
  "context": 262144,
  "call_seconds": 180,
  "provider": {
    "only": ["nebius/fp8"],
    "max_price": {"prompt": 0.1, "completion": 0.3, "request": 0}
  }
}
```

`max_price.prompt/completion`은 백만 토큰당 USD 상한이다.
제공자 자동 대체를 끄고 JSON schema 지원을 요구한다.
[가격 상한과 제공자 지정](https://openrouter.ai/docs/guides/routing/provider-selection),
[구조화 출력](https://openrouter.ai/docs/guides/features/structured-outputs)의 계약을 사용한다.
지원되지 않는 설정은 오류로 보존하며 자동 재시도하지 않는다.

```bash
python -m experiments.openrouter_factory_probe prepare \
  runs/openrouter-probe-example \
  --deployment-file runs/openrouter-assets/deployment.json \
  --maximum-cost-usd 0.25

python -m experiments.openrouter_factory_probe run runs/openrouter-probe-example
```

실행 전에 환경변수에 발급받은 키를 설정한다. `prepare`는 추론을 호출하지 않는다.
전체 8건의 입력을 각각 선언된 모델 context 전체로 잡아 보수적인 비용 상한을
계산하고, 명시한 실행 한도를 넘으면 거부한다. `context`는 실제 제공자 값을 사용한다.
위 설정의 상한은 $0.2118656이며 실제 8건 합계는 $0.0007901이었다.
API 키 잔여액도 실행 전에 확인하고, 비용 정보가 없는 응답은 추가 호출 전에 중단한다.
키 사용액 집계에는 지연이 있을 수 있어 각 응답의 `usage.cost`도 따로 보존한다.

여러 계획을 실행할 때는 공유 비용 정책 JSON을 `--spend-policy`로 함께 전달한다.

```json
{
  "account_id": "commentscope-development",
  "ledger": "runs/openrouter-account/spend.sqlite",
  "maximum_usd": "50",
  "opening_charge_usd": "0.0007901"
}
```

장부를 처음 만들 때 `opening_charge_usd`에 그 시점까지 이미 사용한 금액을 넣는다.
위 금액은 앞서 완료한8건의 예시다. 생성 후에는 총한도와 시작 사용액을 바꾸지 않는다.
각 새 계획에 같은 정책을 전달하면 실제 비용과 미확정 비용을 함께 집계한다.

```bash
python -m experiments.openrouter_factory_probe prepare \
  runs/openrouter-probe-with-shared-budget \
  --deployment-file runs/openrouter-assets/deployment.json \
  --maximum-cost-usd 0.25 \
  --spend-policy runs/openrouter-account/policy.json
```

`providers/openrouter_budget.py`는 요청 전에 금액을 예약하고 첫 응답의 비용으로
정산한다. 응답 유실·비용 누락은 예약을 유지하며 다음 유료 요청을 막는다.
상한보다 큰 실제 비용도 장부에 남긴다. 한도와 잔액은 내림, 비용은 올림해 계산한다.
명시한 로컬 NLI 등은 API 비용과 분리한다.

HTTP 오류는 상태 코드·숫자형 Retry-After·최대16KiB의 비밀값을 제거한 진단을
비공개 추론 장부에 보존한다. 키·Authorization 헤더·일반 예외 메시지는 기록하지 않으며,
호출자에게는 오류 종류만 전달한다. 이 기록을 근거로 재시도나 비용 대조를 판단한다.

응답을 끝내 복구할 수 없을 때는 원래 작업자가 종료됐는지와 장부·서비스 사용액을
검토한 근거를 별도 파일에 남길 수 있다. `resolve_conservatively`는 정확한 계획/요청과
근거 hash를 연결하고, **예약액 전체를 계속 차감하는 보수 처리만** 허용한다.
활성 요청이나 다른 요청은 해제할 수 없고 예약액을 환급하지 않는다.
`confirmed_usd`와 `conservative_usd`를 구분하며, 자동 재시도를 승인하는 기능은 아니다.

계획·요청·코드 hash·원래 실행 경로가 일치할 때만 같은 계획을 재개한다.
완료 응답은 재사용하고 미확정 호출은 장부 대조 없이 재전송하지 않는다.
로컬 Qwen의 기존 동결 실험·응답·장부는 원격 검사와 별도로 유지한다.

## 모델 없는 확인

```bash
python tools/check_factory_draft.py
```

여기에는 합성 HTTP 응답으로 원격 요청 형식, 키 미저장, 재시도 금지,
비용·잔여액 부족 거부, 중단/재개, 관점→Agent→대화 연결을 확인하는 검사가 포함된다.
이 명령은 네트워크·실제 API 키·유료 추론을 사용하지 않는다.
실제 8건의 JSON 응답 성공도 의미 품질 전체 통과를 뜻하지 않는다.

## 전체 Factory 파이프라인과 단계 승인

공유 비용 장부와 고정된 로컬 임베딩·NLI 자료가 필요하다. 로컬 Qwen 서버는 기동하지 않는다.
자료 JSON은 `classifier`, `model_files`, `documents`, `selections`를 포함한다.
기존의 고정 모델 이름·revision·가중치/실행 코드 hash와 문서·선택 구절을 사용하며,
과거의 생성 응답이나 검토 정답을 넣지 않는다. 모델 파일을 자동 다운로드하지 않는다.

```bash
python -m experiments.openrouter_factory_pipeline prepare \
  runs/openrouter-G1-example \
  --deployment-file runs/openrouter-assets/deployment.json \
  --materials-file runs/openrouter-assets/materials.json \
  --spend-policy runs/openrouter-account/policy.json \
  --maximum-cost-usd 0.25

python -m experiments.openrouter_factory_pipeline run runs/openrouter-G1-example

python -m experiments.minimal_factory_review prepare \
  runs/openrouter-G1-example-review --run runs/openrouter-G1-example
```

기존 합성12원문, literal 발견·raw 지지 판정·FULL_SCOPE 검증, 같은 사실 확인·
Agent 조립·고정 질문을 사용한다. 제공자 한 곳의 상태·지원 매개변수·context·가격을
확인하고, 코드·자료·계획 hash를 고정한다. 계획 파일을 수정해 예산이나 gate를 바꾸면 거부한다.
`--gate`의 기본값은 G1이다. G2는 고정 development24개, G3는 holdout96개,
G4는 전체 canonical999개를 사용하며 기존 snapshot과 sample manifest의 hash를 확인한다.
정답·의미 기준표는 모델 입력에 넣지 않는다. 원래 만료기한은 연장하지 않는다.

G2부터는 `--admission-file runs/.../admission.json`이 필요하다. 이 파일의 `gates`는
이전 단계마다 `run`, `packet`, `review`, `result` 경로를 지정한다. G2는 G1,
G3는 G1·G2, G4는 G1·G2·G3의 전수 검토 통과가 필요하다. 실행기는 평가기를 다시
실행하고 모델·전체 코드·출력·수용 기준·보조 모델·문서·공유 비용 정책이 같은지 확인한다.
pass 표시만 쓰거나 코드/모델이 달라진 이전 성공을 가져오면 큰 실행을 거부한다.
코드를 바꾸면 새 코드로 G1부터 다시 검증한다. 실행 완료와 품질 승인은 계속 별개다.

`--discovery-mode free`는 한 원문씩 명제를 직접 추출하는 선택 경로다. 원래 주소·
부모·동일성은 유지하고, 전송용 출처/조건 주소는 자기 원문의 고정 순서에 따라 0/1로 선택한 뒤 기존 명제
검증기로 개수·길이·중복·자기 원문 주소·추가 추출 규칙을 그대로 검사한다. 실제 요청과
응답의 결합은 정규화 기록과 따로 보존한다. 정규화용 내부 요청을 API에 보냈다고
표시하지 않는다. 보고·인용은 자체 정치적 지지로 승격하지 않으며, 명제 추출의 성공은
원문 지지나 Agent의 의미 품질 승인이 아니다. 새 경로는 같은 경로의 G1부터 검증한다.

free의 v3 전송은 인식 가능한 `only if`·`때만` 조건문을 요청 전에 원문 그대로 고정한다.
모델은 전체 문장의 발언 주체를 선택하며, 그 문장의 주소로 결론·조건을 따로 생성하면
요청 전체를 거부한다. 인용·질문·모호한 구문은 이 제한된 문법에서 자동 선택하지 않는다.
이 문법이나 모델 분류가 실제 지지를 승인하지 않는다. 원문별 검증과 검토는 계속 필요하다.
기존 v1 문자열 전송 기록은 원래 요청·응답 그대로 재검증하며 새 형식으로 고치지 않는다.
v2의 boolean 객체도 재검증할 수 있다. 긴 원문의 많은 선택 키는 제공자의 구조 제약을
초과할 수 있어, v3는 각 출처 위치당 정확히 한 비트인 짧은 문자열을 사용한다.
호스트는 길이·0/1 문자·자기 원문 주소·선택 개수를 검사하며, 잘못된 응답을 보정하지 않는다.

복잡한 분기와 중첩 배열은 제공자가 거부할 수 있다
([Gemini 구조화 출력 문서](https://ai.google.dev/gemini-api/docs/structured-output?hl=en)).
전송 구조를 단순하게 해도 호스트의 원래 검증을 줄이지 않는다. 후보 문장 비교에는
원문의 별도 이유를 붙이지 않으며, 검증 설명이 제한을 넘으면 잘라서 승인하지 않는다.

literal 후보 통합에서는 후보 문장 전체를 서로 비교한다. 원문의 별도 이유나 추가
요구를 비교 대상에 붙이지 않는다. 원문·출처는 계속 보존하며 후보의 조건·부정·시간을
자르지 않는다. 별도 문맥이 결합된 후보는 이 비교 형식으로 처리할 수 없다. 병합에는
기존 양방향 조건 검증과 모든 후보 사이의 동등성 확인이 필요하고, 지지는 최종 문장에
대해 원문에서 다시 판정한다. 과거 통합 기록은 원래 요청 형식으로 검증한다.

OpenRouter는 로컬 서버의 `/tokenize`를 제공하지 않으므로 전체 요청의 UTF-8 크기와
명시한 제공자 여유분으로 보수적인 context 경계를 계산한다. 이는 native 토큰 측정이
아니며 각 완료 응답의 실제 `prompt_tokens`가 그 경계 안인지도 확인한다.
기존 문장 임베딩과 NLI는 CPU의 별도 제한된 작업자로 실행하고 API 비용과 분리한다.
자원·주간 사용량 보호는 유지한다.

`completed.json`은 실행 완료와 사용 비용을 기록한다. 품질 판정에는 모든 원문·후보·
집계 지지·논거·Agent·질문의 검토가 필요하며 빈 검토 항목은 성공이 아니다.
실패 응답·개별 질문·중단 시점도 보존한다. 전체 의미 품질과 MVP 완료는 기존 기준을 따른다.

타임아웃 등으로 완료 응답이 없으면 추가 요청을 중단한다. CLI는 종료 코드 2와
`status: blocked`, 원인(`model_response_unavailable`, `pending_call`,
`budget_blocked`)을 반환한다. 예산 차단에는 한도와 미확정 과금 보호가 포함되며,
계정 잔액이 모두 소진됐다는 뜻으로 간주하지 않는다. 누락 응답은 단계·요청·작업 hash를 실패 기록에 남기며
완료 파일을 만들지 않는다. 같은 계획의 완료 응답은 재사용하고 실패 호출은 자동
재전송하지 않는다. 중단 후에는 원래 프로세스·checkpoint·장부를 확인해야 하며,
과금이 미확정인 호출을 완료·무료로 간주하거나 예약 비용을 자동 반환하지 않는다.
계획/입력 검증 실패는 `validation_failed`, 파일·통신 I/O 실패는 `io_unavailable`로
구분한다. 표준 출력에는 예외의 내부 메시지나 제공자 원문을 노출하지 않는다.
응답은 도착했지만 JSON/검증이 잘못된 경우에는 해당 작업의 실패를 보존하고 다른
독립 작업을 진행한다. 실패 기록은 품질 승인을 받았다는 뜻이 아니다.

웹 비교에서도 Agent 하나가 실패하면 전체 질문을 오류로 처리하고 그 질문 전의
모든 Agent 이력으로 복구한다. 실패 turn은 저장하지만 정상 답변으로 게시하지 않는다.
기존 성공 질문은 보존하며 같은 request_id를 다시 보내도 모델을 재호출하지 않는다.

논거 검증은 원문 전체와 모든 논거·소유 관계·의존성을 전달한다. 요청 안에서는
후보·논거·소유 노드의 긴 저장 ID를 짧은 주소로 바꾸고, 응답을 원래 작업 ID에 다시
연결한다. 판정에는 해당 원문 근거나 의미가 바뀐 부분을 짧게 기록한다. 부정·불확실
판정을 긍정으로 바꾸지 않으며 Agent 보류 조건은 유지한다. 과거 검증 기록은 당시
요청 형식으로 계속 확인한다. 이 입력 개선 자체가 실제 의미 품질 통과 증거는 아니다.

개별 논거 검증에는 그 논거의 고정된 부모 입장과 실제 연결 후보·역할을 따로 전달한다.
연결되지 않은 별도 요구에 핵심 입장과의 동등성을 요구하거나, 양보를 입장 재진술로
판정하지 않는다. 전체성 검증은 계속 모든 논거·후보·언어·의존성을 확인한다.

literal 관점의 논거 검증에서는 이전 종류·시간 판정을 입력에서 숨기고 원문을 다시
분류한 관측을 선언과 비교한다. 후보 자체의 종류·범위는 원문 전체와 섞지 않고 별도로
검증한다. 종류·시간·소유·범위가 틀리거나 불명확하면 보류하며 원래 선언을 고치지 않는다.
후보별 연결 거부는 해당 후보에 적용한다. 다른 후보의 유효한 연결까지 함께 막거나
실패한 연결을 승인으로 바꾸지 않는다. 모든 관측·실패·원문 지지 집계는 기록에 남는다.

새 free 경로는 소유 입장과 후보 입장의 비교를 별도 요청으로 분리한다. 이유·양보의
본문을 비교 대상으로 주지 않고 원문의 고정된 소유 입장을 사용하며, 원문 종류·역할·
귀속 관측과 후보 종류 관측은 각자의 거부권을 유지한다. 누락·부정 판정은 승인으로
대체하지 않는다. 각 요청·응답·소유 관계와 후보의 결합을 재검증한다.
소유 입장과 후보 문장의 현실·가상세계·가정 범위를 각각 관측하며, 세계가 다르거나
미확정이면 동등하다는 모델 판정이 긍정이어도 연결을 거부한다. 후보 문장에 없는
소설의 설정을 원문에서 가져와 동등하게 만들지 않는다.
새 관측의 설명은 닫힌 근거 범주에서 선택한다. 제공자가 문자열 길이 제약을
강제하지 않을 수 있으므로 기존 240자 호스트 제한은 유지하고 긴 응답을 자르지 않는다
([Gemini JSON Schema 지원](https://ai.google.dev/gemini-api/docs/structured-output#json-schema-support)).
이 범주는 다른 의미 검증이나 외부 사실 확인을 대신하지 않는다. 과거 관측은 당시
요청과 판정 그대로 재검증한다.
새 원문 관측은 각 작성자의 선언과 관련 후보만 묶어 기록한다. 모델이 받는 원문·
질문은 그대로 유지하며, 전체 선언의 hash를 논거마다 다시 계산하지 않는다.
다른 작성자나 후보의 관측을 현재 원문의 승인으로 가져올 수 없다.

지시어 치환 검증은 원래 지시 대상과 치환된 표현의 대상 종류도 각각 기록한다.
예를 들어 규칙과 그 규칙이 요구하는 활동은 다르다. 종류가 다르거나 불확실하면
모델의 동일 대상 판정이 긍정이어도 해당 치환을 보류하고 원문·다른 관점은 유지한다.
원문 지지 검증에도 선택한 근거나 후보에 추가된 내용을 짧게 기록한다. 설명 자체는
정답이나 지지 승인이 아니며 기존 출처·조건·양보·부정·불확실성 보호를 대체하지 않는다.
과거 형식의 기록은 재검증할 수 있고 새 형식은 설명과 판정의 hash도 함께 확인한다.
