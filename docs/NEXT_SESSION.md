# 다음 세션 시작점

**최신: B의 입력/대표/배정 고정 후 로컬 DeBERTa NLI 비교 완료. 기존 필요성→도입 오연결3건은 막았지만 조건 삭제 오판/정상 연결 누락이 남고 실제3개 이상 그룹0개. 기본 Qwen 판정기 변경/승격하지 않음. 결과 `artifacts/local-nli-comparison-20261011.json.html`, 검수 `artifacts/local-nli-comparison-20261011-assistant-review.json`. 승인 PerspectiveSpec/agent는0. 다음은 사용자 의미 기준 피드백과 실제 긍정 pair 검수; 모델/프롬프트 반복이나 전체 corpus 확장부터 하지 말 것.**

## 사용자 결정과 작업 단위

- 공식 YouTube Data API를 사용합니다. 실제 키 발급·YouTube 전용 제한·인증 확인 완료. 키 값은 저장소/채팅에 남기지 않습니다.
- 첫 후보는 Kurzgesagt 기본소득 영상 `kl39KHS07Xc`. `data/ubi-research-20261010.json`에 최상위 567 + 답글 433개를 저장했습니다.
- 최신 사용자 정정: 일차 목적은 **유의미한 주장을 가진 댓글 클러스터를 충실히 대변하는 agent**입니다. Debate/forum은 후속 활용이지 클러스터 선정의 목적함수가 아닙니다. 대립·찬반 균형·토론 재미를 강제하지 않습니다.
- 팀원들은 비개발자입니다. 다음 목표는 댓글을 입력하면 cluster와 근거를 검토할 수 있는 MVP입니다.
- 내부 구현은 순서대로 하되, 인터페이스/계약만 구현한 상태를 사용자 MVP 완료로 보고하지 않습니다.
- 로컬 모델 우선으로 검증합니다. 모델의 최종 품질 승인과 실제 corpus의 분석·외부 전송 사용 조건은 미결정입니다.

## Git 상태

- 저장소: https://github.com/joowonkime/commentscope (public)
- 수집 브랜치: `feat/youtube-collection`; 로컬 모델/검증 문서는 이를 기반으로 한 `feat/local-model-validation`에서 관리합니다.
- 소표본 claim 연결: `feat/claim-cluster-slice` (`feat/local-model-validation` 기반). PR #7의 Linux/Windows CI 성공 확인 후 분기; main 병합은 아직 하지 않음.
- 로컬 대표 초안/검사: `feat/local-perspective-drafts` (`feat/claim-cluster-slice` 기반). 이전 PR을 임의 병합하지 않음.
- 쌍별 근거 검사: `feat/pairwise-source-audit` (`feat/local-perspective-drafts` 기반). PR #9의 Ubuntu/Windows CI 성공 확인 후 분기. main 병합은 하지 않음.
- 프롬프트 단독 비교: `feat/entailment-audit-prompt` (`feat/pairwise-source-audit` 기반). PR #10 Ubuntu/Windows CI 통과 상태에서 진행. 상위 브랜치 임의 병합 없음.
- 실패 단계 진단: `feat/source-stage-diagnostic` (`feat/entailment-audit-prompt` 기반). PR #11 Ubuntu/Windows CI 통과 이후 진행. 상위 브랜치 임의 병합 없음.
- 원문 선택형 B: `feat/extractive-keypoint-baseline` (`feat/source-stage-diagnostic` 기반). PR #12 CI 통과 이후 진행. 상위 브랜치/main 임의 병합 없음.
- 로컬 NLI 비교: `feat/local-nli-comparison` (`feat/extractive-keypoint-baseline` 기반). PR #13 Ubuntu/Windows CI 통과 확인 후 진행. 상위/main 임의 병합 없음.
- Issue: https://github.com/joowonkime/commentscope/issues/5
- 설계 PR #2와 ingestion PR #4는 main에 반영했습니다.
- 수집 PR의 CI·검토·병합 상태는 다음 작업 전에 확인합니다.

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

## 구현과 확인 범위

- 기존 snapshot validation/normalization과 원자적 저장.
- 공식 videos/commentThreads/comments GET, 키 header 전달, redirect 차단, 제한된 retry.
- relevance/time 표집, ID 중복 관측 기록, 답글 round-robin pagination.
- source/호출/스레드별 답글 상한, partial 표시, provenance와 보관 만료 metadata.
- 기존 29개 + 수집 24개 = 53개 unittest 메서드. 로컬 오프라인 검사 통과.
- CI도 실제 API 키 없이 fake HTTP 응답을 사용합니다. 최신 결과는 PR Checks를 확인합니다.

공개 API의 `textDisplay`를 plainText로 보존하며 작성자의 raw `textOriginal`을 확보했다고 주장하지 않습니다.
`usage.expires_at`은 최대 30일의 metadata일 뿐, 자동 삭제/갱신 또는 만료 사용 차단은 아직 없습니다.
실제 키·영상 응답과 100/1,000개 표본의 validation/normalization은 검증했습니다. 분석 성능은 아직 검증하지 않았습니다.
수집 설정·만료·후보 비교·표본 한계는 [수집 기록](YOUTUBE_COLLECTION.md#첫-live-후보-기본소득-토론-2026-10-10-kst)을 확인합니다.

## 이어서 할 일

1. 현재 PR과 작업 트리를 확인합니다. 기존 기본소득 표본을 재사용하며 키/영상 선택을 다시 요청하지 않습니다.
2. B의 결과와 아래 최신 검수 기록부터 확인합니다. 원문 대표를 복사해도 잘못 연결하면 왜곡이라는 점이 핵심입니다.
3. 관계 판정기 비교는 아래 최신 실행까지 완료했습니다. 결과/합성 평가표/assistant 검수에서 사용자 피드백을 받고 실제 긍정 pair를 추가 검수합니다. 부정 사례만의 통과율이나 합성 점수를 일반 정확도로 보고하지 않습니다. 다음 모델/threshold 튜닝을 자동으로 반복하지 않습니다.
4. 고정 개발 오류를 해결한 뒤 미사용 소표본에서 재확인합니다. 성공 전에는 1,000개 확장/agent 기능을 붙이지 않습니다. 다른 로컬 판정기 검토는 가능하지만 아직 구현/검증되지 않았고, 외부 API 비교에는 데이터 전송/비용 조건 결정이 필요합니다.

[구조](ARCHITECTURE.md), [데이터 계약](DATA_CONTRACTS.md), [검증 목록](ACCEPTANCE_TESTS.md)을 기준으로 진행합니다.

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
