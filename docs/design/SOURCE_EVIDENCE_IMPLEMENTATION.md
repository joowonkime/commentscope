# 원문 증거 구조의 첫 구현과 확인 범위

이 문서는 PR91 당시 v1 구현/무료 검사 기록이다. 후속 실제 비교의 예산 중단·B1 미채택과
현재 무료 수정은 [비교 결과](SOURCE_EVIDENCE_TRIAL_RESULT.md)를 따른다. 아래 당시의 미실행 상태를 현재 실행 상태로 사용하지 않는다.
후속 v3의 현재 계약·무료 구현 범위는 [원문 대조 감사](SOURCE_FIDELITY_AUDIT.md)를 따른다.

연결: TASK-020/021, DEC-013, REQ-001/002/003/008/010.
기준: PR90의 설계, main `8777756db85c84e2f8886806bba498e51a6a64f6`.
**B1 opt-in 코드와 무료 합성 통합 검사 범위다. 실제999의 Agent 수·이유 품질이 개선됐다는 결과는 아니다.**

## 구현한 경계

| 모듈 | 동작 |
| --- | --- |
| `source_evidence_graph` | 원문 envelope·Unicode 구간·복수 의미 단위·scope·조건/이유/전제 관계·전체 문자 coverage의 closed schema와 재구성 검증 |
| 같은 모듈의 observer | 기존 type/commitment/edge/coverage 의미 label을 숨기고 원문과 span inventory를 다시 관측. 누락·불일치·필수관계 순환은 전체 source 보류 |
| `source_evidence_requests` | 최대8개 후보씩 source에 연결. 모든 이유/양보/조건·필수 의존 inventory를 대조하며 prior supported 판정을 모델에 주지 않음 |
| `source_evidence_adapter` | 새 version의 출처별 논거와 audit를 구성. 연속된 원문 fragment만 게시하고 표현 불가능한 단위는 보류. 개인 사실 전제와 core 자체의 사실 근거 분리 |
| 기존 Factory/Compiler | `source_evidence_protocol`을 명시한 shared/raw/full-scope 호출만 새 F4를 선택. 원문 지지·core fidelity·기존 fact 검사·최소지지·최종 Compiler 유지 |
| 비용/remote route | proposer는 generation, observer/후보 연결은 verification. 새 stage cap과 profile은 별도이며 기존 plan의 cap/가격을 빌리지 않음 |

새 artifact의 type/귀속/관계가 모델에 의해 관측됐다는 사실은 외부 사실의 참을 인증하지 않는다.
독립 관측은 unit 경계를 공유하는 별도 요청이며 통계적 오류 독립이나 사람 gold가 아니다.
`binding_checks.receipt_binding`은 이 계층에서 원래 논리 응답을 동일 request로 재구성했다는 뜻이다.
실제 wire/provider/model/사용량 영수증은 기존 X의 durable call·remote receipt 검사 책임이며,
graph 모듈이 그 검사를 새로 수행하거나 synthetic fixture에 실제 영수증이 있다고 주장하지 않는다.

## 기존 경로와 달라진 호출

새 opt-in은 graph proposal →독립 source observation →후보 연결 batch로 기존 node metadata·position alignment와
source owner/dependency/audit 의미 의무를 대응 교체한다. 이 source에 구형 F4 scalar 검사를 겹쳐 실행하지 않는다.
source graph가 미해결이면 후보 연결 호출도 생략하며 source 보류를 남긴다. 유료 자동 retry/repair는0이다.
legacy plan/protocol·이전 artifact·장부는 보존한다. 신규 version을 구형 parser graph처럼 위장하지 않는다.

지지 출처는 eligible 후보의 전체 supporting source 합집합이다. 좋은3개만 골라 새 경로를 통과시키지 않는다.
원문 이유를 편한 일부만 선택한 certificate는 보류한다. source 전체가 unresolved인 상태에서
무관해 보이는 unit을 제거해 합격시키는 B2는 포함하지 않는다.
기존 alignment projection은 legacy record에 그대로 적용된다. 신규 record는 source 전체 complete를 요구한다.

## 평가 자료 준비

`tools/prepare_source_evidence_review.py`는 모델 호출 없이 원실험 artifact에서 다음을 private 파일로 고정한다.

- 17개 논거 record/96단위·52개 map 관계,34 enum 오류와10 capacity event를 서로 다른 분모로 보존.
- 기존17개와 사전 규칙으로 고른31개를 합친 개발 source48개,thread가 겹치지 않는 전이 선정48개.
- source hash·층·이전 상세검토 여부·실패 기록을 보존. 첫 기록 hold를 실제 첫 원인이라고 단정하지 않음.
- 16개 공개 합성 통제: 변화/상태,조건,귀속,부모,가정세계,전제누락,policy bundle,수량/시점,Unicode 등.

개발48개 원문과 제공된 부모를 coding agent가 읽고 보존 의무·이유 존재 메모를 private annotation에 고정했다.
전이48개 원문은 이 검토에서 열지 않았다. 전이는 기존 discovery가 읽은 같은 corpus이므로 unseen-domain이 아니다.
coding-agent 메모는 independent human gold가 아니며 원인별 영향도를 입증하지 않는다.
**후보별 support/관계 정답과 R 분모는 아직 완성하지 않았고 semantic_benchmark_ready=false다.**
TASK-022의 모델 비교 전에는 이 정답·검토 provenance·정확한 wire/가격·상한/기한을 동결해야 한다.
선정/기대 source 보존 메모의 완료와 유료 benchmark 준비 완료를 구별한다.

## 무료 검사와 남은 실제 검증

새 회귀는 다음 동작을 검사한다.

- 원문 변조·부모 evidence·coverage 누락·missing observation·unknown ID·용량 초과·Unicode offset 거절.
- proposal/observer의 type·scope·edge 불일치와 숨겨진 필수 전제 보류.
- source-owned reason 누락·부당한 core factual premise 승격 보류.
- 개인 factual premise가 개인 이유에 남고 core의 공통 전제로 합쳐지지 않음.
- 불연속 literal 조합을 새 문장으로 만들지 않고 unrepresentable_hold 처리.
- 단일 조건은 scope annotation으로 보존하고,flat scope로 의미 손실이 생기는 중첩 조건은 보류.
- Jev M1과 M2를 유지한 전체 합성 Factory에서2 Agent/각3지지와 실제 source-owned 이유 연결.
- M2 veto·source 미해결·이유 누락 때 Agent 게시 차단,구형 F4 중복 호출 없음.
- 새 stage의 profile/cap 미존재를0달러나 legacy Sol 가격으로 채우지 않음.

이는 합성 모델 응답의 통합 검사다. 실제 모델의 분해·관측·일치/보류 비율,실제 이유 보존,
유효 source/candidate 회복,동일5달러 제안한도 내 비교 가능성,전체999/3000 비용·속도는 미검증이다.
graph record가 더 풍부해진 만큼 실제 의미 오류와 비용은 함께 측정해야 한다.
현재 frozen paid-runner plan은 기존 형식이며 새 opt-in으로 자동 변경하지 않았다.
새 source-evidence 실행 plan과 measured profiles를 TASK-022에서 등록하기 전에는 유료 whole run을 시작하지 않는다.

구현 검증: Factory775개 후 조건 변환 회귀를 더한778개가393.717초에 통과했다.
이후 실제 strict wire 구성에서 numeric minimum schema 비호환을 발견해 숫자 범위를 host에서 검증하도록
전송 schema를 수정했고,새 wire 회귀를 포함한 관련81개가10.754초에 통과했다(중복 포함).
최종 신규 검사는20개다. 개발 원문48개의 proposal 요청을 과거 동결 generation/Sol deployment로
구성했을 때48개 모두 용량에 적합했다. 최대 입력 byte 기반 token 상한29975이며 실제 tokenization/모델 응답이 아니다.
observer/후보 요청도 실제 strict wire schema 구성 회귀를 통과했다. 신규 모델 호출0회.
이 증거는 실제 모델이 올바르게 분해하거나 제한 출력 안에 모두 응답할 것이라는 증명이 아니다.

## 재개

AGENTS →MVP_SPEC →SPEC_WORKFLOW →`PYTHONPATH=src:tests:. python tools/check_mvp_spec.py --resume`.
구현/회귀 결과와 정확한 다음 TASK 상태는 `mvp-traceability.json`이 정본이다.
이전999 실행의 deadline은 만료된 상태로 보존하며 이번 코드 수정은 그 실행의 재개가 아니다.
