# 로컬 판정기 모델 교체 비교

원문 문장 후보 baseline과 positional-support의 감사 프롬프트·스키마·host projection을 고정하고,
기존 Qwen3-4B-Instruct-2507 Q4_K_M과 Qwen3-8B Q4_K_M 비추론 모드를 비교한다.
반복성 실험에서 드러난 정상 과잉 보류와 의미 추가 오승인을 함께 줄일 수 있는지 확인하는 개발 진단이다.

## 고정 입력과 평가 기준

기존 반복성12개, core-fidelity12개, evidence-unit16개를 모두 사용한다. 40평가 행/39고유 source-target이며
완전히 같은 요청 하나만 모델별로 공유한다. 기대 라벨은 모델 입력에 포함하지 않는다.
evidence-unit은 전체 원문을 target으로 써서 독립적인 주장인지 검사한다. 길이 축약이나 수동 후보 선택은 없다.
모든 사례는 기존 assistant 개발군이며 transfer라는 과거 명칭도 새 모델의 독립 holdout을 뜻하지 않는다.

각 모델을 새 서버에서 같은 정렬 순서로39회, 총78회 호출한다. repair/의미 재시도/다수결은 없다.
세 군을 합산한 정확도로 보고하지 않고 정상 보존, 부정 오승인/명시 거절/보류, 응답 오류를 나눈다.
NLI·lexical guard·근거 검사를 제외한 provisional audit이므로 전체 지지 승인 수가 아니다.

다음 full-pipeline 시험에 진입하려면 후보 모델이 모두 만족해야 한다.

- 계약/전송 오류0, 각 군에서 부정 오승인0.
- 각 군의 정상 보존 수가 같은 실행의 baseline 이상.
- 반복성 군의 정상10개 중9개 이상 보존.

이 기준을 만족해도 운영 승인이나 agent 생성은 하지 않는다. 기준 미달이면 해당 오류를 남기고 기본 모델을 유지한다.
출력을 보고 프롬프트/라벨/임계값을 수정해 같은 실험의 성공으로 바꾸지 않는다.

## 비교 모델과 실행 환경

Qwen3-8B 공식 GGUF의 Q4_K_M 파일을 사용한다. 공식 모델은 enable_thinking=False로 비추론 모드를 지원한다.
[GGUF 배포](https://huggingface.co/Qwen/Qwen3-8B-GGUF), [비추론 모드 설명](https://huggingface.co/Qwen/Qwen3-8B#enable_thinkingfalse).

- repository Qwen/Qwen3-8B-GGUF, revision `7c41481f57cb95916b40956ab2f0b139b296d974`.
- 파일 Qwen3-8B-Q4_K_M.gguf, 5,027,783,488bytes,
  SHA256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`.
- 기존4B 파일/revision/hash는 반복성 plan에서 상속한다. 모델 파일 다운로드 외에 댓글을 외부로 전송하지 않는다.
- 양쪽 llama.cpp b11541/CUDA12.8, context4096, GPU26layers/나머지 CPU, CPU6threads, parallel1.
  cache off, native Jinja template, enable_thinking=false, temperature0/seed407/max_tokens900.
- GPU8GB에서 다른 작업을 유지하기 위한 동일한 부분 offload다. 전체 GPU/8192 context였던 과거 baseline을 비교 결과로 재사용하지 않는다.
- 모델당900초를 매 호출 전 검사하며 한 진행 중 요청은 기존180초 timeout까지 걸릴 수 있다. 총39회/model를 넘지 않는다.
  부분 실행은 재개하지 않는다. 실패 기록을 보존하고 별도 계획으로 재실행한다.

새 모델은 크기뿐 아니라 학습 버전·native chat template도 다르므로 파라미터 수만의 인과 효과라고 주장하지 않는다.
양쪽 temperature0은 실험 통제를 위해 유지하며 모델 카드의 일반 샘플링 권장값과 다르다.
시간은 이 장비의 부분 offload 비용이지 GPU 전체 운용 성능이나 전체 서비스 시간은 아니다.

## 재현과 보존

실행기는 자신의 localhost8091 서버만 종료하고 기존 서버가 있으면 실패한다. 원본 요청과 응답, JSON,
판정 속성, 모델 파일 hash, 실행 명령·loaded library hash·정상 종료 여부를 private run-dir에 보존한다.
원문/결과/plan은 Git 제외, 기존 snapshot 만료 상속이다. 생성·선택·기본 Factory는 변경하지 않는다.

```bash
python -m experiments.audit_model_compare --run-dir runs/NEW-MODEL-COMPARE --phase plan --diagnostic-only
python -m experiments.audit_model_compare --run-dir runs/NEW-MODEL-COMPARE --phase run --diagnostic-only
python -m experiments.audit_model_compare --run-dir runs/NEW-MODEL-COMPARE --phase verify --diagnostic-only
```

기존 private 반복성 plan, 위 모델 파일과 Linux GPU 런타임이 필요하다. verify는 모델을 띄우지 않고
저장된78개 응답의 순서·hash·host 결정과 집계를 다시 검증한다. overview.html에서39요청을 전수 비교할 수 있다.
