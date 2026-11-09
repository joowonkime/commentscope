# 원문 완전성과 후보 연결 실패를 분리하기

TASK-005, REQ-001/002/003/008/010. 기존 r5·원문·정산·역할·모델을 바꾸지 않는다.
현재 실행 중인 실제24개 checkout은 수정하지 않는다. 이 변경의 검증은 우선 무과금이다.

## 재현한 문제

저장된 G1의 B/C/G/I는 모델의 원문 coverage 관측이 모두 complete다.
owned_arguments의 `supported_candidate_without_owned_position`이 전체 source status를 unresolved로
만들어 다른 후보의 정상 단위와 동일 원문의 실제 지지도 함께 제외됐다.
원문 보존 실패와 특정 후보 소유권 실패는 영향 범위가 다르다.

## 계약

새 opt-in `candidate_verified_subset`은 기존 감사 영수증을 수정하지 않고 후보별 coverage projection을
만든다. 기존 `all_members`/`verified_subset`의 출력·기본값과 실패 동작은 유지한다.

- 입력: 검증된 linked owned-source record, 실제 core, 기존 typed source/owner/graph audit 전체.
  원문·기대 label·과거 좋은 응답을 새로 생성하지 않는다.
- source language/본문·구간·coverage 누락, syntax/type/귀속 미확정, 미해결 사실 전제는 계속 차단한다.
  legacy/untyped·알 수 없는 hold는 기존 전체 source 규칙으로 처리하며 승인으로 바꾸지 않는다.
- `supported_candidate_without_owned_position`과 `position_alignment_uncertain`만 실제 candidate ID와
  bound alignment에 따라 분리할 수 있다. 대상 자신의 소유 position이 없거나 alignment가 uncertain이면
  그 대상은 계속 보류한다. 문자열/특정 예제 ID 예외를 두지 않는다.
- source-only 관측이 complete이고 언어가 일치해야 한다. 그래프는 해당 core와 그 단위·필수 전제
  closure에 대해 기존 비교를 수행한다. 누락/오연결/미확정/잘못된 fact·소유권·core 유형은 계속 거절한다.
  기존 단위별 감사 veto도 유지한다. 따라서 더 세밀한 분리 가능성이 있어도 불확실한 단위를 구제하지 않는다.
- 각 대상의 실패 원인·원래 aggregate 상태·사용 audit/record hash를 별도 projection으로 남긴다.
  기존 source record/audit/모델 응답/미완성 상태/잘못된 raw support를 삭제하지 않는다.
- 최소3개 유효 source와 core-required 실패 전체 보류, 사실·조건·runtime 검사를 유지한다.
  후보별 분리는 지지 전파·사실 전제 삭제·Agent 수동 선택 권한이 아니다.

## 검증

정상: 같은 source의 한 후보에 own position이 없어도 다른 대상의 complete 관측/소유권/단위 검증은 유지한다.
부정: 실제 coverage incomplete, 해당 대상 own position 없음/불확실, 누락 필수 사실, owner/core/조건/귀속
오류, legacy/알 수 없는 source hold, 변조된 영수증은 구제하지 않는다. 기존 두 정책은 그대로다.

회귀 → 저장된 G1 전체 입력의 무료 compiler 재생 → 필수Factory 검사를 수행한다.
무료 재생은 새 formal G1 통과가 아니다. 잘못된 raw 지지가 남으면 r5는 계속 실패다.
현재 실제24개 결과와 이후의 host 재구성 결과도 별도 development artifact로 구별한다.

무료 전체G1 재구성은0→2Agent, 각5/3source를 확인했다. 원래 raw map은 동일하며 잘못된 지지3건은
여전히 남는다. 현재 실제24개는 논거 이전에 모든 후보가 지지0~1개라서 수정 전후 모두0Agent다.
두 실패를 혼동하지 않는다. 현재 실제 입력의 후보 수용/공통관점 형성은 별도 미해결이며,
이 변경으로 실제 댓글 Agent 생성이나 전체 MVP가 완료됐다고 보고하지 않는다.
