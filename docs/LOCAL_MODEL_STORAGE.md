# 로컬 모델 교체와 복구

2026-10-13 사용자 승인으로 Qwen4B와 OpenJev 가중치만 제거했다. 댓글·코드·실험 결과·평가 참조는 보존했고,
Qwen8B, 다국어 임베딩, DeBERTa 사실 검사 모델은 유지한다. 삭제한 모델의 과거 추론을 재실행하려면 가중치를 다시 받아야 한다.
이 페이지의 다운로드 명령은 **복구가 필요한 경우에만** 실행한다. 실행하면 확보한 공간을 다시 사용한다.

## 제거한 가중치

| 모델 | 제거한 파일 | 크기 | 고정 revision |
|---|---|---:|---|
| Unsloth Qwen3-4B-Instruct-2507 Q4_K_M | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2,497,281,120 bytes | `a06e946bb6b655725eafa393f4a9745d460374c9` |
| AlexWortega OpenJev | `qwen3.5-2b-nli-v5/model.safetensors` | 4,426,571,240 bytes | `a20448012c213128955ca0c693e7c943865cab77` |

합계6,923,852,360 bytes(약6.92GB/6.45GiB)다. 휴지통 사본은 만들지 않았다.
OpenJev의 해당 가중치 blob과 snapshot symlink만 제거했으며 약20MB의 tokenizer/config는 남겼다.
캐시 전체 삭제나 다른 프로그램의 모델 정리는 하지 않았다.

복구 원본:

- [4B 고정 파일](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/blob/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf)
- [OpenJev 고정 파일](https://huggingface.co/AlexWortega/openjev/blob/a20448012c213128955ca0c693e7c943865cab77/qwen3.5-2b-nli-v5/model.safetensors)

복구 시 SHA256을 확인한다.

```text
4B:      3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597
OpenJev: 9fd6a352fb00d6bdf848a84a1345f94244fc2d648408c01ee9d9109863e0c9d1
```

기존 Hugging Face CLI가 설치된 환경에서의 선택적 복구 예시다. OpenJev는 기존 cache layout을 재생성한다.

```bash
hf download unsloth/Qwen3-4B-Instruct-2507-GGUF Qwen3-4B-Instruct-2507-Q4_K_M.gguf --revision a06e946bb6b655725eafa393f4a9745d460374c9 --local-dir /home/taeng/.cache/commentscope-models
hf download AlexWortega/openjev qwen3.5-2b-nli-v5/model.safetensors --revision a20448012c213128955ca0c693e7c943865cab77
```

## 새 비교 대상

[공식 Qwen3-14B-GGUF](https://huggingface.co/Qwen/Qwen3-14B-GGUF)의 `Qwen3-14B-Q4_K_M.gguf` 하나만 선택했다.
기존8B와 같은 계열·같은 평가 요청을 유지하며, 모델 교체가 실제 오류를 줄이는지 비교하려는 목적이다.
최신 모델 전체에서 최선이라는 주장이나 정확도 향상 보장은 아니다.

```text
revision: 530227a7d994db8eca5ab5ced2fb692b614357fd
bytes:    9001752960
SHA256:   500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0
```

진행 상태는 [다음 세션 시작점](NEXT_SESSION.md)에 기록한다. `.partial`로 받은 뒤 전체 길이·SHA256이 일치해야 모델 파일로 승격한다.
모델 파일은 공개 Git에 포함하지 않는다. 다운로드는 추론 예산과 분리하며 추론은 기존8시간 ledger를 계속 사용한다.
RTX4060Laptop8GiB에서 전체 가중치를 GPU에 놓을 수 없으므로28layer offload/context4096을 사전 설정했다.
기존256token 추론과512token 전체 응답을 유지한다. 같은8통제 전부 통과 전에는 실제100관계를 실행하지 않는다.
속도는 GPU/CPU 배치가 다른 운영 비교이며 파라미터 수만의 인과 효과로 해석하지 않는다.

## 저장 공간의 실제 범위

삭제 직후 WSL 내부 사용량은 약27GiB에서21GiB로 줄었지만 Windows C: 여유는 약17GiB로 표시됐다.
WSL 가상 디스크는 C:에 있고, WSL의 표시상936GiB 여유를 실제 호스트 여유로 간주하지 않는다.
다운로드 전에는 Windows 잔여 공간이 새 파일 크기+5GiB를 초과하는지 확인했다.
가상 디스크 압축·WSL 종료·다른 사용자 파일 삭제는 수행하지 않았다.
