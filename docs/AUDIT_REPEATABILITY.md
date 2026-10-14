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

## 실행 결과 2026-10-12

추론 전 코드 `2f3d6af`, private `runs/audit-repeatability-20261012/`.
plan SHA256 `7fa33e772e9da2ee4084967c76025f870960758af69079839085c8de8888a825`,
report SHA256 `b5d358cb0819dfd47c33c55ed0d376c99601a7feee8a9dc87498d0e721e330ae`.

| 설정 | 실제 호출 | 변동 요청/12 | 정상 잠정 지지/30회 | 부정 오승인/6회 | 추론 시간 합 |
|---|---:|---:|---:|---:|---:|
| 캐시 on·연속 | 36 | 0 | 18 | 6 | 66.68초 |
| 캐시 on·교차 | 36 | 0 | 18 | 6 | 67.13초 |
| 캐시 off·연속 | 36 | 0 | 18 | 6 | 73.93초 |
| 캐시 off·교차 | 36 | 0 | 18 | 6 | 73.84초 |

각 요청은 4설정×3회=12번의 raw 문자열/구조화 JSON/host state가 모두 같았다. 오류0/repair0.
정상10개 중6개만 잠정 지지,4개는 항상 uncertain. 부정2개는 항상 support다.
반복 횟수를 독립 표본으로 세지 않는다. 이 수치는 전체 support pipeline 정확도도 아니다.
캐시 on 응답은 첫 요청을 제외한35회씩 토큰을 재사용했고, off72회는 cached_tokens 전부0이다.
서버4개 모두 GPU 라이브러리 로딩과 동일 library hash를 기록했고 종료코드0으로 종료했다.
추론시간 합281.58초는 서버 시작/파일 저장/모델 hash 등을 제외한다. 캐시 off가 여기서 약7초/36회 느렸지만 일반 성능 결론은 아니다.

assistant가12개 고유 요청을 대조했다. 열차 이용 증가의 정상 재표현, 재택근무 가능성의 정상 재표현,
안전검사 권고의 동일 원문 및 의무 표현에서 권고로의 함의가 conditions/time=unclear 때문에 보류됐다.
반대로 원문에 없는 영상 생성 방식, 활동의 생산성을 추가한 두 target은 속성이 전부 preserved로 오승인됐다.
독립 gold는 아니며 사후 수정 정답을 추론 입력으로 넣지 않았다.

과거 component-isolation의 안전검사 동일 원문은 support였지만 이후 실행 및 이번12회는 uncertain이다.
이번에는 그 변동을 재현하지 못했고 **캐시가 원인이라고 확정하거나 캐시 해제로 해결됐다고 주장할 근거가 없다.**
더 긴 선행 요청 이력/다른 runtime 상태 등은 통제하지 못했다. 기존 관측도 삭제하지 않는다.

저장144개 재생은 추가 모델 호출0회로 보고서와 일치했다. Python408/Node4 테스트 및 Linux·Windows CI 통과.
공개 저장소에는 코드/설계/집계만 저장하며 원문/응답은 제외했다. 기본 경로·후보 선택·agent0 유지.

## 다음 결정

캐시 해제·다수결 재호출·프롬프트 추가를 이 결과만으로 기본 해결책으로 채택하지 않는다.
후보 선택 baseline을 유지하고 **감사 모듈만 교체하는 고정 source-target 비교**가 다음 작업이다.
기존 정상 재표현/조건·범위 왜곡/원문 자체의 자격 오류를 함께 평가하고 모델·프롬프트·선택기를 동시에 바꾸지 않는다.
비교 모델/자원·실행 예산은 실행 전에 별도 고정해야 한다. 이번에 대체 모델 비교나 자동 MVP 완성을 수행한 것은 아니다.
