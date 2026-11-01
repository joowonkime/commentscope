# OpenRouter Factory 개발 검사

로컬 LLM을 실행하지 않고 기존 Factory 요청을 OpenRouter에 전달한다.
`providers/openrouter.py`의 Client와 Runner는 기존 요청·응답·장부·체크포인트
형식을 사용하며, 원문·프롬프트·JSON schema를 유지한다. API 키는
`OPENROUTER_API_KEY` 환경변수에서만 읽고 계획이나 호출 파일에 저장하지 않는다.

현재 명령은 **기존 합성 요청 8개를 실행하는 개발 검사**다. G1~G4 실행기의
backend 옵션이나 전체 Factory 품질 승인을 제공하는 명령은 아니다.
관점 생성부터 Agent 생성·고정 질문까지의 연결은 모의 HTTP 응답으로 검사한다.
원격 모델을 전체 운영 경로로 채택하려면 해당 모델로 새 G1~G4 검증이 필요하다.

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
