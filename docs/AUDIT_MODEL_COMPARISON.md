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

## 실행 결과 2026-10-13 KST

계획과 추론은10월12일23:51 KST에 시작했고13일에 완료했다. 추론 전 코드 `d8530ad`,
private 경로는 시작일 기준 `runs/audit-model-comparison-20261012/`을 유지한다.
plan SHA256 `edf1325d10d2df62d87357c8d1b6447745be00c5736ccb91e7038c42908b8db0`,
report SHA256 `7989d82b95671a78aa0c6abde1037c60df13e7e88123af81abab7da376980995`.

| 개발 평가 항목 | 같은 설정의4B | 8B 비추론 |
|---|---:|---:|
| 반복성군 정상 보존 | 7/10 | 10/10 |
| 반복성군 의미 추가 오승인 | 2/2 | 1/2 |
| 추가 충실성군 정상 보존 | 2/6 | 3/6 |
| 추가 충실성군 부정 오승인 | 0/6 | 0/6 |
| 자격군 정상 주장 보존 | 8/8 | 8/8 |
| 자격군 제외 대상 오승인 | 8/8 | 8/8 |
| 실제 호출·계약 오류 | 39회·0개 | 39회·0개 |
| 추론 시간 합 | 222.35초 | 429.63초 |

78회 실제 추론, repair/재시도0. 고유 요청39개 중 host state6개·구조화 출력14개가 달라졌다.
8B는 군별 정상 보존 비열화·반복성 정상9/10·오류0 기준을 통과했지만 **오승인0 기준 실패로 다음 통합시험에도 승격하지 않는다.**
추론 합651.98초이며 startup/hash/저장은 제외다. 부분 CPU offload와 공유 GPU 조건이므로 모델 자체의 일반 속도 차이로 해석하지 않는다.
두 모델 모두 응답 model 경로가 계획과 일치했고 cached_tokens 전부0, nonempty reasoning_content0,
loaded library hash 동일, 서버 종료코드0이다. 사전 기동 검사도 별도 서버에서 댓글 요청 없이 종료했다.

## 원문과 판정 속성 검토

assistant가39고유 source-target/78출력을 대조했고 근거 범위72개를 코드로 원문에 재결합했다.
근거 구간의 문자 일치는 의미 판정의 정확성이 아니다. 개발 라벨이나 실제 모델 출력은 사후 수정하지 않았다.

- 도서관 운영시간 권고, 열차 이용 증가, 재택근무 가능성, 안전검사 권고 재표현4개가 보류에서 support로 바뀌었다.
  나머지 정상 기대의 취업 의사2개와 could→may 재표현1개는 8B에서도 modality=changed로 거절했다.
- 활동의 생산성을 추가한 실제 target은 8B에서 not_supported가 됐지만 **modality만 changed**이고 presuppositions는 preserved였다.
  오승인 감소와 생산성 추가를 정확히 탐지했다는 주장을 구분한다. 영상 생성 방식을 추가한 다른 실제 target은 계속 오승인했다.
- 개인에서 사람 일반으로 범위를 넓힌 부정 사례도 8B는 modality=changed로 거절하면서 scope=preserved로 표시했다.
  최종 거절이 맞아도 각 속성이 충실한 이유 설명이라는 보장은 없다. 속성값을 논문의 검증된 설명으로 사용하지 않는다.
- 단순 동의/미해결 지시어/질문/도착 반응 등 제외8개를 두 모델 모두 substantive로 승인했다.
  source=target의 문자적 일치와 agent가 대표할 독립 주장 자격을 구분하지 못한 관찰이다.
  농담 등의 라벨은 assistant 개발 기준이며 이 표를 일반적 독립 정답률로 주장하지 않는다.
- 과거 전체GPU/context8192/cache-off 실행과 이번4B를 비교하면 안전검사 동일 원문1개가 uncertain→support다.
  배치/환경 변화의 어느 요소가 원인인지는 미확정이다. 같은 배치 설정의 새4B를 비교 기준으로 쓴 이유이며 과거 반복성 결과를 지우지 않는다.

저장 응답78개 replay는 새 모델 호출0회로 보고서와 일치했다. Python419/Node4 및 Linux·Windows CI 통과.
원문/모델 출력/가중치는 Git 제외, 설계·코드·집계만 공개한다. 추가 댓글 수집/유료 API/외부 댓글 전송0,
새 로컬 가중치 약5.03GB만 추가했다. 기본 Factory/main/생성기/선택기 불변, agent0/지지 ledger0.

## 다음 변경 경계

이번 설정의8B를 기본으로 교체하지 않는다. 정상 재표현 개선은 보존하되, 더 큰 모델을 연속 다운로드하는 실험은 여기서 멈춘다.
다음은 **SOURCE만 보는 독립 주장 자격 검사**와 **SOURCE→TARGET 충실성 검사**를 분리하는 제한된 대조다.
TARGET이 있는 합동 감사와 없는 자격 검사를 비교해 target 의존성 가설을 먼저 검증한다. 원인은 아직 확정하지 않는다.
성공할 때만 source digest/모델/정책별 자격 결과를 재사용해 pair마다 반복하는 비용을 줄이는 모듈로 연결한다.
원문은 선별 결과와 무관하게 registry에 남기고 자격 미확정을 지지로 승인하지 않는다.

기존 OpenJev typed routing도 자격 선별에 실패했으므로 단순 분리만으로 해결된다고 가정하지 않는다.
이번에 그 새 모듈이나 전체 pipeline을 구현·검증한 것은 아니다. 새로운 대조의 입력/기준/예산을 먼저 고정해야 한다.
