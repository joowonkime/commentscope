# 원문 위치 검사와 추출 전 검색 병목

주제 문자열을 모델이 작성하지 못하도록 원문 위치 선택으로 바꾸고, 저장된 근거만 보는 검사를 추가했습니다.
**문자 보존은 구현했지만 의미 품질 개선은 입증하지 못해 기본 경로에 채택하지 않습니다.**
같은 실제29댓글에서 기존 정상 연결3쌍은 원문 검색으로 모두 노출됐지만 추출 후에는 상대 source가 소실됐습니다.
이번 대조군의 병목은 검색 순위보다 앞선 주장 선택과 필수 topic 생성에 있습니다.

## 구현과 비교 범위

`evidence_positions.py`는 기존 selector의 sentence-ID 범위를 유지하고 topic도 첫/끝 token ID로 선택하게 합니다.
host가 원문 offset에서 topic을 복사하며, 반복된 표현도 선택한 occurrence를 보존합니다.
statement/topic/source digest/focus/context를 재결합해 검증합니다. 모델이 새 단어를 추가할 출력 필드는 없습니다.

topic120자, statement450자, 최종 evidence500자 상한은 그대로입니다. 원문 일부를 임의 절단하지 않습니다.
먼저 위치 선택 결과인 `position_units`를 보존하고, FINAL_EVIDENCE/FOCUS/TOPIC만 보는 검사 후 `units`를 만듭니다.
전체 원문이나 이전 판정은 final 모델 입력이 아닙니다. 이 입력 격리는 코드로 보장하지만 지시 대상 완결성은 모델 판단입니다.

실행 전 코드 `ed9b98e`와45입력을 고정했습니다.

- 합성16개, 기존 실제 개발12개, 기존 확인12개는 **이전 선택 범위를 그대로 사용**합니다.
- 기존 실제 정상 cross-source3쌍의 추가 endpoint5개만 새 선택을 실행했습니다.
- 이전 실제 확인 표본은 이제 회귀 자료입니다. 작은 assistant 개발 평가이며 독립 gold/미사용 corpus가 아닙니다.
- topic prompt/schema/표현 변경을 함께 비교하므로 위치 표현 하나만의 순수 효과로 주장하지 않습니다.
- 최종 검사 효과는 같은 position units에서 분리하고, 이전 확인12units도 변경 전 evidence 그대로 재검사했습니다.

기본 Factory0.2, 기존 evidence-units0.1, OpenJev 결과는 변경하지 않았습니다. 새 수집/유료 API/댓글 외부 전송은 없습니다.

## 실제 실행 결과

Qwen3-4B Q4_K_M으로133개 고유 요청을 실행했습니다. 모델·temperature0·seed407은 유지했습니다.
API transport 오류는 없었지만 topic 위치 계약 오류가9개 후보/5개 source에서 남았습니다.

| 입력 | 기존 units | 위치 선택 후 | 최종 검사 후 |
| --- | --- | --- | --- |
| 실제 개발12댓글 | 13 | 12 | 11 |
| 기존 확인12댓글 | 12 | 12 | 8 |
| 추가 endpoint5댓글 | 비교 없음 | 7 | 6 |

개수는 품질 점수가 아닙니다. 고정 합성16개는 정상7/8·제외7/8로 이전과 동일했습니다.
정상1개는 이미 selector가 빈 범위를 반환해 이번 하류 수정만으로 복구할 수 없었습니다.
지시 대상 없는 확언1개는 topic과 final 검사 모두 통과했습니다. 정상8/8·제외8/8의 사전 조건은 실패했습니다.

위치 계약 오류9개는 모두 topic 범위가120자를 넘었습니다. 잘못된 ID나 새 문자열 추가는 아니었습니다.
모델이 짧은 주제 대신 긴 발언 구간을 선택했으며1회 형식 복구도 실패했습니다. 이 오류를 올바른 의미 제외로 세지 않습니다.
자유 텍스트 복사 문제를 막아도 **짧은 topic을 필수 통과 조건으로 삼는 구조는 유효한 주장까지 잃을 수 있습니다.**

### 최종 근거 검사의 효과

기존 확인12댓글에서 최종 통과한8units를 전부 사후 검토했습니다.

| 사후 분류 | 개수 |
| --- | --- |
| 원문에 명시된 주장 | 5 |
| 지시 대상이 자기 댓글에 없음 | 2 |
| 저장 evidence에 필요한 자기 댓글 문맥이 없음 | 1 |

final 검사는 position 단계의12개 중4개를 제외했지만, 이 중3개는 원문에 명시된 주장이고1개는 수사 의문문이었습니다.
기존 명백한 지시 대상/문맥 실패3개는 그대로 통과했습니다.
이전12units에 그대로 적용한 별도 검사도 정상8개 중7개만 유지하고, 알려진 실패3개는 하나도 막지 못했습니다.
불확실한 수사 의문문1개도 통과했습니다. 따라서 **추가 LLM 호출이 문맥 문제를 해결한다는 증거는 없습니다.**
값 판단이나 사실 확인이 아니라 원문 충실성·독립성 평가입니다. 특정 작성자의 주장에 동의하거나 검증한 것이 아닙니다.

## 검색과 추출 손실의 분리

같은29source pool에서 원문 전체, 위치 선택 후31units, 최종 검사 후25units를 각각 embedding했습니다.
기존 MiniLM 모델/revision, cross-mode의cosine0.55/top8, hybrid의semantic8+lexical4를 유지했습니다.
원문 전체 embedding은 기존 token chunk 경로를 사용하며 긴 입력을 앞부분만 잘라 사용하지 않습니다.

| 검색 입력 | 기존3쌍의 양쪽 source 잔존 | cross-mode 상대 source 노출 | hybrid 상대 source 노출 |
| --- | --- | --- | --- |
| 원문29개 | 3/3 | 3/3 | 3/3 |
| 위치 선택 후31units | 0/3 | 0/3 | 0/3 |
| 최종 검사 후25units | 0/3 | 0/3 | 0/3 |

원문 검색 순위는1·2·1위였습니다. 검색을 넓히지 않은 기존 cross-mode도 찾았습니다.
추출 후에는 상대 source 자체가 없으므로 threshold를 낮추거나 이웃 수를 늘려도 이번 손실을 복구할 수 없습니다.

- 한 댓글은 동의 표현과 명시적인 조건부 취업 의도를 함께 담지만 selector가 전체를 non_substantive로 분류했습니다.
  동의 표현이 내부 판단의 원인인지는 알 수 없으며, 관측된 사실은 빈 선택 결과입니다.
- 다른 anchor에서는 짧은 첫 주장이 선택되지 않았습니다. 대신 선택된 긴 주장3개는 모두 topic 길이 계약에서 거절됐습니다.
- 후자의 anchor가2쌍에 공통이므로3개 실패를 독립 사례3개로 해석하지 않습니다.

이는 source 노출 검사이지 올바른 claim 매칭·cluster 가입·전체1,000개 recall 검사가 아닙니다.
정답 source를 포함한 작은 비대표 대조 pool이므로 원문 검색의 일반 우수성을 주장하지 않습니다.

## 결정과 다음 구현 경계

이번 코드와 결과는 진단으로 보존합니다. 고정 검사와 실제 문맥 평가가 실패해 assembly/새 agent 생성은 실행하지 않았습니다.
MVP 품질 완료가 아니며, 사람이 runtime에 개입하도록 바꾸지도 않았습니다.

다음 비교는 **원문 후보를 보존한 검색 → 후보별 공통 주장 및 원문 지지 검사** 순서가 적절합니다.
LLM 선택/top4/필수 topic 때문에 원문 검색 후보를 영구 제거하지 않아야 합니다.
topic은 검색 보조 정보로 분리하고 누락돼도 원문 후보를 보존하는 방향입니다.
이 retrieval-first 경로는 아직 구현하지 않았으며, 승인 기준을 완화하거나 이번 결과를 성공으로 재분류한 것이 아닙니다.

## 실행 환경과 재현

첫 `runs/evidence-positions-20261012` 실행은 CUDA 라이브러리 경로 누락으로 CPU fallback됐습니다.
선언된 GPU metadata와 달라 중단하고 partial checkpoint와 `runtime-incident.json`을 보존했습니다.
라이브러리 경로만 수정해 새 `runs/evidence-positions-20261012-gpu`에서 처음부터 실행했습니다.
코드/prompt/선택/라벨/상한은 동일하고 CPU checkpoint는 재사용하지 않았습니다.

GPU 프로세스의 CUDA 라이브러리 mapping, model/server 파일 hash와4,348MiB의 GPU 사용 관측을 별도 저장했습니다.
이는 원격 attestation이 아닙니다. 기본 transport는 loopback 전용이며 모델 서버는 검증 후 종료했습니다.

기존 로컬 자료와 clustering 환경, README의 Qwen 서버가 필요합니다. 공개 Git에는 실제 댓글/실행 결과/가중치가 없습니다.
아래는 repo root에서 실행하는 Bash 명령입니다. 완료된 run-dir는 덮어쓰지 않습니다.

```bash
PYTHONPATH=src python -m experiments.evidence_positions_probe --run-dir runs/evidence-positions-new --phase plan --diagnostic-only
PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.evidence_positions_probe --run-dir runs/evidence-positions-new --phase extract --diagnostic-only
PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.evidence_positions_probe --run-dir runs/evidence-positions-new --phase retrieval --diagnostic-only
PYTHONPATH=src python -m experiments.evidence_positions_probe --run-dir runs/evidence-positions-new --phase verify --diagnostic-only
```

로컬 CUDA 라이브러리가 시스템 경로에 없다면 서버 시작 시 올바른 `LD_LIBRARY_PATH`를 지정합니다.
`-ngl99` 요청만으로 GPU 사용을 가정하지 말고 실제 프로세스와 GPU 메모리를 확인해야 합니다.

추출·검색 report를 새 LLM/embedding 호출0회로 replay해 일치했습니다. Python331개/Node4개 통과입니다.
단위 테스트/재현 성공은 모델 의미 품질 보증이 아닙니다.

- private 종합 화면: `artifacts/evidence-positions-overview-20261012.html`.
- 상세: `runs/evidence-positions-20261012-gpu/extract.html`, `retrieval.html`, plan/raw checkpoint/vector JSON.
- 전수 사후 평가: `artifacts/evidence-positions-review-20261012.json`.
- plan SHA256: `4909a91bcc9869f0212bfa01883d4d74b9931b0c7c4408c50bd43316092b0e4a`.
- extraction SHA256: `02fa7a5755bf2bf958484752f09c62bafdc92fffecc205afa033dc89c5b4c89b`.
- retrieval SHA256: `3ece4b5b21af2b798c8e2b4a53f2290d82a12cd67564d80a9c5fad2e347ba49e`.
