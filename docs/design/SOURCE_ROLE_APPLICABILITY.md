# 발화 역할별 필드 적용과 원문 전체 보류

TASK-022 / REQ-001·003·010 / DEC-022. 구현·합성 검사·저장 응답 replay를 실제 품질 채택과 구별한다.

## 문제와 적용 범위

이전 C의 보류 그래프7개 중3개는 모델의 단위별 검사가 모두 pass였다.
2개는 mixed 주장을 포함해 분해/해석이 필요하다. 나머지1개는 명시적으로
not_applicable/question인 문맥 단위의 commitment=unclear와 polarity=unresolved만으로
전체 원문이 보류됐다. 이를 같은 문제로 취급하거나 모든 unknown을 무시하지 않는다.

| 역할 | 판정 의무 |
| --- | --- |
| 자기 주장·가치·예측·보고·인용된 명제 | 기존 type/commitment/strength/world/polarity/change/interpretation 검사 유지 |
| 조건절 | 기존 검사와 condition edge 유지. unclear가 단순 미적용인지 실제 귀속 불명인지 현재 응답으로 구별할 수 없어 계속 보류 |
| 명제가 아닌 질문·문맥 | 아래 닫힌 조건을 만족할 때 commitment와 polarity만 미적용으로 기록 |
| 반문·mixed·해석 불명 | 기존 보류. not_applicable로 강제 변경하지 않음 |

비명제 문맥의 조건: kind=not_applicable, speech_act=question/other,
assertion_mode=question/non_assertive, epistemic=not_applicable,
commitment는 endorsed가 아니며 interpretation=resolved다. 연결 관계는 elaborates/reported_by만
허용한다. 이유·조건·필수 전제·양보·반대 역할의 endpoint이면 문맥 예외를 적용하지 않고 보류한다.
world/change 등 나머지 필드와 단위별10개 감사·전체 coverage/누락/의존성 감사는 그대로 통과해야 한다.

Host는 원 선언을 변경하지 않고 verification_policy와 단위별 적용 의무를 별도 증거에 남긴다.
원 proposal/observation의 wire는 v5 그대로이며 새 검증 기록만 독립 policy 버전으로 구별한다.
구 policy의 verified/candidate/argument 기록을 현행 기록으로 자동 승인하지 않는다.
비명제 단위는 지지 입장·이유·필수 사실·runtime claim으로 승격할 수 없다.

## 검증과 기록 재사용

합성 정상/부정 사례로 비명제 질문, 반문, 명제 누락, 의미 감사 fail/unknown,
잘못된 이유/조건/사실 연결, 조건절의 unclear, stale policy와 변조를 확인한다.
기존 C의 전체14개 저장 그래프를 별도 출력으로 다시 검증한다. 구 wire 요청 SHA와 원 응답은
보존하고, 기존 후보 응답은 요청 내용이 정확히 같을 때만 별도 replay에서 재결합한다.
새로 완료된 그래프에 후보 검사가 없으면 pending으로 남기며 증서를 합성하지 않는다.
같은19개 실패 재호출·다른 arm의 성공 혼합·최소 지지3/Agent2/r5 완화는 없다.

이전 유료 실행의 원 종료시각은 지났다. 이번 작업은 무료이며 이전 plan/owner/기한을 연장하지 않는다.
새 질문 검증이나 확대 모델 실험은 별도 고정 범위·현재 금융 상태·유효 실행 계약을 먼저 작성한다.


## 무료 검증 결과

새 역할 검사8개·실행 정산 결합7개·기존 모델 요청 재사용 검사4개를 추가했다.
관련100개(7.825초), 전체 Factory884개(273.810초)를 통과했다.
기존 C의14개 그래프 전부와 원 provider 요청/응답을 대조해 재검증한 결과 완료7→8이다.
새로 완료된1개는 후보 관측이 없어 pending이며 증서를 만들지 않았다.
기존7개 논거 기록을 같은 wire의 원 응답으로 재결합하면 완료6개·Agent1개/유효 지지4개/허용 항목7개다.
이는 PR97의 무료 재변환과 **같은 Agent 수**다. 이번 역할 수정이 Agent 수를 늘렸다고 보고하지 않는다.
추가 모델 호출/청구0이며 새 runtime·독립 사람 gold·최소2 Agent·전체r5는 미검증/미달이다.
