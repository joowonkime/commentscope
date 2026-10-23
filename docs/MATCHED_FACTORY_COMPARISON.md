# 실제64개 V0/V1/V2 비교

2026-10-13: `experiments/matched_factory_probe.py`를 동결해 첫 matched 개발 비교를 완료했다.
**세 구성 모두 기본 채택 기준 미달이다.** 후보 수 증가나 감사 통과를 MVP 완료로 간주하지 않는다.
아래 실행 조건은 결과 전 동결한 값이고, 결과에 맞춰 변경하지 않았다.

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

실행 코드 `e09a691`, private `runs/matched-factory-20261013/`.
입력64개 모두 fresh 추출 요청에 참여했고45개에서113claim,19개에서 non_substantive를 반환했다.
context_dependent/uncertain을 반환한 원문은0개다. 이는 문맥 문제가 없다는 뜻이 아니다.
V0는58후보 중 다인5개를, V1은77후보 중 다인9개를 카드 생성기로 보냈다. 나머지는 단일 source 후보로 보존했다.

| 결과 | V0 원문 | V1 주장 | V2 같은 V1+감사 |
|---|---:|---:|---:|
| 생성/유지 카드 |6|15|10|
| 서로 다른 source≥3 카드 |0|1|0|
| assistant 검토상 모든 인용이 충실한 카드 |1|5|5|
| 그중 source≥3 카드 |0|0|0|
| 충실하다고 읽힌 common 가입 관계 |4/11|8/21|7/11|
| 충실하다고 읽힌 detail 인용 관계 |12/16|17/36|11/18|

이는 비블라인드 assistant 개발 평가다. 독립 gold, 논문 accuracy, 사실 검증 또는 전체64개 관점 recall이 아니다.
같은 source가 여러 claim으로 반복된 인용은 문장별1회만 센다. 충실한 작은 카드에도 개인/메타 의견이 있어 제품상 유효 관점과 동일하지 않다.
판정에 이견이 가능한 범위/비유 사례를 포함하므로 작은 비율 차이로 우열을 확정하지 않는다.
주요 결론은 명확한 반대 입장 오가입과 최소3-source 카드 부재에 근거한다.

V1의 유일한3-source 카드 `V1-C003-D01`은 'UBI가 있으면 사람들은 일하지 않을 것'이었다.
한 댓글은 그 주장을 했지만 다른 댓글은 열악한 노동을 강요하지 말자는 주장이고,
나머지는 UBI가 있어도 계속 일하겠다는 입장이다. 서로 다른 댓글 수3은 지지 수3이 아니었다.
V2는 후자의 두 common 가입을 unsupported로 판정해 이 카드를 제거했다.

반대로 물가3원문은 V0-C001 및 V1-C002의 후보 단계에 모두 도달했다.
V0 생성은2+1로, V1 생성은 서로 다른 원문 기준1+1+1로 갈랐다.
V1에는 '물가는 화폐 발행만으로 발생하지 않는다'는 좁은 공통 주장을 가질 수 있는 구간들이 있었으나,
생성기가 더 구체적인 조건/다른 수요 주장을 선택했다. 이 실패는 검색 누락만으로 설명되지 않는다.
V1-C004에서는 가격 상승을 명시한 댓글을 '가격 상승을 주장하지 않는다'는 잘못된 이유로 제외하기도 했다.

### 감사의 이익과 한계

57개 distinct 문장/source 요청을 실행했다. assistant가 충실하다고 읽은25개 중23개를 supported로 유지하고,
부분 지원/미지원/불명확32개 중20개도 supported로 통과시켰다. 이는 독립 정확도가 아닌 판정 불일치 진단이다.
완전히 충실하다고 읽힌 작은 카드5/5는 유지했지만, 남긴10개 중5개에는 여전히 문제 인용이 있었다.
감사된 개별 정상 관계의 통과와 카드 전체 유지에 따른 정상 관계 보존은 다르다. 카드 전체 필터 후 정상 관계는18/25다.
기존 V1 원본과 보류 사유는 삭제하지 않았다.

감사는 명백한 반대 입장과 명시하지 않은 job displacement 이유 일부를 차단했다.
하지만 개인 경험의 일반화, 추가 인과·동기, 풍자/질문 처리 등을 완전히 해결하지 못했다.
정상 원문의 fallback 주장을 'only way to go라서 replacement를 뜻한다'며 거절한 오류도 있었다.
따라서 이 감사는 부분적인 보호 효과가 있지만 단독 품질 인증기로 채택할 근거가 없다.

### 비용과 실행 건전성

| 단계 | fresh 생성 요청 | 관측 시간 |
|---|---:|---:|
| V0 카드 생성 |5|84.42초|
| V1 추출 |64|323.46초|
| V1 주장 embedding |생성 요청 아님|13.96초|
| V1 카드 생성 |9|254.28초|
| V2 감사 |57|166.63초|

총135생성 요청, 생성 시간 합828.79초, embedding을 더한 관측 단계 시간842.74초다.
V0 원문 벡터는 기존 캐시라 fresh embedding 비용을 포함하지 않는다. V2는 V1을 재실행하지 않았다.
서버 시작·파일 I/O·전체 서비스 UI latency와 별개이며,1,000개 서비스 속도 개선을 입증한 결과가 아니다.
transport/응답/추출·draft 계약/감사 오류0, 예산 보류0, 모든 완료 사유stop이다.
코드의 형식·출처 검사가 통과해도 의미는 틀릴 수 있다는 사례다. 종료 시 소유 서버PID34024의 정상 종료와 부재를 확인했다.

### 결정과 다음 변경 경계

이번 구성의 기본 채택·예약64개 실행·1,000개 재실행·agent 승격은 하지 않는다.
사전 조건인 충실한3-source 이상 카드≥1을 모두 충족하지 못했다. 감사 시간 조건만 통과해도 승자가 될 수 없다.

다음 변경 대상은 **공통 주장 제안+가입 결정+상세 이유 생성을 한 요청에서 수행하는 경계**다.
이미 검색에 잡힌 원문을 재그룹하면서 핵심을 바꾸거나 다른 댓글의 이유를 옮기는 문제가 관측됐다.
다음 한 번의 제한 비교에서는 검색 artifact를 유지하고 다음 계약을 검증한다.

1. 공통 주장 후보를 먼저 고정하고 ID/digest를 부여한다. 가입 판단 도중 주장을 바꾸지 않는다.
2. 원문별로 그 고정 주장에 대한 관계만 판단한다. 전체 댓글의 배타적 분할을 강요하지 않고 한 원문이 서로 다른 주장에 참여할 수 있게 한다.
3. distinct source 지지를 계산한 뒤 상세 이유를 다룬다. 초기 상세 근거는 원문 인용으로 보존하고 다른 댓글을 함께 본 자유 생성 이유를 지지 수의 전제에 넣지 않는다.
4. 현재4B 감사의 잔존 오승인도 그대로 회귀에 남긴다. 이 분해가 성공한다고 가정하지 않으며, 정상3-source 물가 후보 보존과 반대 입장 오가입 차단을 동시에 요구한다.

이는 새로 구현·성공한 경로가 아니라 다음 adapter 변경 범위다. 기존 extractive/NLI 실험을 그대로 다시 돌리면 해결된다고 주장하지 않는다.
그 실험의 정상 손실도 재사용할 회귀 근거다. 아직 추출·가입 모델의 의미 판단을 코드만으로 완전히 보장할 수는 없다.

## 결과 확인과 재생

private `assistant-review.html`에서 전체21개 카드의 원문·문장별 판정·V2 유지 여부를 함께 본다.
사전 선택12개 원문의 추출 오류 메모도 포함한다. 사용자 입력이나 런타임 보정 라벨로 쓰지 않았다.
`experiments/matched_factory_review.py`는 전체 카드/인용 평가 누락, 중복 source의 상충 판정을 거부하고 수치를 재계산한다.
이 offline renderer는 생성 실행 후 별도 추가했으며 frozen 추론 코드를 변경하지 않았다.

```bash
python -m experiments.matched_factory_probe --run-dir runs/matched-factory-20261013 --phase verify
# assistant-ratings.json을 작성한 새 검토 디렉터리/아직 결과 파일이 없는 실행에서만:
python -m experiments.matched_factory_review --run-dir runs/matched-factory-20261013
```

기존 산출물은 덮어쓰지 않는다. 원문을 포함한 private HTML/JSON을 공개 저장소에 올리지 않는다.
plan SHA `33895cfd3bdb7ee2a225e681f55afe00f183b292fba59f58d7b3c79f7e0ea54a`.
report SHA `51722fb576a7b162085e7ee425320bcc170b17d360eb2df5baa4577cc8f4b07c`.
assistant review SHA `29b9cf4c08a6d05c758eff76f957bdd455d75bf21e8049240faff5b570be3cbe`.
