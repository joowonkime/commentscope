# 원문 문자열 선택과 host 주소 결합

TASK-022 / REQ-001·002·003·008·010. v4 실제19출처 Agent0의 후속 일반 구현 후보다.
기존 결과·지출을 보존하며 상위 Factory/Compiler/Runtime 책임과 합격 기준을 유지한다.

## v5 제안 계약

모델에게 Unicode 문자 위치를 계산시키지 않는다. source-evidence-graph-20261112-v5는
원문에서 그대로 복사한 quote와0부터 시작하는 occurrence를 받고 host가 canonical source_id/start/end를 만든다.
정확한 문자열 선택과 의미 해석은 모델의 책임, 주소 계산·범위·중복·일관성 검사는 host의 책임이다.
wire의 짧은 필드는 q=quote, n=occurrence, o=scope origin이며 canonical 주소에는 이 약어를 남기지 않는다.

- own_spans·edge cue·coverage·issue 증거는 자기 원문에서만 찾는다.
- scope anchor의 origin=unit은 해당 unit own_spans 안에서, source는 자기 전체 원문에서 찾는다.
  parent는 referent_refs에만 허용한다. 부모는 자기 주장·이유의 재료가 되지 않는다.
- occurrence는 지정 검색 영역의 정확한 일치들을 source/offset 순으로 정렬한0-based 순번이다.
  겹치는 일치도 포함한다. 없는 문자열·없는 순번·bool 순번·허용되지 않은 origin은 거절한다.
- 정규화·fuzzy 매칭·자동 문장 수리·숫자 위치 fallback은 없다. 한국어·emoji·결합문자도 원문 그대로다.
- unit envelope는 host가 자기 전체 원문으로 결합한다. 이는 문맥 접근 범위이며 그 전체를 해당 unit의
  주장/이유로 승인하지 않는다. literal own_spans·scope·전수 coverage·감사는 그대로 검증한다.
- coverage 전체 원문 구간은 {"whole_source":"own"}로 선택하고 host가 full interval을 결합한다.
  부분 partition은 quote로 표현한다. coverage 선언은 누락 없음의 승인이 아니며 auditor가 전체 원문을 검사한다.
- wire_output과 실제 요청 SHA를 보존하고 host가 파생한 canonical output을 함께 저장한다.
  검증은 wire_output을 다시 결합해 canonical output과 대조한다. v4 영수증/profile은 재사용하지 않는다.

제안 schema는 host가 이미 거절하는 유형 조합을 typing의 두 분기로 제한한다.
not_applicable과 실제 주장, propositional kind와 non_assertive/not_applicable strength 조합은 생성할 수 없다.
unknown/unresolved는 유지하고 감사나 host에서 보류한다. 명확한 답을 강요하지 않는다.

후보 dependency_edge_ids에는 required_premise_for/condition_for/necessary_condition_for ID만 노출한다.
core_required_fact_unit_ids에도 이미 host가 허용하는 실제 자기 factual assertion만 노출한다.
semantic reason·core dependence·alignment의 판정과 모든 source/candidate 검증은 유지한다.

## 무료·실제 검증

실제16개 과거 제안의 의미/주소를 유지한 무료 형식 비교에서 직접 quote는 총byte1.3% 감소,
q/n/o 압축은11.3% 감소(2개 증가)였다. catalog 원형은6.1% 증가했고512-ID enum은 wire 검사에서 거절됐다.
압축 catalog의 추가 이점은 직접 압축 대비약1.2%p라 catalog/새 참조 의존성은 폐기했다.
이는 같은 영상의16개 형식 비교이며 모델 비용·품질 개선이나3000개 일반화가 아니다. 과거 오류도 그대로 보존한다.

먼저 정확한 multilingual 결합·반복/겹침·parent 경계·없는 문구·변경 provenance·기존 정상/부정 회귀를 검사한다.
canonical 참고 주석은 명시적 annotation→wire encoder를 거쳐 새 binder로 만들며 실제 생성 호출로 보고하지 않는다.
무료 roundtrip은 원 주석이 맞았다는 검증이 아니다. 지난 실제 실패를 정상으로 재채점하지 않는다.

그 뒤 새 protocol·wire·자료·단계·가격을 고정한다. 생성은 기존 GPT5.2, 감사는 기존 Sol로 유지해
표현/형식 변경부터 구별한다. 검토 통제16→대표3→동일전체19의 등록 범위를 유지하고,
새 실행은 기존 누적150·동일 owner·원 최종14:45:28UTC·기존 비용/요청 수를 계승한다.
새 실행에는 failed_binding_no_retry-v1 정책을 auth/plan/handler SHA로 명시한다.
완료된 length 영수증·동일 checkpoint·정산 증명이 모두 맞을 때만 원 실패 응답을 binder에 반환한다.
반환은 승인이나 수리가 아니며 기존 binder가 거절한다. pending/unknown·다른 오류는 여전히 중단한다.
자료 등록 전 새 model dispatch는 없다. 단일 실패에 맞춘 유료 retry·지지 기준 완화·기한 연장은0이다.
독립 사람 gold/48 paired·전이·r5·3000규모·사용자 유용성은 별도다.

## 후속 Agent 변환

위 v5 graph/wire는 유지한다. 마지막 adapter는 [DEC-021 원문 조각 인용](SCOPED_SOURCE_QUOTES.md)의
독립 arguments-scoped-quotes-v1 계약으로 구별한다. 검증된 비사실 절의 바깥 한정어를
원문 조각과 생략 표시로 보존하며 원 v5 B/C 결과를 새 성공으로 덮어쓰지 않는다.
