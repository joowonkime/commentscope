# 다음 세션 시작점

## 최신 raw 공통 주장 실행 완료와 품질 실패 2026-10-12

- 사용자 요청으로 중단했던 실행을 같은 코드/plan으로 재개해 완료했다. LLM57/NLI53 checkpoint를 재사용했다.
  코드 `12c1c2c`, [설계·실측·실패 분석](RAW_SUPPORT_MVP.md), ADR-027이 최신이다.
- 원문 쌍 제안→원문별 NLI+관계 감사→5상태 ledger를 구현했다. 기존 모델/threshold/main은 유지했다.
  source budget은4,000자/NLI512token이며 초과는 unchecked다. full raw source를 조용히 잘라 검사하지 않는다.
- 고정 직접 회귀37개: 정상15/20보존, 부정13/17비승인, 실제 의미 오승인1, 계약 오류4.
  공통 주장 합성12쌍: 정상5/6, 부정4/6비승인, 계약 오류2. 오류는 올바른 부정 판정으로 세지 않는다.
- 실제64쌍:60제안/4무제안,120 source–core 판정은 support12/not_supported54/uncertain33/error13/unchecked8.
  양쪽 통과0, core0, ledger0, 지지도 확장0, agent0. 회귀 gate 실패로 확장을 보류했다.
- 검색 보존 정상3쌍: 취업 의사 쌍은 인용 조건 누락+guard, 물가 한 쌍은 supported/unclear 동시 출력,
  다른 물가 쌍은 과도한 복합 공통 주장으로 실패했다. source 검색 병목과 구분한다.
- 개별 support12건 전수 assistant 검토: 충실한 독립 주장4/수정3/대표로 부적합4/추가 검토1.
  개인 취업 의사→집단의 취업 필요라는 오승인이 있고 밈/불명확한 He/대상 없는0%도 통과했다.
  별도 사후 평가일 뿐 독립 gold나 서비스 수동 승인 아니다. 자동 판정과 기존 라벨은 그대로 보존했다.
- 재개 후153.36초/실제64쌍130.04초. 누적LLM189/NLI178요청, 재개 신규132/125. 전체 연속 서비스 시간 아님.
  형식 수리25회 중18회가 자체 모순된 지지 판정,7회가 원문 인용 문제였다. 수리 요청 시간 합40.31초.
- private `runs/raw-support-20261012/review.html`이 핵심 결과 화면, `overview.html`이 전체원문/판정,
  `assistant-review.json`이 support12건 검토다. 같은 snapshot 만료 상속. 원문/출력/GGUF는 Git 제외다.
  새 LLM/NLI0회 replay 일치, Python367개/Node4개 통과. 모델 서버 종료. PR21 draft/main 미병합 유지.
- **다음**: 검색 이후 판정 계약만 제한적으로 수정한다. 중복 model verdict는 host의 보수적 결정으로 분리,
  인용은 이미 검색된 pair 안에서 source 위치 결합으로 제한한다. 독립 대표 주장 자격과 직접 지지는 분리한다.
  최소 공통 주장/정상 보존/개인→집단·의사→필요성 오승인을 함께 검사한다.
  guard 제거·threshold 완화로 통과 수를 늘리거나 전체1000/새 agent로 확대하지 않는다. 아직 자동 MVP 완료 아님.

## 이전 원문 검색 우선과 지지도 계약 2026-10-12

- 사용자 합의: 전체 댓글을 완벽하게 복원하는 비용을 피하되, 의미 왜곡 없이 지지 댓글 수를 제시하고 서비스 대기 시간을 줄인다.
  [최신 계약·구현·재현](RAW_RETRIEVAL_MVP.md), ADR-026, DATA_CONTRACTS raw-candidates0.1을 먼저 읽는다.
- 코드 사전 고정 `a77f566`. 원문 registry→MiniLM→semantic8+lexical4→hash round-robin64쌍을 구현했다.
  selector/topic/eligibility 실패가 검색 전 source를 삭제하지 않는다. source packet은 exact 원문과 ID/digest를 전달한다.
- 기존29개+hash 선택35개=실제64개 보존. 후보764 directed edges, 무방향533쌍 중64대기/469보류.
  기존 개발 정상3쌍 모두 검색(순위1,2,1)·대기 목록에 포함. 평가 pair 정보는 검색/queue에 들어가지 않는다.
  공유 anchor가 있고 표본 구성에 과거 개발군을 포함했으므로 전체 corpus 품질/독립 gold/새 의미 판정 통과가 아니다.
- CPU embedding load/inference/cache write20.43초, 검색+queue0.085초, 보고서 직전까지21.06초. cache miss/LLM0회.
  공통 주장·지지 판정·agent 생성은 미실행. 1,000댓글60초/300초 목표 달성으로 읽지 않는다.
- plan/report/vectors/HTML: private `runs/raw-candidates-20261012/`. 원문 만료 상속2026-11-08T18:30:59.664629Z.
  저장 벡터 replay 새 모델 호출0으로 일치. Python349개/Node4개 통과. 공개 Git에 원문·출력·가중치 없음.
- support는 고정 주장에 대한 canonical 댓글별 통과 수이며 유사도/좋아요/별도 claim 수가 아니다.
  미검사는 비지지가 아니다. 주요 `max(10,ceil(5%*N))`/제한적3개 이상/희소1~2개는 잠정 표시안이며 미구현·미검증이다.
  현재 support_count=null, agent0, quality_gate_passed=false. 수치 기준만으로 agent 승인하지 않는다.
- **다음 구현**: 저장64쌍의 두 원문에서 공통 주장 제안 → 원문 각각의 직접 지지·조건/시점 보존 검사.
  기존 실패 회귀와 별도 실제 표본을 함께 평가한 뒤 고정 주장별 댓글 집계로 진행한다.
  그다음 latency profiling/최적화→자동 agent/UI→end-to-end 평가. 사람의 승인 파일을 runtime 필수 입력으로 넣지 않는다.
  기존 Factory0.2/main/과거 실행은 유지하고 PR21 draft 미병합이다. 아직 전체 자동 MVP 완료가 아니다.

## 이전 위치 선택과 추출 전 검색 병목 2026-10-12

- [실행 결과·재현](EVIDENCE_POSITIONS_DIAGNOSTIC.md), ADR-025, DATA_CONTRACTS 위치 진단 계약이 최신입니다.
  코드 `ed9b98e`. 기본 Factory0.2와 이전 실험은 유지합니다. `evidence_positions`는 진단 전용입니다.
- topic 첫/끝 token ID→host 원문 복사/offset 재결합, position_units→FINAL_EVIDENCE만 읽는 검사→units를 구현했습니다.
  기존 합성16+실제24개는 이전 선택 범위를 고정했습니다. 알려진 정상3쌍의 endpoint5개만 새 선택하여 총45입력입니다.
- GPU Qwen133요청. 첫 CPU fallback partial run은 보존하고 중단했습니다. CUDA 경로만 수정한 새 gpu run에서
  코드/라벨/선택/상한 변경 및 CPU cache 재사용 없이 실행했습니다. runtime 관측/model hash도 private 저장했습니다.
- 고정 정상7/8·제외7/8로 기존과 동일합니다. 정상1개는 이미 selector에서 소실됐고 지시 대상 없는 확언1개가 계속 통과합니다.
  topic 오류9개/5sources는 모두120자 초과입니다. 위치 선택이 문자 추가를 막아도 필수 짧은 topic 계약으로 정상 후보가 사라집니다.
- 실제 개발12개: 위치12→final11units. 기존 확인12개:12→8units. 추가5개:7→6units.
  확인 최종8개 전수 검토는 정상 주장5·미해결 지시어2·저장 근거 문맥 누락1. final 검사는 알려진 실패를 해결하지 못했습니다.
  같은 position12개에서 final이 제거한4개 중3개는 원문 주장,1개는 수사 의문문입니다. 과잉거절을 개선으로 보고하지 않습니다.
- 이전 확인12units의 원래 evidence에 final만 적용해도 정상7/8유지·알려진 실패0/3차단입니다. 추가 LLM 감사의 효용 입증 실패입니다.
- 동일 실제29source의 raw/position31/final25units 검색: 기존 정상3쌍 raw3/3노출(순위1,2,1), 추출 후 양쪽source 잔존0/3.
  cross-mode/hybrid 동일합니다. 한 member는 명시적 주장이 있어도 selector가 비실질로 제외했고, 다른 anchor의 짧은 첫 주장은
  선택에서 빠졌으며 나머지3개 후보도topic길이에서 거절됐습니다. 후자의anchor가2쌍에 공통입니다. 전체 corpus recall/의미 가입 성공 아님.
- 품질 기준 실패로 assembly/새 agent 생성/전체1,000개 재실행은 하지 않았습니다. 모델·프롬프트·threshold 튜닝도 추가하지 않았습니다.
- private 종합 `artifacts/evidence-positions-overview-20261012.html`, 평가 `artifacts/evidence-positions-review-20261012.json`,
  raw/HTML `runs/evidence-positions-20261012-gpu/`. 새 LLM/embedding 호출0으로 replay 일치. Python331개/Node4개 통과.
  모델 서버 종료. PR21 draft/main 미병합 유지. 실제 원문·출력·가중치는 Git 제외입니다.
- 다음 우선순위는 **원문 검색 후보 보존 → 후보별 원문 기반 공통 주장 검사**인 retrieval-first 비교입니다.
  selector/top4/필수topic으로 검색 전 원문을 영구 제거하지 말고 topic을 선택적 검색 보조로 분리해야 합니다.
  이 새 경로는 아직 미구현이며 이번 판정 실패를 승인하거나 의미 가입 기준을 완화하는 뜻이 아닙니다.

## 이전 OpenJev 로컬 비교 2026-10-12

- [OpenJev 결과·설치·재현](OPENJEV_COMPARISON.md)와 ADR-024가 최신입니다. TypeSafe 상용 Jev가 아니라
  공개 OpenJev2B v5입니다. API 댓글 전송/전체1,000개 재실행/새 agent 생성/기본 모델 교체는 하지 않았습니다.
- eab12f8에서 첫53개 비교를 고정했고 GPU 의존성 다운로드만 중단했습니다. OpenJev 추론 전270fea0에서
  별도 CPU 계획과 typed routing 계획을 고정했습니다. 입력/라벨/threshold0.8은 변경하지 않았습니다.
- CPU 직접53개: 합성 정상 DeBERTa12/12→OpenJev11/12, 왜곡 비승인6/12→12/12.
  실제13개 정상8/8·왜곡3/5는 두 모델 동일합니다. 의미 추가2개를 OpenJev도 높은 점수로 승인했습니다.
  직접 eligibility 정상0/8→5/8, 제외8/8→6/8. 미해결 지시어2개 오승인이 새로 생겼습니다.
- 별도 typed16개/모델당48요청: routing 정상2/8→8/8이나 제외6/8→3/8.
  상대/절대 점수0.8 strict는 OpenJev 정상2/8·제외8/8로 과잉거절입니다. 기본 도입 조건 실패입니다.
- 두 비교 오류0이며 raw score/logits/입력 hash에서 모델 재호출0회 replay 일치. 작은 assistant 개발 평가이며
  독립 gold/미사용 실제 자료/다국어·찬반 경향 분류 검증이 아닙니다. 실패를 고치기 위한 추가 prompt 튜닝은 하지 않았습니다.
- 직접53요청 추론 합 DeBERTa10.24초/OpenJev68.45초, peak RSS1.53/10.33GiB.
  CPU6threads/float32, OpenJev reference 커널 및 swap 관측입니다. GPU/최적화 환경·전체 pipeline wall time 점수가 아닙니다.
- 기존 clustering venv는 그대로입니다. `/home/taeng/.venvs/commentscope-openjev`는 기존 CPU torch를 .pth로
  읽기 전용 참조하고 transformers5.19/hub2.2/httpx2를 별도 설치했습니다. embedding은 이 새 환경에서 실행하지 마세요.
  README optional `.[openjev]`는 독립 venv 전용입니다. 기본 CI에는 모델/의존성을 다운로드하지 않습니다.
- private 화면: `runs/openjev-comparison-20261012-cpu/overview.html`, `runs/openjev-routing-20261012/overview.html`.
  해당 report/plan/원시 checkpoint와 실패한 최초 GPU 계획을 보존했습니다. 실제 원문/출력/가중치는 Git 제외입니다.
- Python317개/Node4개 로컬 통과. PR21 draft/main 미병합 유지. 이번 모델 프로세스는 실행 완료 후 종료됐습니다.
- 다음: topic quote를 원문 위치 선택으로 제한 → 최종 evidence 기준 지시 대상/문맥 검사 → 알려진 실제 연결의
  retrieval recall 검증. OpenJev는 후보 부품으로만 남기며, 정상 과잉거절/실제 의미 추가를 모델 크기만으로 해결됐다고 주장하지 않습니다.

## 이전 원문 선택과 실행 계약 검증 2026-10-12

- [원인·수정·증거](EVIDENCE_SELECTION_DIAGNOSTIC.md), ADR-023, DATA_CONTRACTS 원문 선택 진단 계약이 최신입니다.
  기본 Factory0.2와 main은 그대로이며 `evidence_units`/`evidence_core`는 진단 경로입니다.
- 모델은 원문 sentence-ID 범위만 선택하고 host가 statement를 복사합니다. source digest/offset/focus/context를
  재결합해 검증합니다. 임의100개 원문의 변조 검사 통과는 문자 보존 검사이지 의미 정확도 보증이 아닙니다.
- 최초 d081e0f: 고정 정상1/8·제외8/8, 실제12개→1unit, 확인12개→2units.
  schema는 response_format에만 있어 모델에 보이지 않았습니다. 공식 llama.cpp 문서로 기제를 확인했습니다.
- 1b1dfd9: 선택·eligibility 두 단계만 schema를 system에도 노출했습니다. cache 전에 구성해 raw request와 hash가
  실제 prompt를 반영합니다. 모델/decoding/NLI/기대값/표본/기존 의미 감사는 변경하지 않았습니다.
  고정 정상7/8·제외7/8, 실제12개→13units, 확인12개→12units. 인용 없는 지시어 오승인과 정상 경험 누락이 남습니다.
- 확인12개에서 생성된12units를 전부 assistant가 검토했습니다. 실질 주장8개, 미해결 지시어2개,
  최종 evidence 문맥 누락1개, 수사 의문문 모호성1개. 독립 gold/사실 확인/서비스 수동 승인이 아닙니다.
- 기존20claims의 문맥 ablation은500자 이내16개에서 모델 승인9→13. 복지 문맥 복구와 함께 잘못된
  otherwise 연결도 새로 승인했습니다. 품질 향상 점수로 쓰지 않습니다.
- 실제64개 새 추출:59units/35sources, 이웃 보유10개/3source 가능anchor1개, 각 순서2결정→0agent.
  자동 밀집32개:22units/16sources, 이웃 보유6개/3source 가능anchor2개, 각 순서4결정→0agent.
  degree/source_density 모두 예산 미소진입니다. 순서 개선/새 agent 생성 효과가 입증되지 않았습니다.
- 주제 인용의 자유 텍스트 복사가 원문과 달라64개에서24건,32개에서3건 거절됐습니다. 조건·NLI·공통 후보
  실패도 남습니다. 실제 새 profile이 없으므로 새 agent 질문/토론은 실행하지 않았습니다.
- private `artifacts/evidence-units-overview-20261012.html`이 한눈에 보는 결과입니다.
  원시 `runs/evidence-units-20261012/`, `runs/evidence-units-20261012-visible/`,
  사후 평가 `artifacts/evidence-units-evaluation-20261012.json`. 최초/보완 probe 및 두 조립을 모델 호출0으로 replay했습니다.
- 다음 우선순위: 주제 인용도 자유 텍스트 대신 원문 위치 선택으로 계약 분리 → **최종 저장 evidence**의 지시 대상
  완결성 검사 → 알려진 cross-source 공통 주장으로 원문 retrieval recall 측정. 이 세 가지는 아직 후속 미구현입니다.
  표본에 맞춘 단어 차단/threshold 완화/전체1,000개 재실행으로 넘어가지 않습니다. 밀집 표본도 과거 생성 claim 기하의
  영향을 받아 대표성이나 회수율 개선 증거로 쓰면 안 됩니다.
- Python301개/Node4개 로컬 통과. 원문·실행 결과·모델은 Git 제외, PR21 draft/main 미병합 유지입니다.

## 이전 검색과 방향성 검사 2026-10-12

- ADR-022 / AUTOMATIC_FACTORY 최신 절 / DATA_CONTRACTS 방향성 검사 계약부터 읽습니다.
  `candidate_search`와 `grounded_core`는 진단 전용이며 기본 Factory0.2·main은 그대로입니다.
- 검색 비교는 동일123claims/vector를 재사용했습니다. 유형 제한25개/3출처 가능14개,
  제한만 제거45개/27개, semantic8+lexical4 혼합123개/123개입니다. 알려진 정상 cross-source3개는
  모두 기존 검색도 찾았으므로 검증된 recall 개선으로 주장하지 않습니다.
- 첫 방향성 검사(f5b7445)는 exact 정상4/6·오류5/6, 합성7/7·8/9, 실제6/7·11/11,
  추가주제6/6·6/6. 조건 삭제와 미래→현재 오승인을 보존했습니다.
- 조건/명시적 시간 표지 코드 보완(9f6741b)은 모델 재호출0으로 재평가했습니다.
  exact4/6·6/6, 합성7/7·9/9, 실제5/7·11/11, 추가주제6/6·6/6입니다.
  실제 정상에서 self 제외1/3으로 악화됐습니다. 오탈자 조건 표현을 guard가 과잉거절합니다.
  관점 연결 라벨과 새 대표 문장 충실성은 별개이며, 교통요금 조건이 일반 가격 조건으로 넓어진 core도 남습니다.
- 새64개 조립: 기존 추출123개 재사용→seed64회→새 agent0, 예산 소진, 미배정123.
  고유66claims 중 source 검사31개 통과, seed53개 source 실패·11개 공통 후보 실패.
  실제 가입/새 agent 답변 단계에 도달하지 못했습니다. 넓은 검색이 degree 순서를 무의미하게 만드는 예산 문제도 남습니다.
- 별도12개 댓글은 실행 전 private 평가 계획을 고정하고 새 추출했습니다(7d3a82b).
 20claims/모델 승인12개/빈 source4개. 사후 검토에서 명백한 새 의미 추가2개, 독립성 실패1개,
  자기 댓글의 필요한 문맥을 span에서 누락한 사례를 확인했습니다. 독립 gold/완전히 미사용 corpus가 아닙니다.
- private 요약 `artifacts/grounded-core-overview-20261012.html`, 상세 평가 `artifacts/grounded-core-evaluation-20261012.json`.
  원시 결과는 `runs/grounded-core-20261012`, `...-v2`, `grounded-core-new-sample-20261012`입니다.
  첫58개/보완58개/seed64개/새12개 추출과 검사 모두 모델 재호출 없는 replay로 확인했습니다.
- **다음 우선순위:** 독립적 실질 주장 eligibility와 문자 그대로의 entailment 분리 → 같은 댓글 안의 근거 문맥 완성
  (부모 내용 전이 금지) → 추가된 술어/속성 판정 비교 → source-diverse seed 우선순위/추가 검색 평가.
  bounded 재추출·문맥 보완·새 판정기 비교는 아직 미구현입니다. 단순 threshold 완화·새 어휘별 예외·전체1,000개 재실행 금지.
- 최신 Python289개/Node4개 로컬 통과. 기존 실패 버전과 core/frame 실험은 삭제하지 않았습니다.
  PR21 draft 유지, 품질 승격/정식 agent 승인0, 전체 프로젝트·자동 생성 MVP 미완료입니다.

## 최신 공통 주장과 시간 보존 구현 2026-10-12

- ADR-021 / AUTOMATIC_FACTORY의 공통 주장 탐색 절 / DATA_CONTRACTS 진단 계약이 최신입니다.
  temporal_guard→shared_core→core_groups→진단 profile/기존 AgentSession 연결을 구현했습니다. 기본 Factory0.2는 유지합니다.
- 로컬 모델은 공통 후보1개만 제안합니다. 기존 claim2개와 함께 고정 비교하며 NLI 원문/claim 지지, 시간/강도,
  명시적 영어 조건/개인 행동 범위를 검사합니다. 모델 제안은 근거가 아니며 수동 service 판단은 추가하지 않았습니다.
- 최초 개발: 합성6/7·9/9, 실제5/7·11/11. modal 표지 보정 후 실제6/7이지만 개인→일반 회귀로 합성음성8/9.
  범위 차단 보완 최종: 합성6/7·9/9, 실제6/7·11/11. self 제외 실제 정상 연결2/3이며 취직/계속 근무 뉘앙스는 사후 주의 사례입니다.
- 새 주제12개(첫 실행 전에 fixture 고정): 정상5/6·오류6/6. 기존 실제18개 반복 결과도 일치. 독립 gold/미사용 실제 자료 아님.
  임대료 조건 동의어, 물가 원문1개, 도서관 권고의 시간 오분류가 남습니다. 원래 모든 사례 일치 조건은 실패입니다.
- 사용자의 전체 진행 요청에 따라 품질 승격과 분리한 기능 진단을 명시적으로 추가했습니다. manifest quality_gate_passed=false,
  CLI --diagnostic-only 필수. source-only0.2의64개/123claims→28seed→0agent, 예산64 미소진, 미배정123입니다.
  원문3개 공통 지지를 얻지 못했으므로 실제 새 agent 질의는 하지 않았습니다. 전체1,000개 재추출/새 수집도 없음.
- private runs/shared-core-probe-20261012(-v2,-v3), shared-core-transfer-20261012, shared-core-integration-20261012의
  report.json/overview.html. hash/명령은 AUTOMATIC_FACTORY에 기록했습니다. 첫 코드b13f10b, 두 번째8090a86으로 중간 실패도 보존.
  최신 실제 실행 코드0924733. 사후 private 검토는 artifacts/shared-core-evaluation-20261012.json이며 기존 기대값과 구분합니다.
- Python271개/Node4개 로컬 테스트 통과. 고정34개·추가30개와28개 조립 결정을 모델 재호출 없이 replay했습니다.
  source-bound3개 합성 profile→기존 AgentSession 응답까지 mock 기능 검사했으며 의미 품질 점수로 세지 않습니다.
- 다음 병목은 정상 주장에 대한 시간/강도 분류의 과잉거절, 조건/함의 판정과 공통 명제의 세부 뉘앙스입니다.
  field equality/영어 표지 몇 개가 일반 의미 보증인 것처럼 보고하지 말고, 기존 기대 라벨과 새 대표 문장 충실성도 구분해야 합니다.
  PR21 draft/main 미병합 유지. 기본 승격이나 전체 재실행 전에 미사용 실제 평가와 후보 coverage 분석이 필요합니다.

## 최신 NLI 직접 지지 판정 비교

- ADR-020과 LOCAL_NLI_COMPARISON의 최신 원문 span/claim 절이 최신입니다. 기본 Factory0.2와
  opt-in frame0.3은 변경하지 않았습니다. `experiments/claim_support_probe.py`로 동일34개 사례만 비교했습니다.
- 기존 로컬 DeBERTa NLI/CPU/threshold0.8 고정. 원문→claim/공통 claim을 보는 directional과 claim간 양방향까지
  요구하는 mutual_claims를 사전 고정했습니다. 평가 라벨은 모델에 전달하지 않고 수동 service 입력도 추가하지 않았습니다.
- 양 정책 모두 합성 정상7/7·오류8/9, 실제 정상5/7. 실제 오류는 단방향10/11, 양방향11/11.
  실제 정상 중 anchor self4개를 제외하면1/3유지입니다. 현재/미래 혼합과 물가 원문2개의 과잉거절이 남습니다.
  높은 NLI 점수도 시점 오류를 놓칩니다. 임계값/기대 라벨을 결과에 맞춰 바꾸지 않았습니다.
- 사전 다음 단계 조건은 양성/음성 모두 일치/오류0이며 두 정책 모두 실패했습니다.64/1,000개 실행이나 새 agent 생성 안 함.
  영어용 모델의 한국어 합성1개 통과는 다국어 검증이 아닙니다. 기존 개발18개 assistant 평가이지 독립 gold도 아닙니다.
- private `runs/claim-support-nli-20261011/report.json`, `overview.html`, manifest와113개 checkpoint.
  고유 추론10.86초/로딩1.04초, IO/import 제외.34사례 전부 cached replay 일치. 원문/출력은 Git 제외입니다.
- Python255개/Node4개 로컬 테스트 통과. PR21 draft/main 미병합 유지. 새 다운로드/수집/유료 API/서버 실행 없음.
- 다음은 시간 보존 검사와 최소 공통 명제 자동 탐색을 분리 설계할 단계입니다. 이 둘은 아직 미구현입니다.
  모델 교체·양방향 강화만으로 자동 관점 생성이 해결됐다고 주장하거나 전체 재실행으로 넘어가지 않습니다.

## 최신 호환성 필터 실험 — 기본 미채택

- ADR-019 / AUTOMATIC_FACTORY의 호환성 필드 실험 / DATA_CONTRACTS0.3을 먼저 읽습니다.
  새 `claim_frame.py`는 원문·claim 별도 분류→범위/시간/강도/조건 코드 비교→기존 source/common 검사 구조입니다.
  입력 hash와 원시 component/조건 비교/차단 사유를 기록하고 loader가 replay합니다. 서비스 수동 입력은 추가하지 않았습니다.
- 실제 모델 실험 두 번: 한 요청 방식은 합성 양성3/7유지·음성8/9차단, 실제 개발 양성5/7·음성11/11.
  4작업 분해 방식은 합성 양성0/7·음성9/9, 실제 양성0/7·음성11/11로 전부 차단했습니다.
  단순한 문장도 status가 unclear/mixed로 잘못 분류됩니다. 전부 거절은 성공이 아니며 모델/방법 승인하지 않았습니다.
- 기본0.2를 유지하고 `--experimental-frame-guard`에만0.3을 연결했습니다. 실패한 필터로64개/전체 재실행은 안 했습니다.
  기존0.1 전체8agent,0.2 64개0agent artifact의 현재 loader 재검증 완료. 새 agent가 추가 생성된 것이 아닙니다.
- 결과 `runs/claim-frame-probe-20261011/report.json`, `runs/claim-frame-probe-20261011-v2/report.json`.
  기존18member assistant 라벨은 offline 비교에만 사용했고 모델에는 전달하지 않았습니다. 독립 gold 아님.
  합성16사례 fixture와 실행 코드는 공개, 실제 원문/출력은 Git 제외. PR21 draft/main 미병합 유지.
- 로컬 Python247개/Node4개 테스트 통과. 기본 경로의 frame 요청0회, 명시적 opt-in/replay,
  frame 거절 후 의미 검사 미호출, 빈 실행 policy 검사, JSON key 정렬 후 오류 replay를 확인했습니다.
- 다음은 실패 필드 classifier의 대체 비교를 고정 입력에서 제한적으로 설계할 단계입니다.
  정상 보존을 먼저 만족하지 못하면 full run으로 넘어가지 않습니다. 한국어 답변 왜곡/검색 recall도 여전히 남아 있습니다.

## 최신 원문 격리 보완

- PR #21의 같은 브랜치에0.2 입력/감사 분리(`01cf6cf`)와 scope 독립 지침(`b46d09d`)을 추가했습니다.
  ADR-018, DATA_CONTRACTS, AUTOMATIC_FACTORY 최신 회귀 절을 먼저 읽습니다. 아직 draft이고 main 미병합입니다.
- 추출에는 자기 댓글만, source gate에는 자기 span과 검사할 claim만 제공합니다. parent/common claim을 원문 검사에
  주지 않습니다. 답변 생성에서는 profile/title/allowed_claim을 제외하고, source 감사와 scope 감사를 별도 요청으로 분리합니다.
  source 실패를 scope로 구제하지 않습니다. context_dependent 계약은 추가했지만 실제43개 재추출에서는 uncertain으로 보류했습니다.
- 기존27배정 claim 원문 재검사15통과/12거절. 이전 assistant 라벨18개 대조는 충실9/9유지·오류7/8차단·불명확1통과.
  부모 전이7개는 모두 차단됐지만 조건부 자동화의 무조건적 해석은 남았습니다. 독립 gold가 아닙니다.
- 43source 재추출91claims. 동의3개 빈 claim, 부모 개인 경험 복사 제거. 사용자명→주제어 오해 등 새 오류는 남습니다.
  source gate reason26/27개가300자 상한에 닿았습니다. 검사 설명을 완결된 근거로 취급하지 않습니다.
- `runs/automatic-factory-20261011-sourceonly64/`: 실제64개 →123claims→61edge→0agent. 예산 미소진,
  품질 성공 아님. 현재 loader 재검증 완료. 전체1,000개0.2 실행은 하지 않았습니다.
- 기존8profile을 바꾸지 않고 CLI 답변 회귀: scope 지침 첫 분리본은8개 모두 보류, 지침 충돌 수정 후 A002/A003/A004만 공개.
  A002는 사후 읽기에서 부합하지만 A003의 생활 수준·소비 유도 해석, A004의 취직→직장 유지 변화가 남습니다.
  근거 밖 한국 지급액/연도 질문은8개 모두 보류. 새 factory가8개를 생성한 것이 아닙니다.
- 상세 private 결과: `artifacts/source-isolation-evaluation-20261011.json`,
  `runs/source-isolation-probe-20261011/report.json`, `artifacts/source-isolation-runtime-20261011-v2.json`.
  코드를 제외한 corpus/출력은 Git 제외이며 원본 배정은 수정하지 않았습니다. 테스트235개/Node4개 및 Windows/Linux CI 통과.
- 다음은 scope·시점·조건 명시적 필드/호환성, 한국어 실현 오류 및 과잉 거절 평가. 그 다음 검색 recall·예산·중복.
  모델/프롬프트 승인이나 무작정 전체 재실행으로 넘어가지 않습니다. 모델 서버는 검증 후 종료합니다.

## 최신 작업과 서비스 자동화 요구

- 사용자는 서비스 실행 중 사람이 clustering을 다루지 않는다고 명확히 했습니다. 요구사항 Section16.10,
  ADR-017, `AUTOMATIC_FACTORY.md`를 우선 확인합니다. 아래 검수 지원 시연은 과거 기준선입니다.
- `feat/automatic-perspective-factory`에서 검수 파일 없는 자동 경로를 구현하고 실제 전체 실행을 마쳤습니다.
  `factory.automatic_cli build` → 원문 span claim → embedding 후보 → 직접 근거 gate → automatic bundle.
  `agents.web --automatic`으로 기존 UI를 사용합니다. 기존 `--allow-unapproved` 시연 경로와 혼동하지 않습니다.
- Python231개(자동 경로21개 포함), Node DOM계약4개가 통과합니다. PR #21의 Windows/Linux CI도 통과했습니다.
  의미 품질 검증과는 별개입니다. 현재 PR은 draft이며 아직 main 병합 전입니다.
- 실제64개 hash-order 표본은 주장134개·gate82건·agent0개로 종료했습니다. 품질 성공이 아닙니다.
  결과는 `runs/automatic-factory-20261011-smoke64/`에 보존했습니다. 이 실행에서300자 상한에 닿은 잘린 문장을 발견해
  이후 validator가 차단하도록 수정했습니다. 따라서 과거 smoke를 현재 loader로 승격하지 않습니다.
- 전체1000개 snapshot 실행 완료: `runs/automatic-factory-20261011-full1000/`, duplicate1개 제외999개 선택,
  주장1829개 → 의미 gate2000건(예산 소진) → 잠정 agent8개 / 반영 원문27개(2.7%) / 미배정 주장1802개.
  source 상태는 claims719/uncertain279/extraction_failed1. 관측 실행 간격 약95분, 즉시 응답형 서비스 성능이 아닙니다.
  모델은 loopback8091, Qwen4B Q4_K_M, ngl99/ctx8192/batch128/ubatch128/threads6/parallel1/no-context-shift.
  유료 API나 새 댓글 수집 없음. 최종 출력과 검증을 완료하고 소유한 UI/모델 서버는 종료했습니다.
- full1000 실행 코드는 `4287773`으로 고정했습니다. 후속 빈 snapshot 집계 수정은 실행 중인 비어 있지 않은 데이터의
  판단을 바꾸지 않습니다. 완료한 출력은 현재 loader로도 재검증했습니다. manifest나 기존 출력을 수정하지 않습니다.
  변경 알고리즘의 재실행에는 새 run directory를 사용합니다.
- 이미 검수한21개/기대 라벨은 새 자동 입력에 쓰지 않습니다. 사후 점검 계획은 private
  `artifacts/automatic-factory-20261011-evaluation-plan.json`에 gate 출력 전에 고정했습니다.
  선택한5개 group의 전18member, 미배정10개, zero-claim5개를 assistant가 점검했습니다. 모든 member의 충실성/공통 주장
  지지가 성립한 group1/5, member7/18. 부모 주장→짧은 동의 답글 전이, 개인/일반 범위, 미래/현재 혼합 실패.
  독립 gold나 전체 정확도가 아닙니다. 출력 배정을 수동 수정하지 않았습니다.
- 실제 Chromium에서8개 agent ×2질문 실행 및 인용/다운로드/모바일/초기화/새 탭 분리 통과.
  일반 설명은8개 모두 모델 감사가 통과시켰지만, 오염된 claim 재사용과 한국어 오역·scope 누출을 assistant가 발견했습니다.
  근거 밖 한국 지급액/시행연도 질문에는8개 모두 보류. 기능 통과≠의미 품질 통과.
- 먼저 볼 결과: `artifacts/automatic-factory-20261011-summary.html`. 원문별 결과는
  `runs/automatic-factory-20261011-full1000/overview-ko.html`, 실제 답변은
  `artifacts/automatic-factory-20261011-full1000-browser.comparison.html`, 평가 이유는
  `artifacts/automatic-factory-20261011-assistant-evaluation.json`. 전부 Git 제외입니다.
- PR #21은 품질 실패가 명시된 draft로 유지하며 main은327e5c9 기준선입니다. 코드 테스트 통과를 근거로 완료/승격하지 않습니다.
  다음은 독립 주장/동의 관계 분리와 parent-blind 원문 검사, model-authored claim을 증거로 취급하지 않는 감사 비교부터.
  이어 scope·시점·조건 호환성 → 검색 recall/예산/중복 → 미사용 평가 표본 순서입니다. 아직 후속 개선은 구현하지 않았습니다.
- 별도1-source 입력으로0-agent UI를 실제 Chromium에서 검증했습니다. 질문/내보내기 비활성화, 자동 보류 표시,
  모바일 overflow 없음. `artifacts/automatic-factory-20261011-empty-browser.checks.json` 및 screenshots.
- 자동 실행용 embedding 환경은 `/home/taeng/.venvs/commentscope-clustering/bin/python`, `PYTHONPATH=src`입니다.
  프로젝트 `.venv`에는 numpy/torch/sentence-transformers가 없어64개 추출 후 embedding import에서 첫 실행이 중단됐습니다.
  동일 manifest의64개 추출 checkpoint를 재사용해 기존 clustering 환경에서 재개했습니다. 새 CLI는 모델 호출 전 의존성을 검사합니다.

## 이전 main 통합 기준선

**최신: PR #18 main 통합 및 누적 PR 정리 완료. 실제 데이터 재검증→새 개발 profile2개 생성→Chromium에서 실제 Qwen 질의3개/인용/다운로드/초기화/새 탭 분리까지 확인. 검수 지원형 agent 생성·실행은 동작하지만 정식 승인0이고 자동 factory는 미완료. 고정12개 자동 회귀는 계약10/12·사전 기준 전체 일치6/12. 한눈에 보는 로컬 결과 `artifacts/main-acceptance-20261011-overview.html`. 전체 프로젝트 목표는 댓글 기반 관점 에이전트 시스템이며 clustering 자체를 논문 목표로 되돌리지 말 것.**

## 사용자 결정과 작업 단위

- 공식 YouTube Data API를 사용합니다. 실제 키 발급·YouTube 전용 제한·인증 확인 완료. 키 값은 저장소/채팅에 남기지 않습니다.
- 첫 후보는 Kurzgesagt 기본소득 영상 `kl39KHS07Xc`. `data/ubi-research-20261010.json`에 최상위 567 + 답글 433개를 저장했습니다.
- 최신 사용자 정정: 일차 목적은 **유의미한 주장을 가진 댓글 클러스터를 충실히 대변하는 agent**입니다. Debate/forum은 후속 활용이지 클러스터 선정의 목적함수가 아닙니다. 대립·찬반 균형·토론 재미를 강제하지 않습니다.
- 팀원들은 비개발자입니다. 다음 목표는 댓글을 입력하면 cluster와 근거를 검토할 수 있는 MVP입니다.
- 내부 구현은 순서대로 하되, 인터페이스/계약만 구현한 상태를 사용자 MVP 완료로 보고하지 않습니다.
- 로컬 모델 우선으로 검증합니다. 모델의 최종 품질 승인과 실제 corpus의 분석·외부 전송 사용 조건은 미결정입니다.

## 현재 Git 운영 기준

- 통합 작업: [PR #18](https://github.com/joowonkime/commentscope/pull/18), base=`main`, branch=`chore/main-prototype-baseline`.
  사용자 진행 요청 후 merge commit `a3ead01`로 main 통합 완료. main push CI도 Ubuntu/Windows 통과했습니다.
- PR #6은 포함 커밋으로 merged 처리됐고, #7~#17은 각각 main에 포함된 것을 확인한 뒤 #18을 연결해 closed 처리했습니다.
  수집 Issue #5도 closed이며 기존 브랜치/커밋/실험/로컬 데이터를 삭제하지 않았습니다.
- 다음 시스템 작업은 [Roadmap #19](https://github.com/joowonkime/commentscope/issues/19)로 추적합니다.
- `main`은 최신 연구 프로토타입의 공통 시작점입니다. 코드 통합과 모델 품질 승인은 별개입니다.
- 통합 범위: 기존 PR #6~#17의 14개 커밋(공식 수집→실험/검수→개발 agent→로컬 UI)과 현재 상태 문서 정리.
- 통합 전 main은 snapshot ingestion까지만 포함했습니다. 최신 구현이 없었던 것이 아니라 Draft PR에만 누적된 상태였습니다.
- 이번에는 기존 커밋·브랜치·실패 실험을 삭제하지 않습니다. 원문·모델 파일·대화 기록도 계속 Git 제외입니다.
- 이후 새 기능은 최신 main에서 분기하고 한 작업의 검증/통합을 마친 뒤 다음 작업을 진행합니다. 누적 Draft 체인을 반복하지 않습니다.
- 실제 원격 병합/열린 PR 상태는 GitHub에서 확인합니다. 아래 과거 브랜치 기록은 실행 당시 이력이며 현재 작업 지시가 아닙니다.

<details>
<summary>통합 이전의 브랜치·PR 누적 이력 (보존용)</summary>

- 저장소: https://github.com/joowonkime/commentscope (public)
- 수집 브랜치: `feat/youtube-collection`; 로컬 모델/검증 문서는 이를 기반으로 한 `feat/local-model-validation`에서 관리합니다.
- 소표본 claim 연결: `feat/claim-cluster-slice` (`feat/local-model-validation` 기반). PR #7의 Linux/Windows CI 성공 확인 후 분기; main 병합은 아직 하지 않음.
- 로컬 대표 초안/검사: `feat/local-perspective-drafts` (`feat/claim-cluster-slice` 기반). 이전 PR을 임의 병합하지 않음.
- 쌍별 근거 검사: `feat/pairwise-source-audit` (`feat/local-perspective-drafts` 기반). PR #9의 Ubuntu/Windows CI 성공 확인 후 분기. main 병합은 하지 않음.
- 프롬프트 단독 비교: `feat/entailment-audit-prompt` (`feat/pairwise-source-audit` 기반). PR #10 Ubuntu/Windows CI 통과 상태에서 진행. 상위 브랜치 임의 병합 없음.
- 실패 단계 진단: `feat/source-stage-diagnostic` (`feat/entailment-audit-prompt` 기반). PR #11 Ubuntu/Windows CI 통과 이후 진행. 상위 브랜치 임의 병합 없음.
- 원문 선택형 B: `feat/extractive-keypoint-baseline` (`feat/source-stage-diagnostic` 기반). PR #12 CI 통과 이후 진행. 상위 브랜치/main 임의 병합 없음.
- 로컬 NLI 비교: `feat/local-nli-comparison` (`feat/extractive-keypoint-baseline` 기반). PR #13 Ubuntu/Windows CI 통과 확인 후 진행. 상위/main 임의 병합 없음.
- 원문 계열/검수 루프: `feat/source-facet-review-loop` (`feat/local-nli-comparison` 기반). PR #14 Ubuntu/Windows CI 통과 이후 작업. 상위/main 임의 병합 없음.
- 에이전트 연결: `feat/evidence-agent-vertical-slice` (`feat/source-facet-review-loop` 기반). PR #15 CI 통과 이후 진행. 초기 runtime commit67e226a, 보완 문법/실행 문서가 후속 commit. 상위/main 임의 병합 없음.
- 로컬 질의 UI: `feat/local-agent-comparison-ui` (`feat/evidence-agent-vertical-slice` 기반), draft PR #17. PR #16 Ubuntu/Windows CI 통과 확인 후 진행. 구현 commit772a4e8. 상위/main 임의 병합 없음.
- Issue: https://github.com/joowonkime/commentscope/issues/5
- 설계 PR #2와 ingestion PR #4는 main에 반영했습니다.
- 수집 PR의 CI·검토·병합 상태는 다음 작업 전에 확인합니다.

</details>

## 실행

설치된 현재 WSL 환경에서는 저장소 루트에서 실행합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m commentscope collect-youtube "https://www.youtube.com/watch?v=VIDEO_ID" --prompt-key --max-comments 100 --top-level-limit 40 --max-requests 30 --output data/first-video-smoke.json
.venv/bin/python -m commentscope validate data/first-video-smoke.json
.venv/bin/python -m commentscope normalize data/first-video-smoke.json --output artifacts/first-video-normalized.json
```

위 명령은 새 영상을 위한 템플릿입니다. 기존 기본소득 후보는 이미 수집했으므로 불필요하게 재수집하지 않습니다.
`data/ubi-smoke-20261010.json`, `data/ubi-research-20261010.json`과 대응하는 `artifacts/ubi-*-normalized.json`을 사용합니다.
환경변수 `YOUTUBE_API_KEY`도 지원합니다. `.env` 자동 로딩이나 명령행 key 인자는 없습니다.
기존 결과는 덮어쓰지 않으므로 재실행 때 새 파일명을 사용합니다.
키 발급부터 상세 순서는 [공식 수집 안내](YOUTUBE_COLLECTION.md)에 있습니다.

## 공식 수집 단계의 확인 범위 (과거 기록)

- 기존 snapshot validation/normalization과 원자적 저장.
- 공식 videos/commentThreads/comments GET, 키 header 전달, redirect 차단, 제한된 retry.
- relevance/time 표집, ID 중복 관측 기록, 답글 round-robin pagination.
- source/호출/스레드별 답글 상한, partial 표시, provenance와 보관 만료 metadata.
- 기존 29개 + 수집 24개 = 53개 unittest 메서드. 로컬 오프라인 검사 통과.
- CI도 실제 API 키 없이 fake HTTP 응답을 사용합니다. 최신 결과는 PR Checks를 확인합니다.

공개 API의 `textDisplay`를 plainText로 보존하며 작성자의 raw `textOriginal`을 확보했다고 주장하지 않습니다.
이 수집 단계 자체에는 자동 삭제/갱신이 없습니다. 이후 추가한 agent/UI 경로는 만료된 입력의 실행·열람을 차단합니다.
기존 다운로드 파일의 접근 차단이나 자동 삭제까지 구현한 것은 아닙니다.
실제 키·영상 응답과 100/1,000개 표본의 validation/normalization은 검증했습니다. 분석 성능은 아직 검증하지 않았습니다.
수집 설정·만료·후보 비교·표본 한계는 [수집 기록](YOUTUBE_COLLECTION.md#첫-live-후보-기본소득-토론-2026-10-10-kst)을 확인합니다.

## 이어서 할 일

1. 현재 PR과 작업 트리를 확인합니다. 기존 기본소득 표본을 재사용하며 키/영상 선택을 다시 요청하지 않습니다.
2. AGENT_VERTICAL_SLICE.md와 README12부터 확인합니다. 필요성7/예측4의 개발 agent가 HTTP 질의 경로로 실제 응답했습니다. 검수 입력과 자동 모델 성능, 개발 agent와 정식 승인 PerspectiveSpec을 구분합니다. 서버는 자동 상주하지 않으며 모델과UI를 각각 시작해야 합니다.
3. Chromium 기본 동작/화면은 확인했습니다. 다음은 비개발자 팀원의 실제 Windows/WSL 사용성, 근거 경계를 지키는 대화/반문, Reflection과 시스템 평가입니다. 현재 UI는 독립 비교 질의이며 토론은 미구현. 자동 형성 완성까지 전체 시스템 구현을 다시 막지 않습니다. 미승인 입력을 자동 승인으로 가장하지 않고 독립 평가/정식 승격은 별도로 남깁니다.
4. Auditor는 질문의 전제를 원문 지원 검사에 섞어 과도하게 거절하는 문제가 있습니다. 이 부분은 runtime 검사 경계의 후속 개선 대상이며 clustering 재실험으로 돌아갈 이유가 아닙니다. 전체1,000개 자동 확장/유료 외부 API는 여전히 별도 조건 결정이 필요합니다.

[구조](ARCHITECTURE.md), [데이터 계약](DATA_CONTRACTS.md), [검증 목록](ACCEPTANCE_TESTS.md)을 기준으로 진행합니다.

### main 통합 후 실제 생성·브라우저 검증

- 통합 시연 기준 commit `a3ead01`. 기존 snapshot1,000개 validation/normalization 재실행(중복 정규화999개),
  기존 검수21개에서 새 `artifacts/main-acceptance-20261011-agents.json` 생성. 원시 자동 분류를 승인한 것이 아님.
- 실제 Chromium153.0.8010.12/Playwright1.63.0으로3질문×2agent, 키보드 제출·인용 펼치기·HTML/JSON 다운로드·모바일390px
  가로 넘침 없음·새 탭 세션 분리·초기화 통과. 코드 hash와 인용 binding, HTML 재생성 일치 확인. assistant가 desktop/mobile screenshot 확인.
- 최신 `artifacts/main-acceptance-20261011-browser-v2.comparison.html`, `.checks.json`, `.first-answer.png`, `.mobile.png`.
  초기 browser 실행은 마지막 검사식의 문자열 eval이 CSP에 막혔고 실패 기록을 보존. 검사식을 함수로 수정했으며 앱 CSP/모델/프롬프트는 변경하지 않음.
- 자동 분류는 기존12개 회귀에 v2를 다시 실행, `artifacts/main-acceptance-20261011-auto-regression.json`: 계약10/12,
  사전 assistant 기준 전체 일치6/12. 재사용한 개발 사례이며 독립 gold/holdout/일반 정확도 아님. 이 결과를 agent 입력으로 바꾸지 않음.
- 판단: 검수 지원형 profile 생성·runtime은 개발 기능으로 확인, 범용/전체 corpus 자동 관점 형성·정식 승격은 미완료.
  현재 연결된 source_facets 경로는 AI·자동화/UBI와 최대24개 소표본 한정. 새 모델 학습이 아니라 같은 모델의 독립 evidence/state.
- 모델/UI 서버는 검사 후 종료. 최신 완료판정은 AGENT_VERTICAL_SLICE의 main 통합 후 재검증을 우선. 이전 실행 파일은 보존.

### 이전 로컬 UI 실행과 모델 환경

- 최신 결과 `artifacts/local-agent-ui-20261011-smoke-v3.json.html` (JSON 동일 basename). 코드 hash/원문 binding/HTML 재생성 확인.
- 3질문×2agent: 첫 질문 둘 다 원문 인용, 조건 후속 질문은 필요성 보류/예측 답변, 한국 수치 질문 둘 다 근거 부재로 보류.
  필요성 후속 초안에 인용 원문에 없는 AI/AGI·장기 조건이 있어 차단. assistant 대조이지 독립 gold가 아님. 승인0 유지.
- full GPU `-ngl99`는 이번 여유 VRAM에서 OOM. 기존 모델을 `-ngl24 -b128 -ub128 -c8192 --no-context-shift -t6 --parallel1`로 실행.
  원문/실패 결과/감사 기록은 로컬 Git 제외. 첫 연결 실패 기록과 중간 v2도 보존. 최종 모델 호출17회/시간합172.50초.
- 실제 WSL 모델 경로 `/home/taeng/.cache/commentscope-models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf`,
  바이너리 `/home/taeng/.local/opt/commentscope-llama/llama-b11541/llama-server`.
  `LD_LIBRARY_PATH=/home/taeng/.local/opt/commentscope-llama/cudart-llama-b11541-bin-ubuntu-cuda-12.8-x64:/usr/lib/wsl/lib` 필요.
- Python210/JS 계약3 통과, wheel asset 포함 확인. HTTP/최소 DOM 검증은 실제 브라우저 시각·키보드 QA 대체가 아님.
  모델/UI 서버 종료됨. 다시 시작하려면 README12 사용. `runs/agent-ui` 자동 저장은 reset/종료 때 삭제되지 않으며 자동 resume 없음.

## 과거 실험 이력 — 아래의 '다음 작업'은 당시 기록

아래 기록의 agent0·미구현·테스트 개수는 해당 실험 당시 상태입니다. 현재 상태/다음 작업은 이 문서 상단과 README를 우선합니다.
실패 사례와 대안 비교는 연구 재현을 위해 보존하며, main에 통합했다는 이유로 성공 실험으로 바꾸지 않습니다.

## 로컬 LLM 타당성 검사 / 사용자 평가 방식 (2026-10-10)

- 사용자 방향: 성능을 먼저 분석하고 충분하면 로컬 모델로 비용 절감. AI가 검수 초안을 만들고 사용자가 피드백. 1,000개 전수 인간 라벨링을 요구하지 않음. 모델 초안은 독립 gold가 아님.
- 하드웨어 실측: i5-13500HX, WSL RAM 약 11GiB, RTX4060 Laptop 8GB(검사 전 free 6764MiB). CPU-only라고 가정하지 말 것.
- Qwen3-4B-Instruct-2507 Q4_K_M을 llama.cpp b11541 CUDA12.8로 로컬 실행. 파일은 Linux 저장소 밖 환경에 있음. 유료 API·외부 댓글 업로드 없음.
- 진단 스크립트: `experiments/local_claim_probe.py`. localhost:8091의 명시적으로 시작한 모델 서버를 사용. 프로덕션 extractor가 아님.
- 8개 난점 + seed407 무작위 4개: 총20.62초, 중앙값1.64초, JSON12/12, quote 문자열 검사12/12, 출력 잘림0. 서버/model 로딩 제외·prompt cache 포함. 전체 1,000개 처리 시간이나 API 대비 성능으로 일반화 금지.
- 실질 실패: 사례1/5 eligibility–claims 계약 모순; 사례10/11 의미 있는 개인 주장/경험 누락. reason에 모델 설명이 들어가기도 함. `support`의 대상을 명시하지 않은 스키마도 개선해야 함.
- 결과/피드백 화면: `artifacts/local-claim-probe-qwen4b-20261010.html`, JSON 동일 basename. AI 검수 초안: `artifacts/local-claim-probe-review-20261010.json`.
- 다음은 stance_target/조건/이유 계약 명확화, 개발 표본에서 prompt 보완, 사용자 피드백 후 새 표본 평가. 로컬 속도는 유망하나 현재 프롬프트의 품질은 미승인. 외부 API와 동등하다고 주장하지 않음.
- 유사 도구: [Talk to the City](https://github.com/AIObjectives/tttc-light-js) 우선 비교. 기존 `talk-to-the-city-reports`는 archived. 현행 시스템 전체를 가져오면 Firebase/GCS/Redis/PubSub 의존성이 있어 작은 MVP에 그대로 이식하지 않음.
- 상용 [Comments Miner](https://www.commentsminer.com/) 공개 sample report 확인: 주제/감성·원문 예시 중심. 우리 데이터 업로드·가입·결제·동일 표본 정확도 비교는 수행하지 않음.
- 평가 참고: [KPA-2021](https://aclanthology.org/2021.argmining-1.16/), [DeliberationBank/DeliberationJudge](https://arxiv.org/abs/2510.05154). 직접 YouTube gold로 취급하지 않음.
- 가까운 연구 [Agora](https://arxiv.org/abs/2603.07339)는 실제 인간 의견에 근거한 AI persona 활용. 단순 '의견 기반 agent 생성'을 새 기여라고 주장하지 말고 차별점 검토 필요.

## claims-0.2 계약 / prompt-0.2 재시험 (2026-10-10)

- 사용자 요청: 로컬 모델 우선, 스키마·프롬프트를 명확히 하고 모든 구조 결정을 지속 저장하여 부분 교체 가능하게 만들 것.
- `src/commentscope/contracts/claims.py`: stance_target, 개인/일반 scope, modality, 이유·조건과 각각의 원문 인용, eligibility 일관성 검사. 원문 출처와 claim ID는 모델이 아닌 호스트가 부여. 통과해도 semantic_review_status는 pending.
- `src/commentscope/claim_prompt.py`: claim-extraction-0.2. 프롬프트·스키마 버전/hash와 모델 revision을 진단 결과에 저장합니다.
- 동일 개발 표본 12개에 `experiments/local_claim_probe.py --revision v2` 실행. JSON 12/12, claim quote 문자열 검사 9/12, 전체 계약 통과 8/12, 잘림 0. 총 41.77초, 중앙값 3.68초(서버 시작 제외).
- 결과: `artifacts/local-claim-probe-qwen4b-20261010-v2.json` 및 `.html`. 기존 v1 결과는 보존했습니다. 여기의 probe v2는 논문 비교의 clustering V2와 별개입니다.
- **품질 개선 승인 아님.** 사례 10/11에서 이전에 누락한 개인 주장/경험을 추출했지만, 사례 7은 parent 주장을 가져왔고, 사례 8은 spam 분류 뒤 claims를 생성했습니다. 사례 9는 농담을 정책 주장으로 해석했고, 사례 10은 인용 공백을 바꿨습니다. 이 네 사례는 계약 검사에서 차단됐습니다.
- 계약을 통과한 사례에도 오류가 남습니다. 사례 1은 조건부 반대의 stance/modality가 과도하고, 사례 2/11/12에는 조건·이유 필드 누락이 있습니다. 부분 문자열 일치는 의미적 충실성의 증명이 아닙니다. 이는 AI 검수 초안이며 사용자 승인/gold가 아닙니다.
- prompt/schema/grammar/token budget을 함께 바꿨으므로 어느 변경의 효과인지 분리할 수 없습니다. v1과 검사 기준도 달라 단순 통과율 비교는 하지 않습니다. 같은 표본 반복 튜닝을 일반화 성능으로 보고하지 않습니다.
- 테스트: 전체 69개 통과. 이 수치는 코드 계약 회귀 검사이며 모델 정확도가 아닙니다.
- 다음 작업: eligibility–claims 제약의 생성 단계 적용, TARGET 인용 선택과 의미 필드 작성 분리 여부를 작은 비교 실험으로 검증. 사용자 피드백을 받은 개발 표본을 고정한 뒤 새 표본으로 평가합니다. 실패 출력을 임의 수정해 통과 처리하거나 1,000개 전체에 바로 확장하지 않습니다.
- 구조 기록은 [ARCHITECTURE](ARCHITECTURE.md)의 모듈 상태·교체 영향·ADR, 필드는 [DATA_CONTRACTS](DATA_CONTRACTS.md)를 갱신합니다. 현재 provider adapter/자동 재실행 DAG는 설계일 뿐 구현된 기능이 아닙니다.

## 생성 grammar v3 및 공개 실행 안내 (2026-10-10)

- 기존 1,000개 유지, 이번 검증의 YouTube API 호출 0회. 프롬프트0.2/출력 계약0.2를 유지하고 생성 grammar만 `claim-generation-0.3`으로 변경.
- 기존 12개 회귀: 계약 10/12, JSON 12/12, 잘림 0, 총37.42초/중앙값3.33초. v2와 JSON이 달라진 사례는 7/8뿐(반응·광고 뒤 주장 생성 차단). 인용 공백 변경과 농담 오해는 남음.
- seed408 새 표본 12개(기존 12개 제외): 계약11/12, JSON12/12, 잘림0, 총35.81초/중앙값2.43초. 독립 인간 gold나 별도 영상 평가가 아님.
- 새 표본 AI 의미 검수: 조건 반전(사례3), 일반 주장→개인 scope(6/8), 근거에 없는 설명 추가(9), 짧은 자유 제한 주장 누락(11). 계약 성공률을 정확도로 보고하지 않음.
- 로컬 보고서: `artifacts/local-claim-probe-qwen4b-20261010-v3.json` 및 `.html`, `artifacts/local-claim-probe-qwen4b-20261010-v3-unseen.json` 및 `.html`. 검수 초안: `artifacts/local-claim-probe-qwen4b-20261010-v3-unseen-review.json`(사용자 피드백 대기).
- README의 합성 연결 예제 실제 실행: 주장 추출3/3 계약 통과, 원문 clustering도 실행 확인. 합성 예제의 의미 품질을 검증한 것은 아님. 전체 오프라인 unittest 74개 통과.
- 공개 runner는 snapshot/output/model metadata 인자를 받음. `--replay-report`/`--exclude-report`로 private 보고서 ID를 재사용/제외하며 원본 hash 확인. 개인 corpus ID를 소스에서 제거. 최신 명령은 README 참고(과거 `--revision v2` 단독 명령은 이제 필수 인자가 필요).
- README는 모델 다운로드 출처/revision, loopback 서버, 합성 실행, 실제 snapshot 교체, 오류·품질 해석, 종료까지 안내. GGUF/safetensors와 models 폴더도 Git 제외.
- 다음: 사용자와 의미 검수 기준 확인 → 인용/조건/범위 추출 수정 → 새 표본으로 검증 → claim clustering 연결. 확정 PerspectiveSpec/agent는 여전히 0.

## claim-cluster 작은 연결 결과 (2026-10-11)

- 사용자가 작은 표본부터 claim→검수된 cluster로 연결하도록 진행 요청. 기존 1,000개 재사용; YouTube API 추가 호출 0회.
- V0 C005(반응13개)+C006(자동화12개)+C008(물가12개) = 목적 표집37개. 유망한 묶음과 실패 묶음을 골랐으므로 독립 평가/전체 분포 증거 아님.
- 프롬프트0.2, 생성 grammar0.3 유지. 로컬 추출37개 JSON 전부 파싱, contract28/37, 잘림0, 총125.63초/중앙값2.53초. 실패9개는 조용히 고치지 않고 후보 입력에서 차단.
- included28개 = argument_or_experience19 + non_substantive9. 주장25개 → 후보9개, unique sources>=3 후보3개. accepted0/agent0.
- `artifacts/claim-slice-20261011-extraction.json` 및 `.html`: 원시 추출. `...-candidates.json` 및 `.json.html`: 벡터/입력/후보/출처/실패. `...-review.json`: AI 검수 제안. 최신 사용자 화면 `artifacts/claim-slice-20261011-reviewed-v2.html`.
- CC001의 자동화 원문9개는 필요성/해결책5개(CC001-A)와 도입 예측4개(CC001-B)로 나누는 초안을 저장. 모든 claim을 중복/누락 없이 설명하는지 검사. 아직 적용된 split/사람 승인 아님.
- CC001-A 공통 설명 초안: '자동화·AI 확산에 대한 대응으로 UBI가 필요해지거나 해결책이 될 수 있다.' 필요성과 가능성 강도를 통일하지 않으며, modality/이유 필드 교정은 남음. 사용자 피드백 후 승인 여부 결정.
- CC001-B는 예측을 지지로 해석하거나 짧은 원문에 없는 job displacement 이유를 추가한 오류가 있어 보류. 물가 CC002/CC003도 질문/메커니즘/평가 혼합 때문에 보류. 희소 주장/추출 오류를 숨기지 않음.
- 코드 경계: `factory/claim_clusters.py` prepare/build/render. API/LLM 호출 없이 추출 결과를 재검증하고 후보 생성. 현재 최대60 selected sources/300claims. 모델 벡터/입력을 저장하나 CLI 자동 cache/resume은 미구현.
- 검증: 오프라인 unittest88개 통과. 합성 README 경로 실행 결과 selected3 중 duplicate_alias1/included2, claim1/candidate>=3은0으로 정상 표시. 검수 JSON의 hash/소속/분리 제안 전체 배정 검사 통과. HTML은 escape 처리와 근거 링크를 확인했으며 별도 브라우저 시각 검사는 하지 않음.
- 실행: `python -m commentscope.factory.claim_clusters data/ubi-research-20261010.json artifacts/claim-slice-20261011-extraction.json --output artifacts/NEW.json` (ML 환경, 신규 경로).
- 다음은 CC001-A/B 설명에 대한 사용자 피드백 → 추출 필드 교정 방식/승인 기록 구현 → 새 표본 검사. 전체1,000개 claim 추출·agent로 즉시 확대하지 않음.

## 로컬 대표 주장 생성 + 근거 검사 (2026-10-11)

- 사용자 요청: 후보를 대변하는 공통/상세 주장 생성 방법 설명 후 자동화 진행. Qwen4B Q4_K_M 유지, API 추가 수집/댓글 외부 전송 없음.
- candidate CC001/CC002/CC003을 입력. 기존 assistant의 5개/4개 분리 제안은 모델에 주지 않음. 이미 검토한 목적 표본이므로 독립 평가 아님.
- draft v1: 부분 인용 복사/배정 누락으로 0/3 계약 통과, 총58.56초. `artifacts/perspective-drafts-20261011.json` 및 `.json.html`. 실패 그대로 보존.
- draft v2: 고정 member assignment key, 원문 우선 입력, 호스트의 전체 원문 연결 방식으로 변경. 2/3 계약 통과, 총28.11초. `artifacts/perspective-drafts-20261011-v2.json` 및 `.json.html`. 원문 연결은 코드 보장이지 의미 정확도 아님.
- CC001은 8개를 'AI가 대부분의 일자리를 대체해 UBI가 필요하다'로 일반화하고 도입 예측도 혼합. CC002는 그룹 밖 detail 근거 인용으로 차단. CC003은 모두 unique source1인 rare 초안이며 details.text에 M01 같은 ID만 출력하는 오류.
- 별도 로컬 audit: CC001 14쌍(9.31초), CC003 8쌍(5.01초)을 검사; 둘 다 revise_before_human_approval. `artifacts/perspective-drafts-20261011-v2-audit.json` 및 `.json.html`.
- **검사도 정답 아님.** CC001 P07에서 could→필연성 과장을 supported로 놓침. P13/P14에서는 타당한 도입 예측을 '필요성/고용 근거 없음'으로 잘못 거절. CC003 P02에서 ID placeholder를 supported로 해석. 같은 모델의 문맥 간섭/오판을 보존.
- assistant 검수 초안: `artifacts/perspective-drafts-20261011-assistant-review.json`, 실제 출력 파일 hash 연결. 사람 승인/독립 gold가 아님.
- 새 코드: `perspective_prompt*.py`, `contracts/perspective_*.py`, `providers/local_llama.py`, `factory/perspective_drafts.py`, `factory/draft_audit.py`. README Section6 재현 명령 제공.
- 실행기 context8192/no-context-shift/parallel1, 최대출력3000. 실행 후 서버 종료. 후보별 checkpoint는 보존하되 자동 resume 없음.
- 오프라인 테스트108개 통과. 모델 검사 결과를 코드 테스트 성공률과 혼동하지 않음.
- 다음은 placeholder 차단 및 원문-문장 한 쌍씩 독립 검사하는 실험(아직 미구현), 예측/필요성 구분 개선. 1,000개 확장/agent 승격 전에 새 표본으로 검증. 프롬프트만으로 충분하다고 아직 결론낼 수 없음.

## 쌍별 근거 검사 + placeholder 차단 (2026-10-11, 최신)

- 바로 위의 다음 작업을 구현/실행 완료. 기존 1,000개/초안 재사용; YouTube 호출0, 댓글 외부 전송 없음. 모델/설정/SYSTEM 유지, 요청 경계를 한 문장–한 원문으로 변경. ID-only는 별도 규칙 차단.
- `artifacts/perspective-drafts-20261011-pairwise-audit.json` 및 `.json.html`: 이전 batch와 현재 판단을 나란히 확인. CC001 14회/12.07초, CC003 모델4회/3.31초 + ID-only4쌍 규칙 차단. 총22쌍, 모델18회, 오류/잘림0, 총15.38초. 둘 다 revise_before_human_approval.
- CC001 P02/P07/P08: 이전 supported→partial로 과장/빠진 근거를 탐지. P14: 이전 partial→supported로 타당한 예측 인정. P09/P11/P13은 여전히 타당한 문장을 partial로 거절. P01 판정도 supported→partial로 바뀌었고 이유에 원문과 모순되는 설명이 있어 검토 필요.
- 실행 전 `artifacts/pairwise-audit-20261011-regression-expectations.json`에 assistant 기대 판단을 기록했으며 모델에는 주지 않음. 알려진 실패 중심 모델8사례 중 기대 일치1→5, 별도 규칙4사례는4개 차단. 인간 gold/일반 정확도 아님. 결과 분석: `artifacts/pairwise-audit-20261011-assistant-review.json`.
- 새로운 의미 문제: P04 이유는 원문에 있는 80%+ 일자리 조건도 없다고 설명. P09/P11/P13은 문장에 없는 필요성/독점 인과 요구. 같은 모델의 추가 호출만으로 신뢰 가능한 승인 gate가 된 것은 아님.
- 코드: `draft_audit.py`의 `--mode pairwise`, `--compare-to`, origin/lint 및 쌍별 checkpoint. 비교는 draft hash/pair/이전 verdict 누락 검사. 실패 시 전체 audit_failed, 성공해도 human_approved=false. 자동 resume 없음.
- 초안/cluster 배정을 교정하거나 agent를 만들지는 않았음. 승인 PerspectiveSpec/agent0. 오프라인 테스트118개 통과. 서버는 실험 후 종료.
- 다음: 같은 쌍별 입력을 고정하고 audit prompt만 바꿔, 원문의 함의 검사와 사실/정책 필요성 판단이 혼동되지 않는지 실험. 이후 생성 초안의 예측/필요성 분리와 상세 문장 수정 → 사용자 피드백 → 새 표본 검증. 기존 결과를 덮어쓰거나 1,000개로 바로 확대하지 않음.

## 검사/생성 프롬프트 단독 비교 (2026-10-11, 최신)

- 사용자 요청에 따라 기존 원문/초안/모델/설정을 고정하고 audit prompt만 변경. `audit_prompt_v2.py`, `draft_audit --prompt-revision v2` 구현. 이전 prompt는 v1 기본값으로 유지.
- `artifacts/perspective-drafts-20261011-entailment-audit.json` 및 `.json.html`: 모델18회 + lint4쌍, 총16.99초. 비교 metadata 차이는 prompt hash뿐임을 확인. 사전 기대8사례 일치5→5; P11/P13 교정, P02/P08 회귀, P09 오판 지속. P04/P05 과장도 supported로 놓침. 일반 정확도/독립 gold가 아님.
- 생성 쪽은 `perspective_prompt_v3.py`, `perspective_drafts --revision v3`로 v2 입력/스키마/validator/binding을 고정하고 prompt만 변경. 동일 input/members/generation_schema/model/runtime/request_settings를 실제 artifact 대조로 확인. 기본값은 v2 유지.
- `artifacts/perspective-drafts-20261011-v3.json` 및 `.json.html`: 후보3개, 구조 통과2개, 총32.24초. CC001은 가능한 해결책1개를 분리했으나 나머지8개를 필요성/대부분 일자리 소멸로 과장. CC002는 non-X 배정에 exclusion_reason을 넣어 unexpected_exclusion_reason으로 차단. CC003은 ID-only가 사라졌지만 일부 원문에 없는 common에 잘못 배정하고 상세에 financial stability 이유를 추가.
- 후속 audit는 새 prompt를 채택하지 않고 v1/pairwise로 실행. `artifacts/perspective-drafts-20261011-v3-audit.json` 및 `.json.html`: CC00114쌍/14.89초, CC00310쌍/10.70초, 둘 다 revise. 실제 문제 일부를 잡지만 타당한 문장도 거절하므로 단독 승인 gate로 사용 금지.
- assistant 분석과 수정 제안: `artifacts/prompt-comparison-20261011-assistant-review.json`. 실제 파일 hash에 연결. CC001-A 필요성/해결책5개, B 도입 예측4개 제안은 아직 미적용/미승인. 최신 사용자용 `artifacts/perspective-feedback-20261011.html`은 원문9개·한국어 설명·검토 질문·실제 모델 결과 링크를 제공. 로컬 모델 성공 산출물과 구분.
- 사용자에게 A의 필요성과 가능성을 함께 묶고 강도 차이를 상세에 보존할지, 더 분리할지 피드백 요청. 답변이 오면 기록하되 아직 받지 않은 승인을 가정하지 말 것.
- 원문/결과는 Git 제외. YouTube 추가 호출0, 유료 API/댓글 외부 전송/추가 모델 다운로드 없음. 실험 서버 종료. 오프라인 테스트125개 통과.
- 다음: 사용자 피드백을 반영한 소표본 기준 고정 → 원문별 assertion type/modality/조건 확인과 그룹 공통 명제 생성을 분리하는 실험 설계/실행 → 새 표본 검증. 프롬프트만 계속 늘리거나 실패를 수동 수정해 로컬 모델 성공으로 보고하지 않음. 다른 로컬 모델 비교는 대안이며 아직 실행하지 않음.

## 범위 동결 / 실패 단계 진단 (2026-10-11, 최신)

- 사용자는 프로젝트가 clustering 문제로 산으로 가는 것을 우려. 새 기능/모델/서비스 없이 기존 CC001 원문9개에서만 진단. 기존 pipeline/후보 배정은 바꾸지 않음.
- `experiments/source_frame_probe.py` 추가. 기존 prepare/load_candidates 검증과 local provider 재사용. 9개 원문을 다시 embedding하고, 기존 claim 벡터와 같은 subset에서 비교. 원문/벡터/분류 raw/조건 인용/실패와 source별 checkpoint 보존.
- 실제 묶음: 원문은 임계값0.25/0.35/0.45에서5/3/1개, 기존 claim은3/1/1개. 모든 임계값에서 예측/필요성 혼합이 남음. 주제 후보 생성은 가능하지만 공통 주장 검증과 같지 않음. 이 수치를 정확도나 전체 corpus 결과로 보고하지 말 것.
- 새 요청은 TARGET 하나만 받고 assertion_type/certainty/reason_quote/condition_quote만 출력. 기존 claim/그룹/기대 판단은 입력하지 않음. 새 paraphrase 생성 없이 구조9/9, 총7.79초. 사전 assistant 기대 대비 type8/9, certainty6/9. 인간 gold/일반 정확도 아님.
- M06의 미래 필요성을 도입 예측으로 분류. M04/M07의 will과 M08의 could를 certainty=unclear로 처리. M06/M09의 시간 표현을 조건으로 뽑음. M02의 when-you-consider도 해석 주의. 문자열 일치만으로 의미 검증 완료가 아님.
- 기존 M04는 추출 단계부터 필요성/일자리 대체 이유를 추가. 원문을 읽는 대표 생성도 독립적으로 오류를 만들었으므로 단일 원인으로 단정하지 않음.
- 보고서 `artifacts/source-stage-20261011.json` 및 `.json.html`. 사전 기대 `...-expectations.json`, 결과 검수 `...-assistant-review.json`. 전부 비공개 로컬, 만료 상속. 기존9개 사용, 추가 수집/유료 API/외부 댓글 전송/모델 다운로드0.
- 전체 테스트135개 통과. 모델 서버 종료. agent0/승인0, 기존 생성/검사 기본값 유지. 새 label로 자동 분할하지 않았음.
- 다음 변경은 관점 승격 전 원문별 주장·표현 강도·이유/조건 확인에 집중. 기존 검토안에 대한 사용자 피드백은 아직 없으므로 가정하지 않음. 고정 사례의 의미 오류가 남아 있는 동안 다른 agent 기능/전체1,000개 처리로 확장하지 않음. 수정 후 별도의 새 표본 검증 필요.

## 원문 선택형 B 실행 (2026-10-11, 최신)

- 구현: `factory/extractive_keypoints.py`. 전체 원문을 대표 후보로 고정, 모델은 관계 enum만 선택, 코드는 직접 지원/최소3개/중복 없는 배정. 이전 assistant의 5개/4개 분할 제안을 정답으로 입력하거나 강제하지 않음.
- 기존 자동화9개, Qwen3-4B-Instruct-2507 Q4_K_M/revision a06e946bb6b655725eafa393f4a9745d460374c9, llama.cpp b11541/CUDA12.8/context8192. 72모델호출+9동일원문 record, 오류응답0, 호출시간 합16.77초(서버 로딩 제외).
- 결과 `artifacts/extractive-keypoints-20261011.json` SHA256 `0f7c5ae9e72abd2de1d9db09ba5dd36aba60a17e6d031001dcfeb934145bf174`. `.json.html`에서 원문/대표/미배정/관계행렬 확인. 입력/출력/검수 모두 Git 제외, 만료2026-11-08T18:30:59.664629Z 상속.
- EK001: 대표M04, 소속M01/M03/M04/M05. EK002: 대표M07, 소속M02/M06/M07. M08/M09 미배정. 배정7/9는 품질 점수가 아님.
- assistant 검수: M01→M04, M02→M07, M06→M07은 필요성에서 도입 예측으로 넘어가는 오연결. M03/M05→M04도 조건/범위가 지워질 위험이 있어 보류. 두 그룹 모두 수정 필요, 승인0. 모델 결과는 수정하지 않고 별도 review JSON에 기록.
- 실행 전 고정한 부정9사례 중8개에서 supports를 피했지만 M09→M01은 most-jobs 이유를 잘못 인정. 알려진 부정 회귀만의 수치이며 정확도/recall이나 독립 gold가 아님. 새 prompt/schema도 바뀌었으므로 B 단일요소 효과 주장 불가.
- 전체 테스트147개 통과(코드 계약 검증, 의미 정확도 아님). 로컬 서버 종료. YouTube 추가호출/유료 API/외부 댓글 전송/새 모델 다운로드0. 기존 pipeline 기본값 유지.
- 다음: `judge()`의 관계 판정만 교체·비교. 이 작은 실험은 일반 장문/다중 주장 clustering을 해결한 MVP가 아님. Jev 미사용; 지금 모델 변경이 반드시 해결한다는 근거도 없음.

## 로컬 NLI 비교 실행 (2026-10-11, 최신)

- `providers/local_nli.py`, `experiments/compare_local_nli.py`, 공개 합성20사례/테스트 추가. 실행법과 모델 revision은 [LOCAL_NLI_COMPARISON.md](LOCAL_NLI_COMPARISON.md). 모델 파일만 신규 다운로드했고 댓글 외부 전송/추가 YouTube 호출/유료 API는0.
- 실제9개 원문/대표/72쌍/배정 코드 고정. 사전 계획 `artifacts/local-nli-20261011-prerun.json`, 실행 전 hash manifest `.json.manifest.json`, 실제/합성 모든 출력과 checkpoint 보존. 비교 SHA256 `49fd8170792604b256f19b0e5478a8296afc2f38b6b0d2880a1a5155205bca94`.
- Qwen 실제 출력은 B의 기존 실행 재사용; 합성20개만 동일 서버 설정에서 새로 실행. NLI는 CPU float32/6threads/torch2.14.1+cpu/transformers4.57.1, revision6f5cf0a2b59cabb106aca4c287eed12e357e90eb, threshold0.8 고정. 실제72쌍7.53초, loading0.91초 별도. 일반 성능 benchmark 아님.
- 알려진 실제 부정12쌍 비지지: Qwen8, NLI12(3보류). 조건/범위2쌍은 Qwen0, NLI1. NLI M03→M04 supports 하나가 남아 의미 검수 필요. 실제그룹0, 배정0/미배정9. 원문을 잃은 것은 아니며 clustering 성공으로 보지 않음.
- 합성: 정상 연결7/8씩, 부정 기대 relation 일치 Qwen7/8·NLI6/8, 모순2/2·애매2/2씩. NLI는 조건 삭제를 supports(0.987)로 오판. 양쪽 모두 Most→Some 누락, Most→All을 contradicts로 분류. 마지막 사례의 문자적/일상적 해석 차이는 사용자 피드백 대상으로 보존.
- NLI 기본값 승격 안 함. 새로운 real holdout/인간 gold/실제 positive recall/다국어 검증 없음. 전체 원문 대표 방식이 coverage를 제한할 수 있다는 것은 미검증 가설이지 이번 비교로 확정된 원인 아님.
- 테스트159개 통과. 실제 댓글/결과/사전 계획/검수는 Git 제외 및 기존 만료 상속. 실행 후 Qwen 서버 종료. agent0/승인0.

## 원문 계열 + assistant 검수 루프 (2026-10-11, 최신)

- 사용자 요청: assistant가 먼저 판정하고 평가→수정 루프로 결과를 만들 것. 모델 내부 설명을 정확성 증명으로 취급하지 않고 원문/판정/코드 배정/검수 수정 경계를 나눔.
- 이전9개 한글 검수 제안 `artifacts/assistant-cluster-review-20261011.html`과 JSON. 필요성4/도입 예측4/가능한 해결책1. 원문 hash/정확한 source text/전체 partition 확인. 모델 산출물이나 사용자 승인으로 표시하지 않음.
- 새로운 `source_facets`는 topic/type/polarity/원문 구절을 선택하고 전체 원문 카드를 유지. 기존 전체 문장 entailment와 다른 계열 분류 문제임을 명시. 한 자동화–UBI 주제/영어 짧은 댓글/최대24개로 제한.
- `source-facet-loop-20261011-plan.json`에서 개발9개·확인12개 기대값과 자동 성공 기준 고정. 확인12개는 기존 probe/extraction58개 source 제외, 관련 regex/top-level/500자 이하18개에서 Random411로 선택. reviewer가 구현 전에 읽어 blind holdout 아님.
- v1/v2 개발 결과 모두8/9. M06 미래 필요성을 도입 예측으로 분류하는 오류가 남아 성공 기준9/9 실패. 두 프롬프트 후 반복 중단. `...-review-stage-plan.json`에 프로토콜 변경을 별도 기록한 뒤 v2 고정 확인12개를 진단 목적으로 한 번 실행. 계약10/12, 사전 기준5/12. 실패 기록을 변경하거나 테스트를 재튜닝하지 않음.
- `...-assistant-decisions.json`에서 assistant가21개 전수 검수. 모델 출력13개 확인/8개 수정: 의미 라벨6, 의미+인용1, 인용1. 수정 전 결과를 model_result로 보존하고 새 판단은 origin=assistant_review. 독립 평가가 아니므로 수정 후 정확도100%라는 보고 금지.
- 최신 결과 `artifacts/source-facet-loop-20261011-reviewed.json` SHA256 `8b737d3216c3470c0151e7c6b0290afb001ab40e58051d4e539a208417416cdc`, 화면 `.json.html`. 필요성7(M01/M02/M06/M09/H01/H05/H12), 예측4(M03/M04/M05/M07), 가능한 이점2(M08/H08), 나머지8 보류. 21개 모두 원문/출처/기존 모델 출력 일치와 중복·누락 없는 partition 검사 완료.
- 테스트175개 통과. 로컬 Qwen 서버 종료. 추가 YouTube/유료 API/외부 댓글 전송/모델 다운로드0. 실제 계획/출력/검수는 Git 제외, 기존 만료 상속. 코드/설계/실행법만 공개.
- 자동 clustering/논문용 독립 성능/MVP/agent가 완료된 것이 아님. 검수 지원 prototype의 작은 결과가 생긴 상태. 독립 평가/미사용 실제 표본/다국어/복합 주장 분해/agent 발화 검증은 남음.

## 개발용 관점 에이전트 연결 (2026-10-11, 최신)

- 사용자 정정: 논문 대상은 전체 프로젝트이며 clustering은 준비 모듈. Section16.4에서도 검수 입력으로 end-to-end 검증을 우선함. 기존21개를 재사용하고 추가 추출/군집 실험을 하지 않음.
- `agents/profiles.py`, `runtime.py`, `demo.py`: profile 생성·독립 세션·문장별 인용·별도 Auditor·최대1회 수정·보류·HTML 비교 구현. 개발 전용 --allow-unapproved 필요. build는 모델 호출0, ask는 기존 local Qwen만 호출.
- bundle `artifacts/development-agents-20261011.json`: A001 필요성7개, A002 도입 예측4개. 희소2/보류8은 agent로 만들지 않음. agent별 원문/검수 해석/주의점/부모 문맥 보존, peer 응답/state 공유 없음.
- 첫 실행 `...-comparison.json`: 첫 질문 A001은 빈 partial 답변으로2회 실패, A002는 답변. 보완 실행은 분기 grammar로 빈 답변 방지, 의견 전달과 정책 사실성 입증 구분, 출력 길이 제한 변경. prompt/schema/출력 한도가 함께 달라 단일 요소 효과 주장 금지.
- 최신 `artifacts/development-agents-20261011-comparison-v2.json` SHA256 `1bdebbae658896498d07925e990f49a6c3735174d400abdb6c8295af7e7cf7ed`. 질문3×agent2에서 첫 질문2답변 통과, 과장 전제 질문2건 수정 후 보류, 국가별 금액/연도/물가2건 근거 없음 보류. 출력 HTML은 `.json.html`.
- assistant 검수 `artifacts/development-agents-20261011-assistant-review.json`: 표시4문장을 원문 M01/M02/M03/M05와 대조해 근거/조건 보존 확인. 모든 표시 인용은 자기 agent의 정확한 source card, 거절 초안 최종 노출0. 독립 정답 평가는 아님.
- 과장 전제 질문의 Auditor는 질문 조건을 원문과 혼동하는 오류가 있음. 특히 M05의 조건이 있는 원문/답변을 조건 누락이라고 설명하며 거절. 보류를 모두 올바른 왜곡 탐지로 세지 않음. 현재 보수적 동작과 과잉 거절 한계를 함께 기록.
- 테스트195개 통과. 로컬 서버 종료. 댓글 추가 수집/외부 추론 API/새 모델 다운로드0. raw 초안·검사·checkpoint·비교 HTML은 Git 제외/기존 만료 상속. 승인 관점0, 개발 agent 실행2. 브라우저 채팅 입력/peer 토론/Reflection/전체 자동 MVP는 아직 미구현.

## V0 실험 결과 (2026-10-10 KST)

- 실행 환경: `/home/taeng/.venvs/commentscope-clustering/bin/python`. C: 공간 부족으로 기존 `.venv`와 분리했습니다.
- 로컬 모델: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision은 코드/결과에 고정. 댓글은 모델 API에 전송하지 않았습니다.
- 재현: 위 Python으로 `-m commentscope.cluster_baseline data/ubi-research-20261010.json --output artifacts/NEW-NAME.json`.
  최초 모델 다운로드 후 `HF_HUB_OFFLINE=1`로 실행 가능. output과 `.html`은 덮어쓰지 않습니다.
- 999 canonical comments → 1,145 token chunks → threshold 0.45에서 576 groups, 3개 이상 후보 75개(400 comments).
- threshold 0.35/0.45/0.55에서 group 수 788/576/334. 이는 민감도 검사이지 정확도 점수가 아닙니다.
- raw 결과: `artifacts/ubi-v0-20261010.json`, 최신 검수 화면: `artifacts/ubi-v0-reviewed-claims-20261010.html` (이전 화면보다 우선).
- 탐색 검수: `artifacts/ubi-v0-review-20261010.json`. 6개 사례의 source digest와 cluster/evidence 소속 확인. AI 보조 분석이며 독립적인 인간 평가가 아닙니다.
- 관찰: C006은 자동화에 따른 필요성이라는 유망한 공통 주장; C008은 물가 우려와 반론 혼합; C005는 맥락 의존 반응; C050은 복지 보존 조건이 묻힐 위험.
- C002는 노동 시간 증가/감소가 달라도 '원하는 일을 선택할 자유'라는 공통 주장으로 대표 가능성이 있습니다. 자동 split하지 말고 실제 PerspectiveSpec의 주장 범위와 근거를 검수합니다.
- 확정 PerspectiveSpec/agent 0. raw 묶음 크기나 cosine만으로 승격하지 않았습니다.
- 원문을 포함한 모든 결과는 Git 제외 경로에 보관하며 snapshot 만료 정책을 상속합니다.
