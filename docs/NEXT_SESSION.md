# 다음 세션 시작점

**기본소득 댓글 1,000개 확보 및 V0 로컬 의미 클러스터링 실행 완료. 주장 기반 V1/V2, 검증된 PerspectiveSpec 및 에이전트는 아직 미완료입니다.**

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

1. 현재 PR과 작업 트리를 확인하고 필요한 검토를 마칩니다.
2. 준비된 기본소득 표본을 사용합니다. 키 발급이나 영상 선정을 사용자에게 다시 요청하지 않습니다.
3. eligibility/claim 검수 표본을 만들고, 공통 주장·개별 이유/조건·희소 주장과 parent 맥락이 보존되는지 확인합니다. 반대편 존재를 성공 조건으로 삼지 않습니다.
4. downstream 사용 조건과 모델/예산을 정해 실제 표본을 claim 추출 → 후보 cluster → 근거 확인 화면으로 연결합니다.
5. 기능 내부의 계약과 실패 테스트를 구현하되, 팀원이 볼 수 있는 cluster 결과를 다음 확인 지점으로 삼습니다.

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
