# 실제 관점 생성 평가를 위한 비교 프로토콜

최근 실패마다 새로운 검사를 추가하는 방식에서 벗어나, 같은 실제 입력으로 소수의 구조를 비교한다.
현재 matched adapter·공통 출력·호출 예산을 동결해 [첫 실제 비교](MATCHED_FACTORY_COMPARISON.md)를 완료했다. 세 구성 모두 기본 채택 기준 미달이다.
아래의 준비 단계 설명은 그 실험의 배경이며, 최신 실행 조건·성과·채택 여부는 연결 문서에서 확인한다.
이 문서를 이미 사전등록을 완료한 연구 실험이나 자동 MVP 품질 승인으로 취급하지 않는다.

## 비교할 질문

| 변형 | 질문 | 유지할 조건 |
|---|---|---|
| V0 원문 기반 | 주장 추출 없이 얻은 후보가 얼마나 유용한가 | 동일 source 분모·임베딩 모델·공통 평가 |
| V1 주장 기반 | 추출이 관점 구분과 근거 충실성을 개선하는가 | V0와 같은 source, 누락 source도 분모 유지 |
| V2 같은 V1에 감사 추가 | 감사의 순이익이 정상 손실과 비용보다 큰가 | V1 추출·벡터·후보 artifact 그대로 재사용 |

현재의 `cluster_baseline`과 과거 자동 Factory 출력은 입력·pooling·정책·검사 수가 달라 그대로 순위를 매길 수 없다.
V0 준비 baseline은 기존 raw64 벡터와 `claim_clusters.average_linkage`의 결정적 구현을 사용한다.
distance0.45는 기존 baseline 설정을 결과 확인 전에 고정한 것으로, 이번 표본에서 최적화한 수치가 아니다.
원문 인용 medoid는 공통 주장으로 간주하지 않는다. 관점 카드와 agent-level 비교를 하려면 **동일한 카드 생성·지지 평가 경계**를 모든 변형에 연결해야 한다.
그 adapter는 `experiments/matched_factory_probe.py`로 구현했다. V0의 후보 수와 V2의 승인 agent 수를 같은 지표처럼 비교하지 않는다.

## 표본과 노출 이력

기존 official snapshot1,000개/999canonical을 유지한다. 기존 raw retrieval 개발64개를 그대로 사용하고, 별도64개를 다음 라운드 예약 표본으로 선택했다.
원문·부모 ID는 보존한다. parent 연결과 NFC/공백 정규화 후 동일한 문장으로 연결된 component를 분할 단위로 삼는다.
여기서 동일성은 댓글 전체 텍스트 기준이다. 일부 문장의 공유, 재표현, 의미적으로 유사한 내용까지 분할 간 차단했다는 뜻은 아니다.
부모가 snapshot 밖에 있어도 같은 parent ID를 공유하는 reply는 같은 component다. component의 선택되지 않은 형제도 다른 분할의 후보로 사용하지 않는다.
동일문장 연결은 **평가 분할용**이며 서로 다른 parent의 댓글을 추가 중복 제거하거나 지지 투표를 합치는 정책이 아니다.

결과는 개발 선택64/예약 선택64다. component 전체로는 개발444/예약90/나머지465canonical이다.
이는444개를 이번에 추론했다는 뜻이 아니다. component 분리가 참여 source의 독립성이나 같은 스레드 작성자의 독립성을 증명하지도 않는다.
이미 전체 corpus가 과거 실행에 사용됐고 모든 사후 검토 노출을 인증할 수 없으므로 예약 표본은 **미사용 holdout이 아니다**.
새 영상의 외부 검증은 후속 범위이며 현재 추가 수집하지 않는다.

예약64개의 원문·모델 출력을 보고 튜닝하지 않는다. 개발 단계 선택이 완료되면 한 번 평가하고,
실패를 확인한 뒤 수정하려면 해당 예약군을 개발 데이터로 재분류하고 새 검증 계획을 기록한다. 과거 노출 이력은 지우지 않는다.
최초 matched 비교는 full own-comment만 사용한다. reply 문맥은 링크로 보존하되 parent 내용의 지지를 reply에 전이하지 않는다.
이는 비교 조건이지 제품에서 parent 활용을 영구 금지하는 원칙은 아니다.

## 평가 단위와 측정할 값

댓글에 독립 주장이 있는지의 이진 정확도 하나를 제품 목표로 쓰지 않는다.

| 단위 | 평가 질문 | 주의 |
|---|---|---|
| 원문 | 해석 가능한 주장·경험, 질문/반응, 주제 관련성, 문맥 의존을 구분했나 | 혼합 댓글 전체를 버리지 않음; factual truth와 source fidelity 구분 |
| 원문과 특정 주장 | 원문이 그 주장 전체를 지지하나 | 같은 주제/자기 source/유사도가 자동 지지는 아님 |
| 관점 카드 | 공통 주장과 개별 이유·조건의 출처가 충실한가 | 공통 이유가 아닌 것을 모두의 이유로 일반화하지 않음 |
| 전체 결과 | 유용한 관점과 source를 얼마나 보존했나 | 잘못 가입한 댓글, 누락, 보류, 희소 항목을 함께 공개 |
| 비용 | 실제 호출 수와 fresh 처리 시간은 얼마인가 | cached 재생·실험 누적 시간·서비스 latency를 구분 |

주 지표 후보는 평가된 가입 관계의 오승인 비율, 평가된 유효 관점의 발견 비율, 카드의 의미 추가/조건·범위 손실,
source coverage와 미검사량, 관점당 호출·시간이다. 분모가0이면 비율은 null이며0%오류로 성공 처리하지 않는다.
후보 크기≥3인 source 비율은 검색/구조 지표일 뿐 의미적으로 유효한 coverage가 아니다.
평가하지 않은 전체 corpus recall을 추정하거나 model eligible을 실제 정답으로 대입하지 않는다.

공개 기준선에 사람/assistant의 reference를 넣지 않는다. source-level 라벨과 카드/가입 평가표는 런타임 입력과 별도 파일로 관리한다.
역할을 가린 비교 평가는 후속 공통 평가 출력에서 구현해야 한다. 이번 assistant의 V0 검토는 variant를 알고 수행한 개발 진단이다.

## 정책 보정

개발64개에서 길이3구간×reply 여부2구간을 hash 순서 round-robin으로12개 뽑았다. 모델 출력이나 의미 라벨로 고르지 않았다.
assistant가 먼저 원문을 검토하고, 사용자에게 정책을 좌우하는 소수 사례의 피드백을 받는다.12개 전체를 사람이 판정하도록 요구하지 않는다.
이 과정은 offline 평가 기준 보정이지 서비스 승인 대기열이 아니다. assistant 초안을 독립 gold로 부르지 않는다.

우선 확인할 경계는 (1) 저자가 주장하지만 사실성이 의심스러운 내용과 source fidelity의 분리,
(2) 질문/동의/농담과 유효 주장이 섞인 원문의 부분 보존,
(3) 개인 경험과 다른 집단에 대한 일반화·타인 인용의 구분이다.
현재 잠정값은 원문에 주장 자체가 있으면 기록하되 사실 보증으로 노출하지 않고, 관련성이 없거나 근거가 부족하면 agent 승격하지 않는 것이다.
저자 입장에 동의하는지 또는 인기 있는지로 원문 자격을 정하지 않는다. 미래의 콘텐츠 안전 정책은 별도이며 이를 우회하는 규칙이 아니다.

## 실행 전 동결과 중단 기준

다음 의미 추론 전에 세 variant의 정확한 함수/설정·model/hash·입력·출력·source 분모·공통 카드 경계·평가표·호출/시간 상한을 함께 동결한다.
개발64개는 오류 분리에 적합하지만 관점 밀도와 주제 분포가 전체를 대표하지 않는다. sparse 결과만 보고 threshold를 내려 agent 수를 맞추지 않는다.
표본 확대가 필요하면 이전 비교와 분리한 계획 변경으로 남기고 모든 variant에 같은 범위를 적용한다.

- 코드 불변조건 실패는 즉시 중단한다. 잘못된 인용·중복 집계·원문 유실을 의미 점수로 상쇄하지 않는다.
- 의미 검사는 부정 차단뿐 아니라 정상 손실을 함께 비교한다. 모든 항목을 거절하는 방식은 승자가 아니다.
- 감사 추가가 오류를 충분히 줄이지 못하거나 유효 관점 손실·비용만 늘리면 폐기한다. 검사층을 자동으로 하나 더 추가하지 않는다.
- 수치형 품질·비용 허용선은 첫 fresh V1/V2 실행 전에 고정한다. 결과를 본 후 완화하지 않는다. 첫 실행 값은 [matched 비교](MATCHED_FACTORY_COMPARISON.md)에 기록했다.
- 같은 가설의 한 비교 라운드에서 한 번만 후보를 실행한다. 결과 후 수정은 새 버전·다음 라운드로 기록한다.
- 개발 비교를 이긴 구성이 없으면 모델의 학습/표현/문제 분해 가설을 재검토한다. 전체1,000개 재실행으로 해결하려 하지 않는다.

## 준비 도구와 이번 결과

`experiments/factory_evaluation_kit.py`는 기존 snapshot·raw plan·벡터를 검증해 split,calibration,baseline,HTML을 만들고 재생한다.
원문은 private 경로에만 저장하고 보관 만료를 상속한다. 이 도구는 LLM/embedding 호출·네트워크·agent 승격을 수행하지 않는다.

```bash
python -m experiments.factory_evaluation_kit --run-dir runs/NEW-EVALUATION --phase prepare
python -m experiments.factory_evaluation_kit --run-dir runs/NEW-EVALUATION --phase verify
```

다른 snapshot을 사용하려면 먼저 그 snapshot용 raw-candidates plan/벡터를 만들고 `--snapshot --development-plan --vectors`로 함께 지정한다.
V0 후보는58개(3member1개/2member4개/단일53개),3개 이상 후보에 들어간 source3/64다. 의미 precision/유효 관점 coverage는 null이다.
assistant가 다인 후보5개를 읽었으며 물가 후보1개에는 좁은 공통 주장 가능성이 있다. 지지 count3을 자동 검증하거나 agent를 생성한 성과가 아니다.
복지 관련2개는 같은 주제지만 하나의 처방을 공동 지지한다고 보기 어렵고, 자동화 언급2개도 공통 입장으로 바로 묶을 수 없다.
이 표본만으로 embedding·clustering 전체의 적합성이나 V1/V2 필요성을 결론내리지 않는다.

private `runs/factory-evaluation-reset-20261013/overview.html`과 `assistant-calibration.html`에서 확인한다.
plan SHA `c2ecf136fcad514c82988c6245c788bc35cb48c73627c62f54a3be14a9622212`.
이 준비 artifact의 상태는 `comparison_ready=false`, `quality_gate_passed=false`, `agents=[]`다. 과거 artifact를 수정하지 않고 별도 matched plan을 동결했다.
