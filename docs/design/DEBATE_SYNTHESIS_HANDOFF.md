# DS-v1 구현·검증 인계

TASK031의 설계 패킷이며 TASK032~037은 **todo / DEC029 수락 후 구현**이다.
수락 전에는 상세 검토·합성 예시 확인까지 수행한다. 이 문서가 구조나 유료 실행을 자가 승인하지 않는다.
처음에는 [선택표](DEBATE_SYNTHESIS.md#3-중앙에서-검토할-선택) →
[프로토콜](DEBATE_SYNTHESIS_PROTOCOL.md) → [API/저장/화면](DEBATE_SYNTHESIS_API.md)을 읽는다.

## 1. 인계 시 함께 줄 것

- 저장소·고정 설계 commit/PR·DEC029 수락 근거와 담당 Issue.
- 담당 TASK와 아래 변경 소유 범위·선행 작업·완료 조건.
- [합성 계약 예시](contracts/debate-synthesis-v1.examples.json)와
  [schema](contracts/debate-synthesis-v1.schema.json). 실제 댓글/키/DB/장부는 Git에 없음.
- 기존 [AGENTS](../../AGENTS.md), [협업 시작](../TEAM_START.md),
  [구현 기준](../IMPLEMENTATION_BASELINE.md), [현재 API](../PRODUCT_API.md).

기존 합성 `/mvp --seeded`는 과거 group/1:1/Reflect를 확인하는 화면이다.
새 structured debate/합의/통합 UI나 실제 모델 품질을 확인한 것으로 쓰지 않는다.
API/DB·새 Runtime과 위임받은 범위 외의 구조 변경은 통합 담당자에게 제안한다.

## 2. 작은 PR로 나눈 구현 순서

새 파일명은 책임 경계를 전달하기 위한 구현안이다. 함수 내부 구성은 계약 안에서 조정할 수 있다.
프로세스/저장/API/모델 역할을 새로 바꾸는 것은 다른 설계 변경이다.

| TASK | 예정 모듈·주 책임 | 선행 | 완료 조건 |
| --- | --- | --- | --- |
|032 계약/저장 | `product/debate_contracts.py`,`debate_store.py`;기존 `store.py` migration |031 및 DEC029 수락 | 타입·동적 alias·불변 참조 validator,같은 DB v1→v2,옛 기록/requests/jobs/restart 호환 |
|033 구조화 토론 | `agents/structured_runtime.py`,`product/debate_service.py`;`app.py`의 얇은 dispatch |032 | 고정 phase snapshot·원질문·명시 target,16질문 상한과제거후 coverage,API/start/control,부분실패·늦은응답 |
|034 합의/수락 | `agents/synthesis_proposal.py`,`synthesis_ratification.py`,`product/synthesis_service.py` |032 | 초안1회+검증1회,Agent별 봉인된 명시 수락+검증,명제별집계/no_consensus/hold·예산 |
|035 파생 Agent | `agents/synthesis_compiler.py`,`synthesis_runtime.py`,`product/synthesis_agents.py` |033·034 | 불변계보·새kind·직접댓글지지0,무료compile/cache,1:1/출처API·원Agent/legacy회귀 |
|036 프론트 | `product/debate_client.js`,`debate_ui.js`,기존`mvp.js/html/css`연결 또는 확정 팀프론트 adapter |032 계약 | capability·토론/합의/이견/생성/질문·source origin·Reflect·reload·오류/중복·확정디자인 대응 |
|037 통합/품질 | 관련 test/브라우저와별도실험계약 |027·033~036 | 정상·부정E2E·같은근거단일Agent대조·전체청구/시간·초행사용 QA. 단순CI를품질로승격하지않음 |

032 이후033/034/036은 확정 인터페이스와 합성 fixture로 병행할 수 있다.
035는 실제 토론·합의 산출물 경계를 연결하므로033/034 이후다.
`store.py`는032 담당,`app.py` 공통 dispatch는033 담당과 순서를 맞춰 수정한다.
034/036이 공통파일에 각자의 실행/상태 체계를 추가하지 않는다.
기존 `seeded_runtime.py`는 공개 계약을 유지하고 공통 순수 helper 추출이 필요하면 관련 회귀를 먼저 둔다.
옛 frozen 실행 checkout이나 private 원본을 직접 수정하지 않는다.

## 3. 정상·부정 완료 사례

다음은 구현 전 고정할 기대 동작이다. 합성 의미 판정은 미리 정한 관측이며 실제 Jev 정확도가 아니다.

| ID | 상황 | 기대 결과 |
| --- | --- | --- |
| V01 |2Agent가 조건이 명시된 같은후보를 유효accept |shared1,별도Agent1,원Agent불변·새직접댓글지지0 |
| V02 |합의후보2개 중1개만전원accept |독립shared1만compile,나머지거절/이견유지 |
| V03 |일부needs_condition/reject/undecided |해당후보미수락,조건추가를조용히가정하지않음 |
| V04 |모든후보명시미수락 |no_consensus보고서,새Agent0,오류/허위합의로표시하지않음 |
| V05 |검증hold/누락수락만있음 |verification_hold,의견불일치나합의로승격하지않음 |
| V06 |한후보조건/근거실패,다른후보유효 |실패범위격리. 독립shared를전역veto하지않음 |
| V07 |같은작성자중복source/같은ID반복accept |정규화/중복거절,AI동의로댓글지지증가금지 |
| V08 |quote만남아원질문/target미충족 |coverage incomplete,합의단계진입금지 |
| V09 |reply의targetID는맞지만내용은입장반복 |Jev task_fit 부정 관측이면 미충족. ID만으로 성공처리금지 |
| V10 |다른reply/미래seq/미게시초안참조 |scope/cutoff오류. 모든reply는동일opening만봄 |
| V11 |문헌범위/조건변조·새사실을AI논리로위장 |해당문단/명제보류,독립사실확인으로표시하지않음 |
| V12 |전송실패/검증실패/비용누락 |첫호출비용/이전게시보존,failed/reconciliation,자동재시도0 |
| V13 |새로고침/중복click/다른request_id같은snapshot |기존job/보고서/Agent재사용,새추론0 |
| V14 |다른세션/변조된parent/hash/draft |404또는무결성오류,비공개원문/결과노출금지 |
| V15 |자료수명/예산기한/사용자세션만료 |410/생성불가/401을구별. 기록권한/금융권한연장없음 |
| V16 |pause/close와요청이경쟁·재시작 |기존epoch/정산규칙,늦은게시금지·재전송0 |
| V17 |DBv1/legacybundle/기존방/Reflect |새기능비활성에서기존읽기/질문/저장/reload회귀통과 |
| V18 |통합Agent를새합의의부모로사용 |v1미지원거절,자기반복동의로계보/확신증폭금지 |
| V19 |한글/영문·Unicode한도·Jev28KB초과 |길이/byte를구분,필수내용조용히절단하지않음 |
| V20 |겹치는부모관점/실제Agent부족 |반대Agent합성금지. 중복가능성표시,가용수부족안내 |

기존 source fidelity·조건·필수 사실·금융 검사를 낮추지 않는다.
negative fixture를 통과시키기 위해 schema나 기대값을 현재 출력에 맞춰 바꾸지 않는다.
검증 실패가 정당했는지/과도했는지는 별도 모델·사람 평가에 남긴다.

## 4. 구현 PR의 증거와 검사

명세/참조·관련 단위검사·기존 Factory/제품회귀·JS/합성 Chromium을 변화에 맞게 수행한다.
실제 구현033~036은 새 API와 model callback이 synthetic임을 고정한 브라우저 흐름을 추가한다.
공통 case pack은 표준 라이브러리/저장소 검사기로 무료 확인한다.

```bash
python tools/check_mvp_spec.py
python docs/examples/check_debate_contracts.py
python -m unittest discover -s tests -p test_mvp_spec.py
```

이 설계 PR의 검사기는 계약 예시의 shape·참조·집계 규칙만 확인하며,
현재 product가 새 프로토콜을 실행한다는 뜻이 아니다. 구현되지 않은 endpoint를 호출하지 않는다.
합성 case의 지정된 의미 관측을 실제 모델/독립 human gold로 쓰지 않는다.
양OS CI는 해당 commit의 코드 회귀이며 DEC029 수락·새기능·전체MVP 승인이 아니다.
이 설계의 합성 계약 검사도 양OS workflow에 연결한다. 이는 제안/예시의 정합성만 확인하며
실제 API/Agent 구현이 이 계약을 지키는지는 TASK032~037에서 별도로 검사해야 한다.

## 5. 실제 비교 실험

이번 설계 작업의 모델 호출은0이다. 아래 실험은 입력·코드·예산·기한·평가를 별도로
고정/수락한 뒤 실행할 계획이다. 과거 만료 plan이나 팀 잔액을 새 권한으로 해석하지 않는다.

### 비교 arm과 공정성

| Arm | 조건 | 구별하려는 효과 |
| --- | --- | --- |
| A 원Agent |고정된부모1개,동일모델/질문 |기본체험기준. 근거범위차이가있어MAS원인비교로단독사용불가 |
| B 동일근거단일Agent |부모전원의동일허용원문/조건/문헌,토론없음 |정보를더준효과와MAS효과구별 |
| C 토론→파생Agent |같은부모/근거/모델에서DS-v1으로생성 |실제토론/명시수락/컴파일효과·추가비용 |

원문/문헌·초기관점·질문·모델/provider·총비용상한을 맞춘다.
실제 토큰/호출/시간은 같다고 가정하지 않고 모두 기록한다. B에 추가 reasoning budget을
부여하는 대조를 넣으려면 그 정책도 사전에 고정한다. 가격/정확도를 한 사례로 일반화하지 않는다.
C가 생성되지 않은 no_consensus/hold/실패도 분모와 비용에 포함한다.

### 표본·채점

개발 세트는 별도 준비한 질문12개(입장이유/반박4,조건전이4,외부근거한계2,미합의질문2)를
실행 전 고정한다. 한국어/영어·지지/조건부/실제충돌·합의없음 사례를 포함한다.
원댓글 전체군집 성능·독립 모델 정확도·3천댓글 성능과 구별한다.
암기된 질문/후보에만 맞춘 평가를 피하려면 확정 뒤 별도 held-out 질문을 마련한다.

평가자는 arm을 가린 답변과 출처로 다음을 각각 본다.

- 원댓글/문헌 충실도,조건·불확실성 보존,새로운 무근거 사실·작성자 귀속 오류.
- 질문과 반박 대상에 대한 실질 응답,quote만 남은 실패,정당한 보류/과도한 보류.
- 공통 명제의 유용성,이견 보존,원 Agent보다 이해하기 쉬운지.
- 독립 사람 검토 여부·평가자 수/불일치와 assistant/model 검토를 명확히 구분.

기존60%댓글활용 목표를 응답/판정 정확도60%로 바꾸지 않는다.
새 합격률/유의성/품질 문턱은 사용자가 수락한 별도 평가 계약에 둔다.
합성 critical 사례의 출처위조·타세션누출·중복청구·조건삭제는 각각0실패를 목표로 회귀한다.
작은 표본의 관측0을 서비스 전체 오류0으로 주장하지 않는다.

### 비용·속도 보고

생성준비비용(Factory) / 새토론 / 초안 / Agent별수락 / 검증 / 후속질문을 분리한다.
`C_total(Q)=C_factory+C_debate+C_synthesis+Q*C_followup`으로 cold와warm 비용을 함께 보고한다.
같은분석 재사용이 절약한 비용을새토론당원가와섞지않는다.
전체벽시계·첫발언시간·합의완료시간·후속응답의중앙값/최대와대기시간을기록한다.
후속질문은2호출 구조여도 실제지연을측정하기전 빠르다고약속하지않는다.

### TA 사용성

대본 밖의 자유질문,다른Agent선택,중복click,reload/뒤로가기,빈근거/합의없음,
pause/close,세션/자료만료,저장후재열람을 초행 사용자가 수행한다.
핵심과업을 막는 문제를 우선 기록하고 실제 참가자 결과와 합성 브라우저 검사를 구별한다.

## 6. 구현 AI에게 전달할 추가 문장

```text
담당 TASK/Issue의 구조 기준은 DEC029에서 수락한 DS-v1 고정 revision이다.
DEBATE_SYNTHESIS의 DS-01~10, PROTOCOL의 담당 P절, API의 담당 A절,
이 문서의 담당 TASK와 완료 사례를 읽고 구현해줘.
DEC029가 아직 proposed면 설계를 자가 수락하거나 기능 구현을 시작하지 마.
기존 계약 안의 내부 구현은 자율적으로 진행하고, 새로운 구조 변경은 근거와 대안을 제안해줘.
기존 Agent/legacy·API·Figma·private데이터·장부와 실패를 보존해줘.
합성 shape/집계 성공, 실제 모델 의미 품질, 사용자 QA와 전체MVP를 구별해줘.
```

이번에 팀원에게 넘길 것은 구조 검토 패킷이다. DS-01~10이 수락되면 담당 Issue에
설계절/commit·담당파일·선행PR·정상/실패기대를 연결해 구현 착수 패킷으로 사용한다.
