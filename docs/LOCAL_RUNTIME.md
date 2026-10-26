# 로컬 모델 실행 모듈

클러스터링·Agent 생성은 같은 처리 코드를 사용하고, 모델 파일과 실행 설정은 별도 deployment JSON으로 전달한다. 엔진은 llama.cpp이며 채팅 템플릿·JSON schema 호환은 실제 로딩 후 확인한다. 현재 공통 실행기·Factory 연결과 합성 검사를 구현했고, 작은 모델의 실제 자원·품질 검증과 999개 실행은 미완료다.

| 코드 | 책임 |
| --- | --- |
| `providers/llama_runtime.py` | 모델·서버 SHA/revision, 기동 설정, loopback 호출, 실제 템플릿 토큰 측정, 서버 소유·종료 |
| `providers/runtime_runner.py` | 응답을 기존 Factory 형식으로 변환하고 기존 장부에 기록 |
| `providers/checkpoint_calls.py` | 같은 계획의 완료 응답 재사용, 미확정 호출 재전송 방지 |
| `providers/exclusive_models.py` | LLM과 embedding/NLI의 동시 상주 방지 |
| `experiments/minimal_factory_pipeline.py` | snapshot부터 Agent/질문까지 연결하고 규모 확장 조건 검사 |
| `experiments/minimal_factory_review.py` | 동결된 출력 전체를 원문과 대조한 사후 검토로 r5 평가 |

Factory의 `runner.call`, `embed`, `inspect`, `fact_check` 경계는 유지한다. 모델별 처리 코드를 복사하지 않는다. 새 모델·설정·코드는 새 계획 hash를 가지므로 이전 답변을 새 추론으로 재사용하지 않는다.

## 별도 소형 모델 설정

deployment에는 `version`, `model`, `server`, `runtime`, `startup`, `resource_policy`를 기록한다. 모델은 이름·repository·고정 revision·절대 경로·SHA256, 서버는 경로·SHA256·라이브러리 경로를 갖는다. 사용자 경로·가중치·실제 댓글·장부는 공개하지 않는다.

- context 8192, thinking off, 병렬 1개, 기본 스레드 2개
- batch 128/microbatch 64, q8 KV, GPU offload, direct I/O, prompt/RAM cache 비활성
- 시작 전 RAM 여유 4096MiB·commit 여유 4GiB·GPU 여유 3072MiB, 가중치 최대 3GiB
- 실행 중 기존 보호선 유지: RAM 여유 1536MiB·commit 여유 1GiB·호스트 디스크 여유 6GiB
- 유한 기동·호출 timeout, 전송 재시도 0, 자신이 시작한 서버만 정리

`runtime.cuda_graphs`는 선택적 boolean이며 생략하면 기존 그래프 캡처를 사용한다. `false`이면 실행기 자식 프로세스에만 `GGML_CUDA_DISABLE_GRAPHS=1`을 적용한다. 상속된 같은 환경변수는 덮어쓰며, 실제 설정을 `runtime-environment.json`에 남긴다. 메모리 사용과 속도에 영향을 주는 실행 설정이므로 변경 시 새 계획에서 자원·품질 검증을 진행한다.

이것은 측정 전 시작 프로필이며 성능 보장이 아니다. 기존 8B 시작 기준은 수정하지 않는다. 가중치 크기는 KV·버퍼를 포함한 총 메모리와 다르다. WSL 내부 여유와 Windows 호스트 디스크 여유도 별도다. 실제 모델이 자원 보호와 품질 기준을 모두 통과해야 채택한다.

## 단계별 실행

실제 연구 입력·고정 평가 자료·기존 장부·모델·개인 환경의 usage guard가 준비된 환경에서 실행한다. clone만으로 비공개 자료가 생기지는 않는다.

```bash
python -m experiments.minimal_factory_pipeline prepare runs/new-model-g1 \
  --gate G1 --discovery-mode literal --membership-mode raw \
  --deployment-file runs/new-model/deployment.json
python -m experiments.minimal_factory_pipeline run runs/new-model-g1
```

`literal`은 원문 구문 노드에서 입장을 선택하며 모델이 새 입장 문장을 작성하지 않는다. 이유와 양보는 작성자의 원문 그래프에 별도로 보존하고, 필수 조건은 입장에 유지한다. 대명사 치환은 원문·부모의 정확한 구간을 증거로 남긴다. 모델이 고른 구간이나 역할 자체가 의미 검증을 통과했다는 뜻은 아니다.

새 raw 검증 계약은 이유·양보가 섞인 복합 후보를 지지 집계 전에 보류한다. 입장만 동의한 작성자에게 후보의 추가 이유까지 부여하지 않기 위한 경계다. 작성자가 직접 제시한 이유의 귀속은 별도로 유지하며, 경험적 주장은 기존 사실 검증을 계속 거친다. 과거 검증 계약과 실행 기록은 그대로 재현할 수 있다.

실행 완료는 품질 통과가 아니다. `minimal_factory_review prepare`로 packet을 만들고 전체 검토를 채운 뒤 `evaluate`로 평가한다. 고정 사실40건·Agent별3질문 기준을 유지하며 검토 라벨은 모델 입력에 넣지 않는다. 개발 중 합성 G1 실행은 12개 입력 처리를 완료했으나 잘못 집계된 지지 3건과 Agent 0개로 실패했다. 위 경로의 합성 검사와 제한된 모델 진단만으로 이 품질 실패가 해결됐다고 보고하지 않는다.

G1·자원 검증 후 G2(24개/의미19개 중 후보 보존12 이상), G3(96개/의미74개 중45 이상)를 진행한다. G4 999개에는 G1·G2·G3 통과가 모두 필요하다. 다음 단계의 `--admission-file`에 검토 경로를 제공한다.

```json
{"gates": {"G1": {
  "run": "runs/new-model-g1",
  "packet": "runs/new-model-g1-review/packet.json",
  "review": "runs/new-model-g1-review/review.json",
  "result": "runs/new-model-g1-review/result.json"
}}}
```

G3에는 G1·G2, G4에는 G1·G2·G3 항목을 포함한다. 자동 출력·검토·평가 hash와 동일 모델·코드·알고리즘을 확인하고 기존 평가기로 통과를 재계산한다. 코드/모델 변경 시 다시 검증한다. 소규모 통과는 전체 품질 보장이 아니므로 G4에서도 453/755 활용·집계 지지 전수 유효·Agent/사실/실행 기준을 검사한다.

개인 Goal의 주간 잔여40% 이하 즉시 중단·기록 규칙도 유지한다. 아래 합성 검사는 모델을 사용하지 않는다.

```bash
python -m unittest discover -s tests -p 'test_portable*.py'
python tools/check_factory_draft.py
```
