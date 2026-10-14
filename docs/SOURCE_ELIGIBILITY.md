# 원문만 보는 주장 자격 검사 비교

독립적인 주장이 있는지 판단하는 자격 검사와 특정 target을 지지하는지 판단하는 충실성 검사를 분리한다.
기존 합동 감사가 질문·단순 반응까지 승인한 문제를 대상으로 한 opt-in 실험이며, 기본 Factory나 원문 registry를 변경하지 않는다.

## 사전 고정 대조

기존 evidence-unit16개와 새로운 대비16개, 총32고유 원문을 사용한다. 각 군은 정상8/제외8이다.
새 대비는 질문/진술, 해결된/미해결 지시어, 명시된/생략된 권고, 영상 의견/도착 반응, 주장/인용,
질문에 경험이 섞인 댓글, 농담에 실제 주장이 섞인 댓글, 한국어2개를 포함한다.
모든 기대는 추론 전에 고정한 assistant 개발 라벨이다. 알려진 실패를 보고 작성했으므로 독립 holdout이 아니다.

| 조건 | 입력 | 출력 |
|---|---|---|
| joint | SOURCE와 동일 문자열 TARGET | 기존 assertion/eligibility/6속성/evidence |
| eligibility_with_target | SOURCE와 동일 문자열 TARGET | eligibility만 |
| source_only | SOURCE만 | eligibility만 |

뒤 두 조건은 system/schema가 같고 입력의 TARGET 필드만 다르다. 둘 다 TARGET은 자격 근거가 아니라고 명시한다.
joint와 자격 전용의 차이는 prompt/schema/역할 명료화가 함께 바뀐 **분리 패키지 효과**다.
그 결과를 TARGET 제거 하나의 인과 효과로 설명하지 않는다. 혼합 댓글에서 최소 한 독립 주장이 있는지 보는 정책도 명시했다.

각 조건을 새4B 서버에서32회씩 총96회 실행한다. 조건 순서는 표 순서, source 순서는 ID 정렬로 고정한다.
지난 모델 비교의 Qwen3-4B-Instruct-2507 Q4_K_M/revision/hash/llama.cpp b11541을 유지한다.
양쪽 전용 검사와 joint 모두 context4096/GPU26layers/CPU6threads/parallel1/cache-off/non-thinking,
temperature0/seed407/max_tokens900이다. 새 모델 다운로드/추가 수집/외부 댓글 전송은 없다.
조건당600초를 호출 전에 확인하며 진행 중 요청에는 기존180초 timeout이 적용된다. 재시도·repair·부분 실행 재개는 없다.

## 모듈과 판정 경계

`factory/source_eligibility.py`는 SOURCE만 받는 요청 생성, 엄격한 단일 enum 검증, host 상태 매핑을 제공한다.
원문4,000자/80segments 한도를 넘으면 잘라 쓰지 않고 거절한다. 기대 라벨/다른 댓글/후보 target은 입력하지 않는다.
자격은 substantive→eligible, non_substantive→excluded, context_dependent→동명 보류, unclear→uncertain이다.
형식·전송 오류는 error이며 미확정을 승인하거나 맞게 제외한 것으로 세지 않는다.

비교의 주 지표는 **eligibility 필드**다. joint의 전체 projection이 충실성 이유로 실패해도 자격을 잘 분류했다고 세지 않는다.
자격 통과는 target 지지나 agent 승인이 아니다. 여러 문장이 있는 댓글의 자격 통과는 그 안의 모든 문장 자격을 보장하지 않는다.
원문은 검사 결과와 관계없이 보존한다. 이번 코드에는 corpus 필터/지지 집계/서비스 cache 연결이 없다.
`identity`는 source·모델 식별정보·prompt/schema/version에 결합한 향후 재사용 키이며 실제 cache 구현이나 채택은 아니다.
실제 연결 시 모델 식별정보에는 가중치 hash/revision/양자화와 실행 프로파일까지 포함해야 한다. 모델명만으로 환경 간 결과를 공유하지 않는다.

## 사전 통과 기준

source_only가 기존 정상8/8, 새 대비 정상7/8 이상을 보존하고 두 군에서 제외 대상 오승인0·오류0이면
**다음 실제 데이터 시험의 후보 자격만** 얻는다. 사람이 서비스 중 승인하는 단계나 자동 품질 승격을 추가하지 않는다.
전용 검사 간 label 변화와 원문별 실패를 전수 공개한다. 통과해도 새 실제 표본·원문별 재사용·전체 충실성 경로 연결은 별도 검증이다.
기존 OpenJev typed routing 실패와 별도이며 같은 문제를 해결했다고 미리 가정하지 않는다.

## 실행과 재생

기존 private 모델 비교 plan과 로컬4B/런타임이 필요하다. 모델 기동/종료는 이전 소유 서버 helper를 재사용한다.
이미 실행 중인 localhost8091 서버에는 접속하지 않고 실패하며, 자신이 생성한 서버만 종료한다.

```bash
python -m experiments.source_eligibility_probe --run-dir runs/NEW-ELIGIBILITY --phase plan --diagnostic-only
python -m experiments.source_eligibility_probe --run-dir runs/NEW-ELIGIBILITY --phase run --diagnostic-only
python -m experiments.source_eligibility_probe --run-dir runs/NEW-ELIGIBILITY --phase verify --diagnostic-only
```

private plan/attempt/report는 원문·출력과 code/model hash를 결합하고 snapshot 만료를 상속한다.
verify는 새 추론0으로 요청·순서·출력·집계를 재계산한다. overview.html에서32원문/96출력을 확인한다.
공개 저장소에는 코드·합성 fixture·설계·집계만 저장한다.

## 실행 결과 2026-10-13

추론 전 코드 `aefc313`, private `runs/source-eligibility-20261013/`.
plan SHA256 `85912421d23263603cf3077eafc05577cefcfcc63b0a75d847270f37fcd73ca3`,
report SHA256 `8410b20422bcb1c9507158e2e8bd2671e4288b8447e997d10a296895d3fbd658`.

| 조건 | 기존 정상 보존 | 기존 제외 오승인 | 새 대비 정상 보존 | 새 대비 제외 오승인 | 추론 합 |
|---|---:|---:|---:|---:|---:|
| joint | 8/8 | 8/8 | 8/8 | 8/8 | 180.91초 |
| 자격 전용·TARGET 있음 | 8/8 | 7/8 | 7/8 | 5/8 | 22.37초 |
| 자격 전용·SOURCE만 | 8/8 | 5/8 | 7/8 | 4/8 | 22.75초 |

총96회 실제 추론, 오류/repair/재시도0. source-only는 정상15/16을 남기고 부정 오승인은16/16→9/16으로 줄였지만
**사전 오승인0 기준을 실패했다. 실제 표본 시험 후보나 기본 필터로 승격하지 않는다.**
정상 보존은 두 군의 사전 기준을 충족했지만 이것만으로 통과 처리하지 않는다.

joint→자격 전용 with-target에서5개 label이 달라졌다. 도착 반응2개·순수 농담1개·질문1개를 제외했지만
질문+경험의 혼합 댓글1개도 잘못 제외했다. 이 변화는 prompt/schema/정책 명료화를 묶은 효과다.
자격 전용의 system/schema를 유지하고 TARGET 필드만 제거하면 기존 농담1개와 질문2개가 추가로 제외됐다.
이3개는 입력 존재에 따른 차이이며 모델 내부의 판단 이유나 일반적인 target 편향의 증명은 아니다.

출력 token 합은 joint3392/전용 with-target325/source-only328이다. 자격 전용은 출력과 작업 범위가 작아 더 짧게 실행됐다.
세 조건의 추론 합226.02초이며 시작/파일 hash/저장은 제외다. **전체 감사·clustering이 약8배 빨라졌다는 뜻이 아니다.**
성능 비교는 같은 부분GPU 실행의 이32개에 한정한다.

## 남은 오류와 원문 검토

32원문/96출력을 assistant가 대조했다. source-only의 남은 오승인9개는 미해결 지시 대상8개와 독립 인용1개다.

- 단순 동의의 대상, it/that/they가 가리키는 주장·행동·주체를 원문 안에서 찾을 수 없는8개를 substantive로 승인했다.
  한국어 단순 동의1개도 포함된다. 문맥 안에 선행 내용이 있는 정상2개도 살렸으므로 모든 대명사를 막는 규칙은 적절하지 않다.
- 독립 인용1개를 author-endorsed 주장으로 승인했다. 인용이 곧 저자 동의라는 정책으로 바꾸지 않는다.
- 질문 뒤에 하루 통근 시간이2시간이라는 명시적 경험이 붙은 정상1개를 전용 두 조건 모두 제외했다.
  댓글 하나를 한 enum으로 판단하는 방식은 혼합 발화에서 정상 구간을 잃을 수 있다.
- 순수 농담은 제외하면서 명시적 임대료 인상 경험에 농담이 섞인 정상은 남겼다.
  이 대비의 성공을 모든 농담/다국어/장문으로 일반화하지 않는다.
- 전용 두 조건에서 context_dependent/unclear 출력은0개다. 스키마에 상태가 있어도 의미적 보류를 제대로 사용하는 것은 아니다.

모든 source-only 요청에서 TARGET/라벨 없는 정확한 SOURCE를 확인했다. 세 서버의 모델 경로·library hash가 일치했고
cached_tokens0/nonempty reasoning_content0, 소유 서버3개 모두 종료코드0·종료 확인했다.
저장96개 재생은 추가 모델 호출0으로 보고서와 일치했다. Python433/Node4 및 Linux·Windows CI 통과.
추가 수집·모델 다운로드·외부 댓글 전송0, 새 agent0/기본 변경0. 모듈은 opt-in 계약만 제공하고 서비스 cache/필터는 연결하지 않았다.

## 다음 구현 경계

단일 enum의 자격 판정을 반복 수정하는 대신, 남은 오류를 **발화 구간**과 **원문 안의 지시 대상 결합**으로 나눠 검사하는
최소 구조의 설계가 다음이다. 질문+경험에서 독립 주장 구간을 보존하고, 필요한 지시 대상이나 인용의 저자 동의 근거를
원문 위치로 제시할 수 없는 경우 승격하지 않는 계약을 검토한다. 위치 일치만으로 의미 해결을 증명할 수는 없다.
대명사·물음표·인용부호를 일괄 제외하는 단어 규칙이나 사례별 예외표는 채택하지 않는다.

이 구조가 이번 오류를 해결한다는 것은 아직 가설이다. 구현 전 원문 위치·실패 상태·예산·대비 사례를 먼저 고정해야 한다.
생성기/후보 선택기/충실성 감사는 바꾸지 않고, 이 source-only 모듈을 통과한 필터처럼 연결하지 않는다.
