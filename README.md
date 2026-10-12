# CommentScope

한 영상의 sampled comments에서 서로 다른 관점과 근거를 탐색하는 연구용 프로젝트입니다.

기존 **공식 API 표본 → 검수 지원 개발용 에이전트 → 로컬 비교/질의 UI**에 더해,
**수동 검수 파일 없는 자동 주장 추출 → 후보 검색 → 의미 검사 → 잠정 에이전트 생성** 경로를 추가했습니다.
자동 실행과 모델 품질 검증은 별개입니다. 정식 품질 승인·에이전트 간 토론·논문 평가가 끝난 것은 아닙니다.
실제 corpus와 실행 출력은 공개 저장소에 포함하지 않습니다.
이어서 작업할 때는 [다음 세션 시작점](docs/NEXT_SESSION.md)을 먼저 확인합니다.

**최신 검증 — 사실 판정과 선택형 답변 부품:** 고정40건(실제 문서30·합성 충돌10)에서 로컬 NLI가 지원9/10을 보존하고
비지원 오승인0/30을 기록했습니다. 합성 관점2개에 대한 실제 로컬 모델 답변 선택은 답변20/20·보류20/20,
비교20회 P95 10.27초였습니다. [측정 범위·실패·개선·남은 기준](docs/MVP_ACCEPTANCE_STATUS.md).
이는 독립 gold나 실제 댓글 agent 생성 완료가 아닙니다. 자동 원문 지지·유형/전제 추출·자료 검색·새 UI 통합은 남아 있습니다.
모델은 허용 claim ID만 선택하고 프로그램이 저장된 문장·출처를 표시하는 경로로, 자유 생성 후 감사하는 경로와 구분합니다.

**기반 구현 — 주요 사실 근거와 에이전트 입력 분리:** 원문 지지 검사와 사실 검사를 분리하고,
자료와 결합된 판정 기록 → 허용된 주장만 담는 입력 조립을 추가했습니다. 미검증·반박된 사실은 입력에서 제외하며,
주요 사실 근거가 모두 탈락하면 후보를 보류합니다. [구조·정책·실행 예제·남은 단계](docs/FACT_GROUNDED_AGENTS.md).
합성 예제 5개와 새 회귀 테스트 34개로 계약 동작을 확인했습니다. 실제 팩트 판정 성능이나 자동 MVP 완성을 뜻하지 않습니다.
제한된 실제 문서 확보와 독립 선택형 답변은 구현됐지만 자동 검색·Factory adapter·새 UI 연결은 없고, 기존 기본 경로는 변경하지 않았습니다.

모델·API 키 없이 새 입력 경계를 확인하려면 설치 후 아래 명령을 실행하고 출력 폴더의 `overview.html`을 엽니다.
모든 자료와 판정은 합성 예제이며 재실행은 다른 출력 폴더를 지정합니다.

```bash
python -m experiments.grounding_contract_demo --output-dir runs/fact-grounding-demo
```

**최신 구조 분리 비교:** 기존64개 추출·검색 결과에서 고정 주장24개와 원문 관계72개를 검사했습니다.
물가3댓글을 한 주장에 모았지만 일부 원문만 말한 부연까지 공통 지지로 승인해 **기본 채택에 실패했습니다.**
추론 합195.09초·오류0이며 영상 전체 처리 시간이 아닙니다. 충실한3-source 이상 카드0·새 agent0입니다.
[현재 구조·중단 경계](docs/CURRENT_ARCHITECTURE.md) · [설계·결과·재현](docs/FIXED_CORE_COMPARISON.md).
private 전체 검토는 `runs/fixed-core-20261013/assistant-review.html`입니다. 약속한 개선 비교1회를 마쳤고 같은4B prompt/auditor 반복은 중단합니다.
예약 표본 확대나 새 자동 agent 연결을 하지 않았습니다. 기존 review-assisted2-agent 데모와 무인 자동 MVP 완료는 구분합니다.

**이전 실제64개 비교:** 원문 기반(V0), 주장 기반(V1), 같은 V1에 감사 추가(V2)를135회 fresh 로컬 호출로 비교했습니다.
카드6/15/10개를 만들었지만 assistant 원문 검토상 충실한3-source 이상 카드는 모두0개로 **기본 채택을 보류합니다.**
반대 입장 오가입, 공통 주장 과분할, 상세 이유의 출처 이동을 분리해 확인했습니다. 형식 테스트 통과와 의미 품질은 다릅니다.
[현재 구조·채택 상태](docs/CURRENT_ARCHITECTURE.md) · [실측·실패·다음 변경 경계](docs/MATCHED_FACTORY_COMPARISON.md).
private 화면은 `runs/matched-factory-20261013/assistant-review.html`입니다. 평가가 독립 gold이거나 자동 MVP가 완성됐다는 뜻은 아닙니다.
예약64개·전체1,000개 재실행·새 agent 승격은 하지 않았습니다.

**이전 원문 위치 근거 비교:** 같은4B로48원문×2조건=96회 실행했습니다.
정상 source 통과23/24→5/24, 제외 오승인15/24→1/24로 정상 손실이 커져 **이번 구조는 채택하지 않습니다.**
통과한 정상5개도 선택된 근거가 불완전했습니다. 위치 일치가 의미 정확성을 보장하지 않는 한계를 확인했습니다.
[계약·실패 분석·다음 경계](docs/ELIGIBILITY_WITNESS.md). private 요약은 `runs/eligibility-witness-20261013/review.html`입니다.
기본 변경·새 agent0, 자동 MVP 품질 미완료입니다.

**이전 원문 자격 분리 대조:** 기존4B로32원문×3조건=96회 실제 비교했습니다.
합동 검사→자격 전용→원문 전용에서 제외 오승인16/16→12/16→9/16으로 줄었지만 정상도16/16→15/16으로 줄었습니다.
미해결 지시 대상·독립 인용 오승인과 혼합 댓글 손실이 남아 **기본 필터로 연결하지 않았습니다.**
[설계·실측·실패·다음 경계](docs/SOURCE_ELIGIBILITY.md). private 요약은 `runs/source-eligibility-20261013/review.html`입니다.
새 agent0개, 자동 MVP 품질 미완료입니다.

**이전 로컬 판정기 모델 비교(10월13일):** 같은39요청으로4B·8B를78회 실제 비교했습니다.
8B는 반복군 정상 보존7/10→10/10, 의미 추가 오승인2/2→1/2로 일부 개선됐습니다.
하지만 독립 주장이 아닌 제외8개를 두 모델 모두 통과시켜 **기본 교체 기준에 실패**했습니다.
[설계·실측·검토·다음 경계](docs/AUDIT_MODEL_COMPARISON.md). private 요약은 `runs/audit-model-comparison-20261012/review.html`입니다.
후보/생성기/기본 경로는 유지하며 새 agent0개입니다. 자동 MVP 품질은 아직 미완료입니다.

**이전 판정기 반복성 진단:** 같은12요청을 캐시 켬/끔·연속/교차 순서로144회 새로 추론했습니다.
요청별 출력은 모두 같았지만 정상6/10만 잠정 지지, 부정2/2는 계속 오승인했습니다.
캐시 변경으로 해결되지 않았고 기존 실행 간 변동의 원인도 확정하지 못했습니다. 다음은 선택기를 고정한 판정기 교체 비교입니다.
[설계·결과·재현](docs/AUDIT_REPEATABILITY.md). private 요약은 `runs/audit-repeatability-20261012/review.html`입니다.
**기본 변경·새 agent 생성 없음. 자동 MVP 품질 미완료입니다.**

**이전 원문 문장 후보 baseline:** 생성 제안 없이 문장을 직접 선택해 실제 핵심 구간3/3쌍을 양쪽1순위로 보존했습니다.
그러나 실제 양쪽 지지 통과0/3, 합성 정상2/6·부정 오통과0/6으로 판정/문장 단위의 한계가 남았습니다.
통과한 합성3target은 원문 대조도 충실했습니다. 같은 감사 요청의 실행 간 출력 변화도1건 발견해 반복성 검증이 우선입니다.
[계약·실측·실패·다음 경계](docs/EXTRACTIVE_CANDIDATES.md). private 검토는 `runs/extractive-candidates-20261012/review.html`입니다.
**기본 경로 변경·새 agent 생성 없음. 자동 MVP 품질 미완료입니다.**

**이전 생성·판정 분리 진단:** 같은 모델·프롬프트에서 전체 원문/자동 구간/사전 선택 구간을 비교했습니다.
실제3쌍 중1쌍은 충실한 생성과 양쪽 원문 검사가 가능했지만 자동 구간 선택에서 소실됐습니다.
정상 합성6쌍은 기준 주장을 직접 줘도2쌍만 통과했고, 조건 범위를 넓힌 생성 문장도 오승인했습니다.
선택기와 판정기 각각의 병목을 확인했으며 **기본 변경·새 agent 생성은 하지 않았습니다.**
[분리 결과·다음 구현 경계](docs/COMPONENT_ISOLATION.md). private 화면은 `runs/component-isolation-20261012/review.html`입니다.

**이전 위치 기반 근거·코드 판정 진단:** 원문 위치 결합과 host 판정을 구현하고 고정 회귀를 실행했습니다.
직접37개 계약 오류4→0이지만 정상 보존15/20→10/20, 의미 오승인1→2로 품질이 악화됐습니다.
실제 정상3쌍 양쪽 통과0/3으로 **기본 채택·전체 확장·새 agent 생성을 보류**합니다.
[결과·원인·다음 비교 경계](docs/POSITIONAL_SUPPORT.md). private 화면은 `runs/positional-support-20261012/overview.html`입니다.

**이전 원문 공통 주장·지지 검사:** 저장된 실제64쌍의 실행과 모델 재호출0회 재생 검증을 완료했습니다.
공통 주장 통과0개이며 정상 과잉거절·응답 계약 오류·개별 지지 오승인이 남았습니다.
지지 집계 코드는 구현했지만 실제 지지 범위 확대와 새 agent 생성은 보류했습니다. 자동 MVP 품질 완료가 아닙니다.
[수치·원인·재현·다음 수정 경계](docs/RAW_SUPPORT_MVP.md). private 결과 화면은 `runs/raw-support-20261012/review.html`입니다.

**이전 원문 검색 우선 경로:** 실제64개를 추출/의미 필터 전에 보존하고 검색 후보764개·비교 대기64쌍을 만들었습니다.
이전에 추출에서 소실된 개발 정상3쌍은 모두 검색·대기 목록에 남았습니다. CPU 임베딩 로딩 포함21.06초이며
공통 주장·지지 수·agent 생성 시간은 아닙니다. 새 agent0개/지지 수 미산정, 기본 Factory0.2는 유지합니다.
[지지도·시간 계약, 실행 결과, 재현법](docs/RAW_RETRIEVAL_MVP.md). 의미 판정과 자동 agent MVP는 아직 미완료입니다.

**이전 원문 위치·문맥·검색 검증:** topic을 원문 ID로 선택하게 하고 저장 evidence만 보는 검사를 분리했습니다.
고정 정상7/8·제외7/8로 개선되지 않았고, 확인8units 중 문맥/지시 대상 실패3개가 남아 기본 채택하지 않았습니다.
같은29댓글의 기존 정상3쌍은 원문 검색3/3→추출 후 source 잔존0/3입니다. 이번 대조군의 손실은 검색 이전에 발생했습니다.
[원인·실패·재현·다음 설계 경계](docs/EVIDENCE_POSITIONS_DIAGNOSTIC.md). 새 agent 생성/전체1,000개 재실행은 하지 않았습니다.

**이전 로컬 OpenJev 비교:** 기존 DeBERTa와 같은 입력53개를 실제 비교했습니다. 합성 왜곡 비승인6/12→12/12지만
정상 조건 동의어1개를 새로 과잉거절했고, 실제 의미 추가2개는 두 모델 모두 오승인했습니다.
TypeSafe 상용 Jev 시험이 아니며 **기본 교체·새 agent 생성 없이 진단으로 보존**합니다.
[결과·분류 계약·별도 환경 설치·재현법](docs/OPENJEV_COMPARISON.md). 실제 댓글은 외부 API로 전송하지 않았습니다.

**이전 원문 선택과 실행 계약 검증:** 모델의 주장 재작성을 원문 위치 선택·코드 복사로 분리했습니다.
같은 모델·고정 표본에서 선택 단계의 schema를 모델에게도 보여주자 정상 보존1/8→7/8이지만 제외 차단8/8→7/8입니다.
실제64개→59units, 자동 밀집32개→22units이며 **두 조립 모두 새 agent0개**입니다. 의미 품질·자동 생성 MVP 미완료입니다.
[원인·수정·검증·재현 방법](docs/EVIDENCE_SELECTION_DIAGNOSTIC.md). 기본 Factory0.2와 main은 유지합니다.

**이전 검색과 방향성 검사:** 후보 검색의 유형 제한을 분리하고 원문→대표 문장의 의미 보존·명시적 조건/시점 검사와 별도 평가를 구현했습니다.
동일123claims의 검색 후보 보유25→45개, 혼합 검색123개이지만 실제64개 조립은 **새 agent0개 / 검사 예산 소진**입니다.
별도12개 댓글에서도 새 의미 추가와 독립 주장 판정 실패가 발견돼 **기본 채택하지 않았습니다.**
[최신 결과·실패·재현 명령](docs/AUTOMATIC_FACTORY.md#검색과-방향성-검사-2026-10-12).

**이전 공통 주장 탐색:** 시간/표현 강도 검사, 공통 주장 후보→원문 검증, 고정 core 직접 배정과 진단 profile 연결을 구현했습니다.
고정 실제 정상6/7·오류11/11이지만 과잉거절/뉘앙스 문제가 남고,64개 기능 진단은 **새 agent0개**입니다.
품질 미완료이며 기본 경로는 유지합니다. [현재 구현·실패·재현 명령](docs/AUTOMATIC_FACTORY.md#공통-주장-탐색과-시점-보존-2026-10-12).

**이전 직접 지지 판정 비교:** 로컬 NLI는 합성 정상7/7·실제 정상5/7을 유지했지만, 시점 혼합과 과잉거절이 남았습니다.
실제 정상에서 anchor 자체를 제외하면1/3유지입니다. **기본 적용/새 agent 생성 없이 개발 비교로 보존**했습니다.
[판정 방식과 결과](docs/LOCAL_NLI_COMPARISON.md#최신-원문-span과-claim-비교)를 확인하세요.

**이전 호환성 검사 실험:** 범위·시점·표현 강도·조건을 구조화하는 교체 가능 모듈과 재현 검사를 추가했습니다.
실제 로컬 모델 시험에서는 정상 재표현도 과잉 차단해 **기본 경로에 채택하지 않았습니다.**
기본은0.2이며0.3은 `--experimental-frame-guard` 실험 옵션입니다.
[수치와 실패 원인](docs/AUTOMATIC_FACTORY.md#호환성-필드-실험-2026-10-11-기본-미채택)을 확인하세요.

**0.2 보완:** 부모 텍스트와 생성 라벨이 원문 검사에 섞이지 않도록 입력·감사를 분리했습니다.
기존 부모 전이7개는 원문 검사에서 모두 차단됐지만, 새64개 통합 실행은 agent0개이고
한국어 답변의 의미 변화도 남았습니다. **품질 완료 아님.** [원문 격리 회귀 결과](docs/AUTOMATIC_FACTORY.md#2026-10-11-원문-격리-회귀-결과).

**0.1 실제 자동 실행:** 댓글1,000개(중복 제외999) → 주장1,829개 → 잠정 agent8개까지
수동 개입 없이 연결했습니다. 그러나 반영 원문은27개(2.7%)이고, 사후 assistant 표본5개 묶음 중
4개에서 원문 충실성/공통 주장 지지 실패가 발견됐습니다. **생성 MVP 품질 완료가 아닙니다.**
[실행·실패 기록](docs/AUTOMATIC_FACTORY.md#2026-10-11-실제-전체-snapshot-실행-기능-연결-품질-실패)을 확인하세요.
자동 경로는 [Draft PR #21](https://github.com/joowonkime/commentscope/pull/21)이며 main 반영 전입니다.

## 현재 기준선과 완료 상태

`main`은 **검수 지원 입력을 사용하는 로컬 연구 프로토타입**의 통합 기준선으로 관리합니다.
main 반영은 코드 통합이지 모델 품질 승인·실험 성공·제품 완성을 뜻하지 않습니다.
[통합 PR #18](https://github.com/joowonkime/commentscope/pull/18)은 merge commit `a3ead01`로 반영됐고,
[남은 시스템 작업 #19](https://github.com/joowonkime/commentscope/issues/19)에서 다음 작업을 확인할 수 있습니다.

| 구간 | 현재 상태 | 남은 경계 |
| --- | --- | --- |
| 영상 → 댓글 수집 | 공식 API로 1,000개 표본 확보·검증 완료 | 전체 댓글 수집이나 대표성 보장 아님 |
| 댓글 → 주장/cluster | 후보 생성·검수 도구 및 여러 비교 실험 구현 | 자동 의미 품질 미해결, 전체 1,000개 자동 성공 아님 |
| 수동 개입 없는 자동 생성 | 전체 snapshot에서 잠정8개 생성·실제 브라우저 질의 확인 (PR #21) | 원문 coverage2.7%; 부모 내용 전이·scope 혼합 등 품질 실패, main 승격 전 |
| 검수 묶음 → agent | 검수된 21개 중 필요성7/예측4로 개발 agent 2개 생성·실행 | assistant 검수에 의존; 정식 승인 PerspectiveSpec 0개 |
| agent → 근거 답변 | 독립 evidence/history, 검사·1회 수정·보류, 인용 연결 구현 | 동일 모델 감사의 오승인/과잉거절·설명 오류 위험 |
| 주요 사실 근거 → 새 agent 입력 | 자료에 결합된 판정 인터페이스·허용 입력 조립·합성 검증 | 실제 검색·의미 품질·자동 adapter·답변/UI 연결 미완료 |
| 사용자 화면 | 로컬 질의 UI 및 Chromium 키보드 제출·인용·다운로드·초기화 확인 | 팀원 사용자 검증·전체 접근성 검증은 남음 |
| 에이전트 간 상호작용·Reflection | 아직 미구현 | 기능 범위·메시지 계약·사용자 task 확인 필요 |
| 논문 검증 | 재현 코드·실패 기록·설계 이력 확보 | 독립 사람 평가, 미사용 데이터, baseline·사용자 연구 미완료 |

**기존 확인된 시연:** 준비된 검수 결과 → 두 개발용 agent에게 질문 → 서로 다른 답변·인용 원문 비교.
**새 자동 경로:** [수동 개입 없는 생성과 실행 방법](docs/AUTOMATIC_FACTORY.md). 사람 승인 큐가 없으며,
통과 묶음이 없으면 0 agent와 보류 결과를 반환합니다. 자동 생성 성공과 의미 품질 성공을 구분합니다.
**아직 불가능한 완료 주장:** 임의 영상 → 전체 댓글 자동 분석 → 검증된 agent 생성 → 토론까지 완전 자동 MVP.

기존 검수 지원 시연은 [12단계 로컬 UI](#12-브라우저에서-직접-질문하기-로컬-전용)를,
수동 입력 없는 실험은 [자동 생성 실행 안내](docs/AUTOMATIC_FACTORY.md)를 사용합니다.
아래 3~10단계 실험을 전부 다시 실행할 필요는 없습니다. 기존 연구 데이터는 별도 로컬 준비가 필요하며 GitHub에 없습니다.

| 코드 위치 | 역할 |
| --- | --- |
| `ingestion/`, `agents/`, `providers/local_llama.py` | 수집·검수 입력·로컬 질의의 현재 실행 경로 |
| `factory/`, `cluster_baseline.py`, `experiments/`, 프롬프트 비교 모듈 | 후보 생성·검수 및 연구용 비교 경로. main에 있어도 품질 승인된 기본 알고리즘은 아님 |
| `docs/ARCHITECTURE.md`, `docs/DATA_CONTRACTS.md` | 교체 가능한 모듈 경계·결정 이력·입출력 계약 |
| `data/`, `artifacts/`, `runs/` | 실제 댓글·실행 결과·대화 로그. Git 제외 |

## 읽는 순서

1. [프로젝트 요구사항](docs/requirements-handoff.md): Section 16이 최신 구현 기준입니다.
2. [단계별 구현 계획](docs/IMPLEMENTATION_PLAN.md): 단계별 산출물과 완료 조건입니다.
3. [협업 방법](CONTRIBUTING.md): 브랜치, 변경 검토, 데이터 관리 규칙입니다.
4. [구조 결정](docs/ARCHITECTURE.md)과 [데이터 계약](docs/DATA_CONTRACTS.md): 첫 구현의 경계와 필드·불변조건입니다.
5. [검증 목록](docs/ACCEPTANCE_TESTS.md): 단계별로 구현할 실패 사례와 완료 조건입니다.
6. [YouTube 댓글 수집 안내](docs/YOUTUBE_COLLECTION.md): API 키 발급, 첫 수집, 상한과 오류 처리입니다.

## 현재 범위

- 약 1,000개 댓글/스레드의 준비된 연구 snapshot을 목표로 합니다.
- 다국어 입력, 선택한 UI 언어 출력, 원문 인용 보존을 지향합니다.
- 검증된 cluster만 Perspective Agent가 됩니다. Rare/uncertain 관점도 근거와 함께 보존합니다.
- 각 agent의 증거와 대화 상태를 분리하고 Auditor가 답변을 수정하거나 거절할 수 있게 합니다.
- Factory 자동화와 검수 입력 기반 사용자 흐름을 분리해 진행합니다. clustering만을 최종 연구 목표로 삼지 않습니다.
- 실제 서비스에서는 사람/대화 assistant의 분류·수정·승인을 요구하지 않습니다. 개발 및 논문용 사후 표본 평가는 별도입니다.

## 저장소 경계

이 폴더가 독립 Git 저장소입니다. 수업 전체 폴더와 기존 발표 자료는 저장소에 포함하지 않습니다.
요구사항 원본은 상위 폴더의 `CommentScope_Implementation_Handoff_Requirements_2026-10-07.md`이며,
독립 clone에서도 읽을 수 있도록 동일 내용의 기준본을 `docs/requirements-handoff.md`에 포함합니다.
기준본의 Section 16을 우선하며, 향후 변경은 원본과의 차이 및 이유를 PR에 기록합니다.

실제 댓글, API 키, 대화 기록, 실행 결과는 기본적으로 Git에서 제외합니다.
공유 가능한 합성 테스트 데이터는 `tests/fixtures/`에 있습니다. 모델 weights도 올리지 않으며 원 배포처에서 별도로 받습니다.

## GitHub 연결 상태

공개 저장소: [joowonkime/commentscope](https://github.com/joowonkime/commentscope)

기본 브랜치는 `main`입니다. GitHub Issues/PR로 단계별 작업을 관리합니다.
실제 연구 데이터와 비밀 값은 공개 저장소에 포함하지 않습니다.

## 설치와 실행

Python 3.12 이상이 필요하며 현재 테스트 기준은 3.12입니다. 수집·검증에는 runtime 외부 의존성이 없고, clustering은 추가 설치가 필요합니다.
저장소 폴더에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m commentscope validate tests/fixtures/synthetic-snapshot.json
python -m commentscope normalize tests/fixtures/synthetic-snapshot.json --output artifacts/normalized.json
python -m unittest discover -s tests -v
```

Windows PowerShell에서는 `py -3.12 -m venv .venv`로 생성한 뒤 활성화 없이 `.venv\Scripts\python.exe`로 위의 `python` 명령을 실행할 수 있습니다.
설치하면 `commentscope validate ...` 형태의 console 명령도 제공됩니다.

현재 WSL처럼 `ensurepip`가 없지만 기존 Python에 pip가 있는 환경에서는 다음 경로를 사용할 수 있습니다.

```bash
python3 -m venv --without-pip .venv
python3 -m pip --python .venv install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m commentscope validate tests/fixtures/synthetic-snapshot.json
```

## 이번 단계에서 확인할 수 있는 것

- `validate`: 필드/타입/enum, UTF-8 JSON, 원문 ID, parent 관계, cycle, URL 및 timestamp 형식을 검사합니다.
- `normalize`: 원문을 보존하고 분석용 NFC·공백 정규화와 문맥별 중복 alias를 생성합니다.
- JSON 산출물에 입력 SHA-256, snapshot 전체, 원문/정규화 텍스트, 실행/정규화 버전과 집계를 보존합니다.
- 표본 예제의 결과는 원문 11개, top-level 9개, reply 2개, missing parent 1개, 중복 alias 1개입니다.

## 공식 API 댓글 수집

Google Cloud에서 YouTube Data API v3를 활성화하고 API 키를 만든 뒤 실행합니다.
키는 화면에 표시되지 않는 프롬프트에 입력하며, 영상 URL을 실제 선택한 영상으로 바꿉니다.

```bash
python -m commentscope collect-youtube "https://www.youtube.com/watch?v=VIDEO_ID" --prompt-key --max-comments 100 --top-level-limit 40 --output data/first-video.json
```

일반 실행에서는 `YOUTUBE_API_KEY` 환경변수도 사용할 수 있습니다. `.env` 자동 로딩은 하지 않습니다.
relevance/time을 섞어 조회하고 답글은 별도로 보완합니다. API의 표시 텍스트와 parent 관계를 보존합니다.
본문 100개가 아니라 **최상위 댓글과 답글을 합쳐 최대 100개**이며, 부족하면 실제 개수를 보고합니다.
실제 API 호출과 표본 1,000개 저장을 확인했습니다. 자세한 순서는 [수집 안내](docs/YOUTUBE_COLLECTION.md)를 따릅니다.
첫 cluster 품질 검증까지 기존 1,000개를 재사용하며 자동 재수집하지 않습니다. 전체 수집 또는 무작위 표집이 아닙니다.

같은 output 경로로 다시 실행하면 `OUTPUT_EXISTS` 오류를 반환합니다. 새 파일명을 지정해야 합니다.
입력 또는 기존 결과를 덮어쓰는 옵션은 없습니다. 파일시스템의 hard-link 지원이 필요하며 지원하지 않으면 저장 오류를 반환합니다.

성공은 stdout의 JSON과 종료 코드 0입니다. 입력 계약 오류는 stderr의 JSON과 코드 2,
입출력 오류는 stderr의 JSON과 코드 1입니다. CLI 인자 오류는 argparse의 도움말과 코드 2를 반환합니다.
`validate`는 파일을 생성하지 않고, 실패한 `normalize`는 완료 결과 파일을 남기지 않습니다.

## 검증과 다음 범위

[자동 테스트](tests/test_ingestion.py)는 S01–S12, 긴 reply chain, 중복 JSON key, 동시 저장, 파일 보존을 검사합니다.
PR과 main push에서 GitHub Actions가 Linux/Windows Python 3.12 설치·테스트·CLI 실행을 확인합니다.
CI 결과는 해당 PR의 Checks에서 확인합니다.

다음 사용자 확인 지점은 **실제 댓글의 주장 추출 품질을 확인하고 claim cluster로 연결하는 MVP**입니다.
로컬 모델 우선이며 품질 승인은 아직입니다. corpus 분석·외부 전송 사용 조건도 별도 검토 대상입니다. 인터페이스만을 MVP 완료로 간주하지 않습니다.
합성 JSON 예제와 Factory trace는 직접 작성한 자료이며 모델 결과나 다국어 분석 성능의 근거가 아닙니다.

## 로컬 모델 실행 (개발용, 아직 one-click 앱 아님)

현재 확인한 환경은 WSL/Linux, RTX4060 Laptop 8GB, Qwen3-4B-Instruct-2507 Q4_K_M입니다.
모델은 별도 프로세스에서 실행되며 Python 진단 스크립트는 `127.0.0.1:8091`로만 요청합니다.
댓글을 외부 모델 API로 보내지 않습니다. 최초 모델/패키지 다운로드에는 인터넷이 필요합니다.
다른 OS/GPU의 성능·설치는 아직 실측하지 않았습니다. 비개발 팀원은 우선 담당자가 만든 **로컬 HTML 검수 화면**으로 의견을 남길 수 있습니다.

### 1. 모델과 실행기 준비

- 실행기: [llama.cpp b11541 릴리스](https://github.com/ggml-org/llama.cpp/releases/tag/b11541)의 OS/GPU에 맞는 바이너리. NVIDIA는 해당 CUDA runtime도 필요합니다.
- 원 모델: [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).
- 사용한 양자화: [Unsloth GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/a06e946bb6b655725eafa393f4a9745d460374c9)의 `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`.
- 모델 파일과 실행기는 저장소 밖에 두세요. Git에 weights/API 키/실제 댓글을 추가하지 마세요. 각 배포처의 라이선스와 실행 환경 요구사항을 확인하세요.

`llama-server`가 PATH에 있고 필요한 라이브러리를 찾을 수 있는 환경에서, 별도 터미널에 실행합니다. `/absolute/path/...`는 실제 모델 경로로 바꿉니다.

```bash
llama-server -m /absolute/path/Qwen3-4B-Instruct-2507-Q4_K_M.gguf --host 127.0.0.1 --port 8091 -c 4096 -ngl 99 -t 6 --parallel 1
```

`--host 0.0.0.0`으로 외부에 노출하지 마세요. 메모리 부족 시 다른 GPU 작업을 종료하거나 offload 설정을 조정하고 변경 설정을 실행 기록에 남깁니다.
설정 변경의 품질·시간은 기존 결과와 동일하다고 가정하지 않습니다. 사용 후 서버 터미널에서 Ctrl+C로 종료합니다.

### 2. 공개 합성 예제로 연결 확인

위의 Python 기본 설치 후 다른 터미널에서 실행합니다. YouTube API 키는 필요 없습니다.

```bash
python experiments/local_claim_probe.py --snapshot tests/fixtures/synthetic-snapshot.json --output artifacts/synthetic-probe.json --limit 3 --revision v3 --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 context4096 parallel1"
```

출력은 JSON과 같은 이름의 `.html`입니다. HTML을 브라우저에서 열어 원문·모델 결과·계약 오류를 나란히 확인합니다.
이 합성 fixture는 수집 계약 예제이지 UBI 의미 평가셋이 아니므로 이 실행은 연결 확인용입니다.
`--model-label`, `--model-revision`, `--runtime`은 실제 설치에 맞춰 쓰는 사용자 선언이며 스크립트가 자동 검증한 값이 아닙니다.

### 3. 준비된 로컬 데이터 검증

`--snapshot`을 자신이 사용할 권한이 있는 snapshot 파일로, `--output`을 새로운 경로로 바꿉니다.
현재 단계는 snapshot 최대 1,000개, 기본 추출 표본 12개, seed 407입니다. 실험을 반복해도 YouTube API를 호출하지 않습니다.
프롬프트는 현재 UBI 주제용이므로 다른 영상에 적용할 때에는 주제와 프롬프트 버전을 함께 검토해야 합니다.

- 같은 표본 회귀 비교: `--replay-report artifacts/previous.json` (기존 보고서 전체 ID를 재사용; `--limit`보다 우선).
- 이전 표본과 겹치지 않는 표본: `--exclude-report artifacts/previous.json --limit 12 --seed 408`.
- 두 옵션은 동시에 쓸 수 없으며, snapshot hash가 다르면 거절합니다.
- `v2`/`v3`는 같은 prompt-0.2와 claims-0.2를 사용합니다. v3는 생성 스키마에서 eligibility와 claims 유무를 함께 제한합니다. 논문 설계의 clustering V2와 다른 버전입니다.
- 기존 결과는 덮어쓰지 않습니다. HTTP 오류는 실행을 중단하며, 이 진단 도구는 자동 retry/resume 또는 중간 결과 복구를 제공하지 않습니다.

`contract_pass`는 형식·인용 문자열·필드 일관성 검사입니다. 의미 정확도나 agent 승인 점수가 아닙니다.
모든 성공 결과도 `semantic_review_status=pending`이며 주장 누락·추가·조건 변경을 별도로 확인합니다.
실제 원문이 들어간 HTML/JSON은 공개 GitHub에 올리지 마세요.

### 4. 원문 기반 clustering 기준선 (별도 실험)

```bash
python -m pip install -e '.[clustering]'
python -m commentscope.cluster_baseline tests/fixtures/synthetic-snapshot.json --output artifacts/synthetic-clusters.json
```

처음에는 embedding 모델을 다운로드합니다. 실제 데이터로 실행하려면 입력 snapshot 경로만 교체합니다.
결과 화면은 `artifacts/synthetic-clusters.json.html`입니다. 이는 **원문 묶음 기준선**이며 claim 추출 결과를 연결하거나 agent를 생성하지 않습니다.
ML 의존성은 GPU 없이도 CPU에서 실행할 수 있지만 시간은 환경에 따라 달라집니다. 모델 실행은 CI에 포함되지 않으며 CI는 오프라인 계약 테스트를 수행합니다.

### 5. 주장 추출 → 후보 클러스터 연결 (소표본 개발용)

2단계의 추출 JSON을 4단계와 같은 ML 환경에서 연결합니다. LLM 서버를 다시 호출하지 않습니다.

```bash
python -m commentscope.factory.claim_clusters tests/fixtures/synthetic-snapshot.json artifacts/synthetic-probe.json --output artifacts/synthetic-claim-clusters.json
```

`artifacts/synthetic-claim-clusters.json.html`에서 주장·원문·부모 문맥·실패/제외 목록을 확인합니다.
snapshot hash와 원문을 재검증하며 실패 결과를 성공으로 취급하지 않습니다. 벡터와 입력 텍스트도 JSON에 저장합니다.
현재 60개 이하 선택 원문/300개 이하 claim만 지원합니다. 원본 snapshot 상한은 1,000개입니다.
서로 다른 원문 3개 이상이어도 **검수 전 후보**일 뿐입니다. 합성 예제는 연결 확인이며 의미 품질의 증거가 아닙니다.

기존 V0 그룹을 목적 표집하려면 추출 명령에 `--v0-report artifacts/YOUR-V0.json --clusters C001 C002`를 추가할 수 있습니다.
그룹 전체를 사용하므로 이때 `--limit`은 적용하지 않습니다. `--replay-report`/`--exclude-report`와 동시에 사용할 수 없습니다.
유망한 그룹을 골랐다는 사실을 반드시 평가에 표시하며, 이전 실험을 본 표본을 독립 평가셋으로 간주하지 않습니다.

AI 검수 초안은 별도 로컬 JSON으로 보존하고 candidate artifact hash와 근거 소속을 검사합니다.
새 HTML에 붙이는 명령은 다음과 같습니다(실제 파일 경로로 교체).

```bash
python -m commentscope.factory.claim_clusters data/YOUR-SNAPSHOT.json artifacts/YOUR-EXTRACTION.json --render-only artifacts/YOUR-CANDIDATES.json --review artifacts/YOUR-REVIEW.json --output artifacts/YOUR-REVIEWED.html
```

이는 자동 의미 검수나 사람 승인 UI가 아닙니다. 원문 충실성을 사용자가 확인한 뒤 다음 구현에서 승인 절차로 연결합니다.
claim 기반 전체 corpus 처리·split/merge·PerspectiveSpec·agent는 아직 구현하지 않았습니다.

### 6. 로컬 대표 주장 초안 + 근거 검사 (품질 미승인)

후보에서 공통 주장·일부 댓글의 이유/조건/차이를 로컬 모델로 생성하는 실험입니다.
**승인된 PerspectiveSpec/agent 생성기가 아닙니다.** 개발 표본에서 과장·예측/필요성 혼합과 검사 모델의 오판을 확인했습니다.
기존 assistant의 검수 초안을 모델 입력에 넣지 않습니다. 실제 댓글/결과를 공개 GitHub에 올리지 마세요.

기존 서버를 종료하고, 이 실험에서는 더 큰 입력을 위해 8192 context와 context shift 비활성화 설정을 사용합니다.
설치 경로를 실제 경로로 바꾸세요. 실제 확인한 환경은 앞서 설명한 WSL/RTX4060 Laptop 8GB입니다.

```bash
llama-server -m /absolute/path/Qwen3-4B-Instruct-2507-Q4_K_M.gguf --host 127.0.0.1 --port 8091 -c 8192 --no-context-shift -ngl 99 -t 6 --parallel 1
```

Python 기본 설치 환경에서 다음 명령을 실행합니다. 입력은 앞 단계의 동일 snapshot/추출/후보 JSON이며, 파일명과 후보 ID는 실제 파일에 맞춥니다.
아래는 프로젝트 로컬 데이터 경로 예시입니다. 연구 데이터는 clone에 포함되지 않습니다. 합성 연결 확인에는 5단계의 파일들과 CC001을 사용할 수 있습니다.

```bash
python -m commentscope.factory.perspective_drafts data/ubi-research-20261010.json artifacts/claim-slice-20261011-extraction.json artifacts/claim-slice-20261011-candidates.json --output artifacts/YOUR-drafts.json --clusters CC001 CC002 CC003 --revision v2 --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 context8192 no-context-shift parallel1"
```

v1은 모델이 부분 인용을 생성합니다. v2는 모든 입력 ID의 배정을 필수로 하고, 모델이 선택한 ID에 실제 **전체 원문**을 코드로 연결합니다.
v2의 인용 일치는 생성 정확도가 아니라 프로그램의 출처 연결 보장입니다. 전체 원문이 연결됐다고 문장을 실제로 뒷받침하는 것은 아닙니다.
세부 문장의 근거 ID는 해당 그룹 안에 있어야 합니다. 같은 원문의 여러 claim은 지지 source 수를 늘리지 않습니다.
프롬프트·출력 형식·입력 방식·인용 방식을 함께 바꿨으므로 v1/v2는 단일 요인의 효과 비교가 아닙니다.

v2의 구조 통과 초안에 대해 별도 로컬 검사를 실행할 수 있습니다.

```bash
python -m commentscope.factory.draft_audit data/ubi-research-20261010.json artifacts/claim-slice-20261011-extraction.json artifacts/claim-slice-20261011-candidates.json artifacts/YOUR-drafts.json --output artifacts/YOUR-audit.json --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 context8192 no-context-shift parallel1"
```

각 명령의 결과 화면은 output에 `.html`을 덧붙인 경로입니다. 중단 대비 후보별 `.case-N.json`도 보존하지만 자동 resume은 없습니다. 새 실행은 새 output 경로를 사용합니다.
한 번에 최대 후보3개, 후보별 claim20개를 시험합니다. 오류나 출력 잘림은 차단하고 원시 출력을 남깁니다.
검사는 같은 모델의 두 번째 판단이며 독립적인 정답 평가가 아닙니다. 모두 supported여도 사람 검토 대기이며, agent 승격 권한이 없습니다.

한 문장과 인용 원문 하나만 새 요청으로 검사하려면 `--mode pairwise`를 사용합니다. 기본값은 과거 비교를 위한 `batch`입니다.
pairwise에서는 `M01` 같은 ID만 적힌 문장을 모델 호출 전에 규칙으로 차단합니다. 이는 모델 정확도 개선으로 세지 않습니다.
같은 초안의 이전 검사 결과가 있으면 선택적으로 `--compare-to`를 붙입니다. draft hash와 pair 일치를 확인하며 이전 판단은 모델에 전달하지 않습니다.

```bash
python -m commentscope.factory.draft_audit data/ubi-research-20261010.json artifacts/claim-slice-20261011-extraction.json artifacts/claim-slice-20261011-candidates.json artifacts/YOUR-drafts.json --mode pairwise --compare-to artifacts/YOUR-audit.json --output artifacts/YOUR-pairwise-audit.json --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 context8192 no-context-shift parallel1"
```

pairwise는 쌍별 `.case-N.PXX.json`도 보존합니다. HTML에서 원문·제안 문장·이전/현재 판단·규칙/모델 출처를 대조할 수 있습니다.
실제 개발 표본 22쌍에서 18회 모델 호출 + ID-only 4쌍 규칙 차단을 확인했습니다. 일부 과장은 잡았지만 원문과 동등한 문장의 잘못된 거절도 남았습니다.
검사만 달라졌으며 초안 내용·cluster 배정은 수정하지 않았습니다. 승인된 PerspectiveSpec/agent는 여전히 0입니다.

#### 프롬프트만 바꾸는 비교 실험

위 audit 명령에 `--prompt-revision v2`를 추가하면 사실 검증과 원문 충실성 검사를 구분하는 새 지시문을 시험합니다.
기본값은 `v1`을 유지합니다. 동일 draft에 `--mode pairwise`를 유지하고 `--compare-to`에는 이전 pairwise 결과를 지정하세요.
`comparison_metadata_changes`에서 모델/설정/검사 방식이 함께 바뀌지 않았는지 확인할 수 있습니다. 실행자 선언 metadata이며 독립 평가가 아닙니다.
기존 개발 회귀 8사례에서 기대 판단 일치는 5→5였습니다. 타당한 예측 거절 2건을 고쳤지만 과장 2건을 다시 놓쳐, 개선 버전으로 채택하지 않았습니다.

대표 초안 명령의 `--revision v3`는 v2의 입력·배정 스키마·원문 연결을 유지하고 생성 프롬프트만 바꿉니다. 기본값은 `v2`입니다.
새 경로에 저장해야 하며 v3 결과도 같은 audit 명령으로 검사할 수 있습니다. `draft --revision`과 `audit --prompt-revision`은 별개 버전입니다.
실제 후보3개 중 구조 통과2개였지만 예측/필요성 혼합과 다른 주장을 잘못 묶는 오류가 남았습니다. 프롬프트 수정만으로 해결됐다고 간주하지 않습니다.

### 7. 실패 단계 분리 진단 (개발용, pipeline 변경 없음)

`experiments/source_frame_probe.py`는 한 고정 후보 안에서 원문 embedding과 저장된 claim embedding을 같은 임계값으로 비교하고,
댓글 하나씩 주장 성격·표현 강도·원문 이유/조건 구간만 분류합니다. 기존 추출 주장이나 그룹 설명은 분류 모델에 전달하지 않습니다.
주장을 재작성하지 않으므로 paraphrase 품질 개선이나 전체 extractor 대체로 해석하지 않습니다. 분류 label로 자동 분할/승인하지 않습니다.
저장소 루트의 ML 설치 환경과 위 로컬 서버가 필요합니다. 모델을 이미 내려받았다면 offline 모드로 실행할 수 있습니다.

```bash
HF_HUB_OFFLINE=1 python -m experiments.source_frame_probe data/ubi-research-20261010.json artifacts/claim-slice-20261011-extraction.json artifacts/claim-slice-20261011-candidates.json --cluster CC001 --output artifacts/YOUR-stage-diagnostic.json --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 CUDA12.8 context8192 no-context-shift parallel1"
```

최대12개 claim, source당1개, 원문당2,000자 이내의 작은 진단입니다. 원문/추출/후보·저장 embedding 출처를 재확인하고,
벡터·임계값별 배정·원시 모델 결과·실패·댓글별 checkpoint·미승인 상태를 보존합니다. 결과 화면은 output + `.html`입니다.
선택 subset만 비교하므로 기존 전체 후보 생성과 같지 않으며, 같은 개발 사례 반복 결과를 일반 정확도로 보고하지 않습니다.
현재 자동화9개는 원문/추출 주장 모두 0.45에서 한 후보로 묶였고, 더 작은 임계값에서도 예측/필요성 혼합이 남았습니다.
주제 후보를 만든 것과 agent가 대변할 공통 주장을 검증한 것은 다릅니다. 현재 집중할 부분은 원문별 의미 확인과 후보의 관점 승격 검토입니다.

### 8. B: 원문 선택형 대표 + 직접 지원 관계 (개발용, 미승인)

대표 문장을 생성하지 않고 후보 안의 짧은 원문 전체를 대표 후보로 사용합니다. 로컬 모델은 두 원문 사이의
`supports / contradicts / not_established / unclear`만 선택합니다. 코드는 대표를 직접 지원하는 댓글을 최소3개씩
중복 없이 묶고, 남는 댓글도 모두 표시합니다. 연결된 댓글을 따라가는 간접 추론으로 지지 수를 늘리지 않습니다.

위 로컬 서버와 5단계 산출물이 필요합니다. 명령의 파일명은 로컬 데이터 예시이며 실제 댓글은 저장소에 포함되지 않습니다.

```bash
python -m commentscope.factory.extractive_keypoints data/ubi-research-20261010.json artifacts/claim-slice-20261011-extraction.json artifacts/claim-slice-20261011-candidates.json --cluster CC001 --output artifacts/YOUR-extractive-keypoints.json --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 CUDA12.8 context8192 no-context-shift parallel1"
```

결과는 지정 JSON과 `.json.html`, 쌍별 checkpoint입니다. 기존 파일은 덮어쓰지 않습니다. source당1개 claim,
최대12개 source, 원문당500자 제한의 작은 기준선입니다. 모델 호출은 N×(N−1)회라 전체1,000개에 직접 적용하지 않습니다.
기존 추출/후보는 입력 선택과 출처 검증에만 쓰며, 관계 판단 입력에는 원문 두 개만 전달합니다.

실제9개 실행: 모델72회, 오류응답0, 호출시간 합16.77초(서버 로딩 제외), 제안2묶음/배정7개/미배정2개.
하지만 필요성→도입 예측 오연결이 남아 **두 묶음 모두 의미 검수상 수정 필요, 승인/agent는0**입니다.
대표 원문 복사는 보장하지만 배정의 의미 정확성은 보장하지 않습니다. 다음 교체 지점은 `judge()`의 관계 판정이며,
현재 Qwen4B 결과를 자동 승인 gate로 쓰지 않습니다. Jev나 유료 API 호출/외부 댓글 전송은 하지 않았습니다.

### 9. 관계 판정기만 교체한 로컬 NLI 비교

`experiments.compare_local_nli`는 8단계 원문/대표/배정 코드를 고정하고 영어 NLI 분류기를 비교합니다.
실제9개 회귀와 합성20사례를 실행했습니다. 기존 필요성→도입 오연결3건은 막았으나 조건 삭제 오판과
정상 연결 누락이 남았고, NLI로 만든 3개 이상 묶음은0개였습니다. **기본 판정기 교체/자동 승인하지 않습니다.**
모델 다운로드·평가 계획·실행법·해석 한계는 [로컬 NLI 비교](docs/LOCAL_NLI_COMPARISON.md)에 있습니다.

### 10. 원문 보존형 주장 계열 + assistant 검수 루프

자동 판정의 실패를 보존하면서 assistant가 원문을 읽고 수정한 별도 결과를 만들 수 있습니다.
현재21개 검수 결과는 필요성7개/도입 예측4개/가능한 이점2개/보류8개입니다. 같은 계열의 조건·이유가 모두 같다는
뜻은 아니며, 전체 원문 카드를 개별 근거로 보존합니다. 로컬 모델 단독 성공이나 승인된 agent로 보고하지 않습니다.
개발9개는 두 revision 모두8/9, 추가12개는 계약을 포함한 사전 기준 일치5/12로 자동 성공 기준을 실패했습니다.
실행/검수 계약과 평가 한계는 [검수 루프](docs/SOURCE_FACET_REVIEW_LOOP.md)를 확인하세요.

### 11. 묶음 → 개발용 에이전트 → 질문·근거 비교

이제 검수 결과를 에이전트 프로필로 만들고 같은 질문에 독립적으로 답하게 할 수 있습니다.
에이전트별 근거/대화 상태를 분리하고, 문장별 출처 검사 → 최대1회 수정 → 통과 또는 보류를 실행합니다.
저장된 HTML에서 답변을 비교하고 원문을 펼쳐 볼 수 있습니다. 정식 승인된 PerspectiveSpec/제품용 agent가 아니므로
`--allow-unapproved`를 명시해야 합니다. 같은 모델의 검사 통과는 의미 정확성을 보장하지 않습니다.

```bash
python -m commentscope.agents.demo build data/ubi-research-20261010.json artifacts/source-facet-loop-20261011-reviewed.json --allow-unapproved --output artifacts/YOUR-dev-agents.json
python -m commentscope.agents.demo ask data/ubi-research-20261010.json artifacts/source-facet-loop-20261011-reviewed.json artifacts/YOUR-dev-agents.json --allow-unapproved --question "이 관점에서 AI와 UBI는 어떤 관계인가요?" --question "그 판단에 붙은 조건은 무엇인가요?" --output artifacts/YOUR-agent-comparison.json --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 CUDA12.8 context8192 no-context-shift parallel1"
```

ask에는 위에서 설명한 로컬 모델 서버가 필요합니다. 실제 데이터/검수 파일은 Git에 없고 위 경로는 로컬 실행 예시입니다.
결과 화면은 output + `.html`입니다. 최대6개 질문을 순서대로 보내며 이전2개 자기 대화만 참조합니다.
위 명령은 저장형 비교입니다. 직접 질문하는 로컬 UI는 아래 12단계를 사용합니다. 에이전트 간 토론과 Reflection은 아직 아닙니다.
자세한 동작·경계·검증은 [에이전트 연결 단계](docs/AGENT_VERTICAL_SLICE.md)에 있습니다.

### 12. 브라우저에서 직접 질문하기 (로컬 전용)

Python 설치 후, **터미널 1에서 로컬 모델**, **터미널 2에서 UI 서버**를 실행하고 브라우저를 엽니다.
기존 검수 snapshot/bundle이 필요합니다. 실제 댓글은 GitHub에 없으므로 새 clone만으로 동일 연구 자료가 생기지는 않습니다.
모델 실행 경로와 CUDA 라이브러리 설정은 본인 환경에 맞춰야 합니다. 기존 8,192 context 설정을 유지합니다.
GPU 메모리가 부족하면 다음처럼 GPU layer/배치를 줄일 수 있습니다(속도는 달라지며 모델 품질 개선을 뜻하지 않음).

```bash
# 터미널 1 — 실제 설치 경로 사용
llama-server -m /absolute/path/Qwen3-4B-Instruct-2507-Q4_K_M.gguf --host 127.0.0.1 --port 8091 -c 8192 --no-context-shift -ngl 24 -b 128 -ub 128 -t 6 --parallel 1

# 터미널 2 — 저장소 루트, 가상환경 활성화 후
python -m commentscope.agents.web data/ubi-research-20261010.json artifacts/source-facet-loop-20261011-reviewed.json artifacts/development-agents-20261011.json --allow-unapproved --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 CUDA12.8 context8192 no-context-shift parallel1 ngl24 batch128 ubatch128 threads6"
```

브라우저에서 **http://127.0.0.1:8765**를 엽니다. WSL에서 Windows 브라우저를 쓸 때는 localhost 전달이 필요합니다.
연결되지 않으면 WSL localhost forwarding 설정을 확인하세요. 서버를 `0.0.0.0`에 공개하는 것으로 해결하지 않습니다.

1. 관점 카드의 전체 근거를 펼쳐 봅니다.
2. 질문 입력 → 진행 상태 확인 → 두 관점의 답변과 인용 원문을 비교합니다.
3. 후속 질문을 하거나 비교 HTML/연구 JSON을 저장합니다. 대화당 최대 6개 질문입니다.
4. 새 대화로 시작하면 이전 대화 상태는 모델에 전달되지 않습니다. 종료는 두 터미널에서 각각 Ctrl+C입니다.

서버는 loopback만 사용하며 외부 서비스에 댓글을 전송하지 않습니다. 모델 서버가 꺼져 있거나 생성에 실패하면
답변 보류 사유에 연결/생성 오류를 표시합니다. 의미적으로 근거가 없다는 판정과 구분하세요.
원시 초안/검사 결과는 화면에 최종 답변으로 노출하지 않지만, `runs/agent-ui/<실행ID>/`에 자동 저장하며 JSON으로 내려받을 수 있습니다.
원문이 포함된 민감한 연구 기록이므로 공개 업로드하지 마세요. 새 대화/서버 종료는 이 파일을 삭제하지 않습니다.
만료 후 신규 질의/서버 열람은 차단하지만, 저장·다운로드한 파일의 자동 삭제나 재개 기능은 없습니다.
새로고침은 새 세션이며 이전 세션의 자동 복원이 아닙니다. 메모리 세션은 최대 8개, 비활성 1시간 후 정리됩니다.

검증 명령 (JS 검사는 Node 18+ 필요, 앱 실행 자체에는 Node 불필요):

```bash
python -m unittest discover -s tests -v
node --check src/commentscope/agents/comparison.js
node --test tests/web_ui_smoke.cjs
```

실제 서버/모델 연결을 반복 검증하려면 `experiments/agent_web_smoke.py --question "..." --output artifacts/NEW-ui-check.json`을
Python으로 실행합니다. 이는 HTTP 연동 검사이며 실제 브라우저의 레이아웃 검증은 아닙니다.

실제 Chromium에서 질문 입력·키보드 제출·인용 펼치기·HTML/JSON 다운로드·새 탭·대화 초기화를 확인하는 선택적 개발 검사도 있습니다.
앱의 필수 의존성이 아니며, 별도 개발 환경에 Playwright와 Chromium을 설치한 후 모델/UI 서버를 먼저 실행합니다.

```bash
python -m pip install playwright==1.63.0
python -m playwright install chromium
python experiments/browser_agent_smoke.py --output-prefix artifacts/NEW-browser-check --question "AI와 UBI에 대해 어떤 주장이 있나요?" --question "한국에서 지급액은 정확히 얼마인가요?"
```

스크린샷과 다운로드에는 실제 댓글이 들어갑니다. `artifacts/` 밖의 공개 위치에 저장하지 마세요.
이 검사는 브라우저를 직접 조작하지만 비개발자 사용자 연구나 독립적인 의미 평가를 대신하지 않습니다.
