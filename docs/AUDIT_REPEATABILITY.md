# 동일 감사 요청의 새 추론 반복성

후보 선택 baseline을 고정하고 Qwen 판정기의 실행 간 변화를 분리 진단한다.
저장된 응답 재생 성공은 fresh inference의 결정성 증명이 아니다. 기본 Factory/판정기/agent 경로는 변경하지 않는다.

## 사전 고정 설계

기존 component-isolation과 extractive-candidates에서 겹치는 요청 **전부 10개**, 기존 positional-support의
의미 추가 오승인 2개를 포함한다. 정상/부정 기대는 개발용 assistant 판단이며 독립 gold가 아니다.
각 요청의 system/data/schema와 과거 결과 파일 hash를 계획에 묶는다. 프롬프트에 schema를 다시 붙이거나 수정하지 않는다.

프롬프트 캐시 켬/끔 × 같은 요청 연속(blocked)/전체 순환(interleaved), 각 3반복으로 **144회 실제 HTTP 추론**한다.
arm 순서는 on-blocked, on-interleaved, off-blocked, off-interleaved로 고정한다.
매 arm에 별도 서버를 띄우고 warmup 없이 시작한다. Qwen3-4B-Instruct-2507 Q4_K_M, llama.cpp b11541,
CUDA12.8, ngl99, context8192, parallel1, CPU6threads, seed407, temperature0, max_tokens900을 유지한다.
같은 요청이라도 응답 cache를 사용하지 않으며 format repair/의미 재시도는 없다.

실행기는 localhost8091이 사용 중이면 실패하며 기존 서버를 종료하지 않는다. 자신이 생성한 process만 finally에서 종료한다.
중단된 arm의 문맥 이력을 재현할 수 없으므로 부분 실행 재개는 금지한다. 기존 출력은 보존하고 새 run-dir에서 다시 계획한다.
각 호출의 원본 HTTP 응답/JSON/usage/시간, 요청 hash, 서버 명령/라이브러리 hash/종료 기록을 private 경로에 저장한다.

공식 b11541 문서는 프롬프트 캐시가 기본 활성화이며 KV 재사용과 batch 차이가 결과 변화에 영향을 줄 수 있다고 설명한다.
이는 비교 가설이지 이번 실패 원인의 확정이 아니다.
[고정 버전 공식 server 문서](https://github.com/ggml-org/llama.cpp/blob/b11541/tools/server/README.md).

## 측정·해석 경계

- raw 문자열 변화, 구조화된 JSON 변화, 각 속성 변화, host provisional state 변화를 따로 센다.
- source NLI/근거 NLI/lexical guard는 실행하지 않는다. 여기의 support는 전체 지지 승인이나 지지 수가 아니다.
- 부정 사례의 안정적 오승인도 별도 보고한다. 반복성이 좋아져도 의미 정확도가 좋아졌다고 결론 내리지 않는다.
- arm당 process 1개/3반복/고정 실행 순서라 일반 결정성, 처리 성능, 인과 효과를 확정하지 못한다.
- 모든 출력·댓글·계획은 Git 제외 및 기존 snapshot 만료 상속. agent0, 전체 corpus 확장0, 기본 승격0.

## 실행

기존 private 실험 checkpoint와 위 로컬 모델/런타임이 필요하다. Linux GPU 진단용이며 서버 경로는 코드에 명시돼 있다.
운영 endpoint나 Windows 모델 서버를 바꾸는 기능이 아니다. 코드 수정 후 새 plan을 만들고 추론 전에 hash를 고정한다.

```bash
python -m experiments.audit_repeatability_probe --run-dir runs/NEW-REPEATABILITY --phase plan --diagnostic-only
python -m experiments.audit_repeatability_probe --run-dir runs/NEW-REPEATABILITY --phase run --diagnostic-only
python -m experiments.audit_repeatability_probe --run-dir runs/NEW-REPEATABILITY --phase verify --diagnostic-only
```

verify는 서버를 시작하지 않고 저장된 144개 attempt의 순서/요청/결과 hash와 보고서 재계산을 검사한다.
새 모델 호출 0회를 fresh 반복성 결과로 잘못 세지 않는다. 검토 화면은 해당 run-dir의 overview.html이다.
