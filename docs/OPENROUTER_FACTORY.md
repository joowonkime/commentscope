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

## 전체 G1 파이프라인

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
현재 이 명령은 G1만 지원하며 G2/G3/G4는 새 통과 증거와 후속 실행기 지원이 필요하다.

OpenRouter는 로컬 서버의 `/tokenize`를 제공하지 않으므로 전체 요청의 UTF-8 크기와
명시한 제공자 여유분으로 보수적인 context 경계를 계산한다. 이는 native 토큰 측정이
아니며 각 완료 응답의 실제 `prompt_tokens`가 그 경계 안인지도 확인한다.
기존 문장 임베딩과 NLI는 CPU의 별도 제한된 작업자로 실행하고 API 비용과 분리한다.
자원·주간 사용량 보호는 유지한다.

`completed.json`은 실행 완료와 사용 비용을 기록한다. 품질 판정에는 모든 원문·후보·
집계 지지·논거·Agent·질문의 검토가 필요하며 빈 검토 항목은 성공이 아니다.
실패 응답·개별 질문·중단 시점도 보존한다. 전체 의미 품질과 MVP 완료는 기존 기준을 따른다.

논거 검증은 원문 전체와 모든 논거·소유 관계·의존성을 전달한다. 요청 안에서는
후보·논거·소유 노드의 긴 저장 ID를 짧은 주소로 바꾸고, 응답을 원래 작업 ID에 다시
연결한다. 판정에는 해당 원문 근거나 의미가 바뀐 부분을 짧게 기록한다. 부정·불확실
판정을 긍정으로 바꾸지 않으며 Agent 보류 조건은 유지한다. 과거 검증 기록은 당시
요청 형식으로 계속 확인한다. 이 입력 개선 자체가 실제 의미 품질 통과 증거는 아니다.
