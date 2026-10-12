# 원문 검색 우선 MVP 계약 — 2026-10-12

상태: 실험 경로. Factory0.2/main을 교체하지 않는다. 원문 보존·검색·대기 목록까지 구현하며,
공통 주장 생성·지지 수 집계·agent 승격은 이 경로에 아직 연결하지 않는다.

## 결정한 구조

`고정 API 표본 → canonical 원문/벡터 → 검색 후보 → 비교 대기 목록 → 공통 주장 → 원문별 지지 판정 → agent`

앞의 네 단계가 이번 구현이다. 추출/eligibility/topic 생성 실패가 원문 검색을 막지 않는다.
각 단계의 입력·출력·버전·hash·시간을 별도 저장해 교체할 수 있게 한다. 서비스 실행에 사람의 승인 파일을 넣지 않는다.
개발용 assistant 평가와 향후 독립 연구 평가는 서비스 판정과 별개다.

## 지지도 계약 v0.1 — 집계 구현은 다음 단계

- 지지 수는 **고정된 공통 주장을 직접 지지한다고 판정된 canonical 댓글 ID의 수**다.
  검색 이웃 수·유사도·좋아요·claim 개수·LLM 요청 수를 지지 수로 쓰지 않는다. anchor도 검사 없이 자동 득표하지 않는다.
- 기존 NFC/공백 정규화와 같은 parent 안의 동일 텍스트를 alias로 묶는다. 서로 다른 parent의 같은 문장은 남는다.
  저자 중복·조작 계정 제거가 아니며, 댓글 수를 사람 수나 전체 시청자의 여론으로 표현하지 않는다.
- 공통 주장별 상태는 `support / not_supported / uncertain / error / unchecked`로 나눈다.
  다섯 상태의 합은 고정 N이다. 예산 소진·검색 미노출은 `unchecked`이며 반대나 비지지가 아니다.
- 화면은 `판정 통과 S / 선택 corpus N`, 검사 완료 수, 불확실·오류·미검사 수와 표본 범위를 함께 표시한다.
  모델 오승인 가능성이 있어 S를 실제 지지의 보장된 하한이나 통계적 신뢰도로 부르지 않는다.
- 한 댓글은 같은 주장에 한 표다. 실제로 다른 두 주장을 지지하면 양쪽에 포함될 수 있어 관점별 비율 합이100%를 넘을 수 있다.
  동의어 주장 병합·중복 agent 방지는 후속 계약에서 검증한다.
- **잠정 표시 기준**: 주요 후보 `S >= max(10, ceil(0.05*N))`, 제한적 관점 `3 <= S < 주요 기준`, 희소 `S=1..2`.
  N=999/1000이면 주요 기준50이다. 이는 사용자와 합의한 과학적 임계값이 아니라 첫 구현용 제안값이다.
  미검사량이 크면 ‘현재 확인된’ 수준으로만 표시한다. 이 숫자만으로 agent를 승인하지 않으며 의미 품질 gate가 별도로 필요하다.

## 검색 계약 v0.1 — 구현됨

- `factory/raw_candidates.py`: 원문/ID/digest/parent/alias registry. 공백 원문도 보존하되 embedding 대상에서만 제외한다.
- 기존 고정 multilingual MiniLM을 CPU에서 사용한다. 기존 token chunk 후 평균 embedding을 재사용하므로 긴 원문을 단순 앞부분으로 자르지 않는다.
- 원문당 cosine 상위8개 + 중복되지 않는 lexical 후보 최대4개. similarity threshold/주장 유형/topic 필터는 없다.
  반대 주장도 검색될 수 있으며 이것이 membership 승인은 아니다.
- 출력 후보는 최대12N개. 계산은 dense O(N²)이며 최대1,000 canonical MVP에 한정한다. 대규모 확장성 해결로 주장하지 않는다.
- source hash 순서에서 rank-round-robin, 무방향 pair 중복 제거 후64쌍을 후속 검사 대기 목록에 둔다.
  넘친 후보는 전부 후보 파일에 남는다. queue 예산은 지원 개수나 전체 검사 완료 보장이 아니다.
- source packet은 두 원문의 ID/digest/text만 전달한다. parent 텍스트를 답글에 합성하지 않는다.
  parent가 별도 검색 후보로 선택될 수는 있다. 원문의 지시 대상·독립성·공통 의미 검사는 다음 단계다.
- 현재 `support_count=null`, `quality_gate_passed=false`, `agents=[]`, 생성형 호출0을 유지한다.

## 처리시간 계약 v0.1 — 아직 성능 목표 미검증

잠정 목표는 warm local 모델/RTX4060 Laptop8GB 환경에서 첫 유효 agent60초 이내,
1,000댓글 membership 처리300초 이내다. 하드웨어·모델·표본·cache 상태를 함께 보고하고,
API 수집/모델 최초 다운로드/cold loading을 분리한다. 목표 수치는 실측 달성이나 최종 SLA가 아니다.
agent가0개인 빠른 실패는 첫 agent 목표 통과로 세지 않는다.

이번 측정은 CPU embedding load+inference/cache IO, 후보 검색+queue, 시작부터 보고서 직전까지다.
Python startup/최종 보고서 쓰기/댓글 수집/공통 주장·지지 검사·agent 생성은 포함하지 않는다.
캐시 replay 시간은 새 입력 warm inference 시간과 다르다. 과거 여러 실험의 누적90분과 직접 비교하지 않는다.

## 재현과 평가 경계

기존 ML 환경 또는 README의 clustering 환경을 사용한다. 실제 데이터는 공개 Git에 넣지 않는다.
snapshot 만료를 검사하며 vector/원문/HTML도 같은 만료 정책을 따른다.

```bash
python -m experiments.raw_candidates_probe --run-dir runs/NEW-RAW --phase plan --diagnostic-only \
  --reference-plan runs/evidence-positions-20261012-gpu/plan.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.raw_candidates_probe \
  --run-dir runs/NEW-RAW --phase run --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.raw_candidates_probe \
  --run-dir runs/NEW-RAW --phase verify --diagnostic-only
```

기본64개: 이전29실제 원문 + source hash로 선택한35개. 알려진 정상3쌍은 평가에만 쓰며 검색/queue 입력에 넣지 않는다.
다만 평가군 포함을 위해 표본 구성에 이전 원문을 사용하므로 독립 holdout이나 무작위 전체 corpus 평가가 아니다.
다른 사용자는 자신의 snapshot을 `--snapshot`으로 지정하고 `--reference-plan`을 생략할 수 있다.
전체1000 실제 모델 추론은 이번 단계 범위 밖이다. 합성1000개 벡터 시험은 용량 계약 검사일 뿐 실제 품질·속도가 아니다.

계획/코드/input/model revision hash를 먼저 고정한다. embedding cache의 원문/순서/revision/vector digest를 검사한다.
verify는 저장 벡터로 결과를 다시 만들며 모델을 호출하지 않는다. 결과를 보고 queue 예산이나 표본을 바꾸지 않는다.

다음 순서: 원문 쌍에서 공통 주장 제안+직접 지지 검사 → 고정 주장별 support 집계 → latency profiling/최적화
→ 자동 agent/UI 연결 → 미사용 표본과 end-to-end 검증. 검색 성공만으로 clustering/MVP 완료를 선언하지 않는다.

## 실제 실행 결과 — 2026-10-12

사전 고정 코드 `a77f566`. 기존29개에35개를 추가한64개를 모두 보존했다.
방향 있는 후보764개, 무방향 후보533쌍 중64쌍 대기/469쌍 보류다.
알려진 개발 정상3쌍은 모두 검색되었고(anchor→member 순위1,2,1),64쌍 대기 목록에도 모두 들어갔다.
과거 추출 후 해당 source 쌍 잔존0/3인 병목을 이 검색 경로에서 피했다.
단, pool29→64와 경로가 함께 바뀌었으므로 같은 pool의 통제 실험 효과량으로 해석하지 않는다.
검색 정확도/전체 recall/공통 주장 지지 판정/agent 품질을 입증한 결과는 아니다.

CPU4threads, 기존 cached model weights, embedding vector cache miss였다.
embedding 라이브러리·모델 로딩/추론/벡터 저장20.43초, 검색+queue0.085초, 보고서 직전까지21.06초.
peak RSS 약958MiB. torch2.14.1+cpu/transformers4.57.1/sentence-transformers5.1.1/numpy2.5.3.
원문 token134>128 경고는 chunk 준비 전 tokenizer에서 발생했으며 기존 token_chunks의 길이 재검사/분할 경로로
전체 token을 처리했다. 원문을 삭제하거나 잘라 저장하지 않았다.

새 생성형 호출0/embedding invocation1/agent0/support 미산정. 새 수집/외부 댓글 전송/모델 다운로드0.
저장 벡터 재생은 새 embedding/생성형 호출 없이 결과와 일치했다. Python349개/Node4개 통과.
합성1000source 시험도 포함되지만 실제1000개 성능 시험은 아니다.

원문 포함 결과는 Git 제외 `runs/raw-candidates-20261012/overview.html`, `report.json`, `vectors.json`, `plan.json`.
원본 snapshot 만료2026-11-08T18:30:59.664629Z를 상속한다.

- plan SHA256: `4b6d642194e2f8f755fc6645266ce387221942dc8354041e947e1bae849d4499`
- report SHA256: `f7d4f06d9b2c40c5598d4933f5da8e5c3637005cad02cbfad87afa2f987a4d5c`
- vectors SHA256: `d304a754d477decffa2f15aa239d9fce47da4275207a4490e8be129ca97d28a8`
