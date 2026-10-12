# 실제64개 V0/V1/V2 비교

2026-10-13: `experiments/matched_factory_probe.py`를 동결해 첫 matched 개발 비교를 실행한다.
이 문서는 실행 조건이며, 결과를 받기 전 품질 승인이나 MVP 완료를 선언하지 않는다.

## 공통 조건

기존 평가 kit의 개발64개를 유지한다. 예약64개는 이번 실행·튜닝에 쓰지 않는다.
full own-comment만 사용하고 parent와 assistant 평가표는 모델에 넣지 않는다.
Qwen3-4B-Instruct-2507 Q4_K_M, temperature0/seed407, 단일 로컬 서버를 쓴다.
context8192/GPU26/threads6/cache-prompt off다. 이전4096-context 감사 실험과 속도를 직접 비교하지 않는다.
임베딩은 기존 pinned multilingual MiniLM, clustering은 deterministic average linkage/distance0.45다.

| 변형 | 후보 입력 | 카드 생성 | 후처리 |
|---|---|---|---|
| V0 | 기존64개 원문 벡터 | 기존 v3 prompt/assignment0.2, 전체 원문을 scope로 제공 | 추가 감사 없음 |
| V1 |64개에서 fresh 추출한 주장 statement의 벡터 | 같은 생성기, 선택한 정확한 원문 span 목록을 scope로 제공 | 추가 감사 없음 |
| V2 | V1 artifact 그대로 | 재생성 없음 | common/detail별 원문-문장 감사를 거쳐 카드 전체 유지/보류 |

모든 카드 생성 요청에는 전체 원문도 함께 제공한다. `scope_quote`는 두 변형 모두 정확한 span의 목록이다.
V0/V1 차이는 추출+표현+scope 선택을 포함한 패키지 비교이며 추출 한 요소만의 인과 효과가 아니다.
서로 다른 원문2개 이상인 후보만 생성한다. 단일 원문·예산 초과 후보는 원문/사유를 남긴다.
공통 주장·세부 근거·실제 source ID의 카드 계약은 동일하다. 최소3개 출처는 agent 후보의 필요조건이지 승인 기준의 전부가 아니다.
`candidate_source_count`와 검증된 `support_count`를 구분하고 후자는 null로 둔다.
동일 source에서 여러 claim이 나와도 지지 수를 늘리지 않는다.

V2 감사는 기존 source-statement prompt0.2를 사용한다. 한 요청에 특정 원문과 특정 문장만 넣는다.
같은 source/원문/statement의 중복 인용은 한 번 검사한다. 한 카드의 common 및 모든 detail 인용이 supported일 때만 그 카드를 그대로 남긴다.
partial/unsupported/unclear/error/미검사는 유지하지 않는다. 이는 비교할 단순 정책이지 최적 정책으로 채택한 것이 아니다.
정상 공통 주장에 나쁜 detail 하나가 붙어 카드 전체가 탈락하는 손실도 평가한다. 서비스에 사람 승인 단계를 추가하지 않는다.

## 동결 예산·기준

- 추출64회, V0/V1 draft 각각32회, 감사192회: 최대320회 fresh 생성 요청. 재시도/repair0회.
- 완료된 생성 요청 시간 합1,800초에 도달하면 다음 요청부터 보류한다. 진행 중 요청의 transport timeout은180초여서 마지막 요청만큼 초과 가능하다. 서버 시작·CPU embedding은 별도 기록한다.
- 최대20member/후보, 요청30,000 UTF-8 byte. 초과 시 잘라내지 않고 보류한다. 이는 token 계산이 아니며 context 초과는 `--no-context-shift` 서버 오류로 기록한다.
- completion 상한은 추출900, draft1,800, 감사300token. finish가 stop이 아니면 형식 실패로 처리한다.
- 원문 보존/출처/분모/hash 불변조건 실패는 중단한다. 원시 응답·오류·호출 설정을 append-only로 남긴다.
- 개발 비교 후보가 되려면 assistant 검토상 유효한3-source 이상 카드≥1, 해당 카드 크기군의 잘못된 common/detail 가입0, transport/contract 오류0이어야 한다. 작은 카드도 손실·왜곡을 별도로 공개한다.
- V2 채택 후보 조건: 실제 잘못된 가입을 줄이고, V1의 유효3-source 이상 카드를 모두 보존하고, 추가 감사≤300초. 모두 거절하는 결과는 승자가 아니다.

assistant 검토는 잠정 개발 라벨이며 사용자 개별 확인·독립 gold가 아니다. 사실성 의심과 원문 충실성을 분리하고,
질문/동의/인용과 독립 주장이 섞이면 실제 저자의 주장만 평가한다. 관련성·모달리티·조건·범위·인용 귀속을 확인한다.
보고할 값은 후보 수, 모든 생성 카드와 common/detail source 관계의 검토, >=3 카드 coverage, 감사 정상 손실/오승인,
누락/희소/오류/예산 보류, 실제 호출/시간이다. 전체 corpus recall이나 여론 비율을 추정하지 않는다.
비교 결과가 모두 기준 미달이면 승자를 정하지 않고, 표본 밀도와 제안·분할·감사 중 실패한 경계를 구분한다.

## 실행과 산출물

기존 연구 데이터와 로컬 모델을 갖춘 개발 환경에서만 실행한다. 데이터·모델 다운로드나 유료 호출을 하지 않는다.

```bash
python -m experiments.matched_factory_probe --run-dir runs/NEW-MATCHED --phase prepare
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.matched_factory_probe --run-dir runs/NEW-MATCHED --phase run
python -m experiments.matched_factory_probe --run-dir runs/NEW-MATCHED --phase verify
```

`run`에는 clustering extra가 설치된 Python이 필요하다. 원문/응답/벡터/모델 파일은 공개 Git에 넣지 않는다.
prepare는 입력·코드·모델을 고정하고, run은 새 요청만 수행한다. 실패한 실행을 같은 디렉터리에서 재시작하지 않는다.
verify는 완료 manifest의 파일 hash와 V2가 V1 카드의 정확한 부분집합인지 확인하며 모델을 부르지 않는다.
이번 private 경로는 `runs/matched-factory-20261013/`이다.

## 결과

실행 전: 미측정. 기존 baseline 또는 과거 감사 점수를 이번 결과로 대체하지 않는다.
