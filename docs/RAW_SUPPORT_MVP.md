# 원문 쌍에서 공통 주장과 지지 수 만들기

원문 검색 다음 단계의 실험 경로다. `raw_support`가 공통 주장 제안, 원문별 판정, 지지 수 집계를 분리한다.
기존 Factory0.2/main과 모델 가중치·NLI threshold0.8은 유지하며 아직 agent를 승인하지 않는다.

## 단계별 책임

1. 저장된64개 원문의64쌍 대기 목록을 그대로 읽는다. 후보의 유사도나 개발 평가 정답을 모델에 전달하지 않는다.
2. 한 쌍의 전체 원문에서 공통 주장 하나를 제안한다. 제안이 없거나 의미 검사에서 실패하면 다른 문장을 반복 생성하지 않는다.
   구조 오류만 기존 정책에 따라 한 번 수리할 수 있다. 성공할 때까지 프롬프트를 바꾸지 않는다.
3. 원문 하나와 고정된 주장만 NLI에 전달한다. supports를 통과해야 별도 Qwen 관계 검사를 한다.
   상대 댓글·다른 판정·cluster 크기는 이 검사에 들어가지 않으며 anchor도 자동 득표하지 않는다.
4. Qwen은 원문 전체와 주장의 범위/시점/양태/조건/극성/전제 보존을 확인하고 정확한 원문 인용을 반환한다.
   인용 복사와 enum을 코드로 검증한다. 보조적인 영어 조건/시점 검사는 이 인용과 주장을 비교한다.
   다른 문장의 무관한 조건을 전부 공통 주장에 강제하지 않도록 기존 full-source lexical guard와 적용 위치를 구분한다.
5. 같은 주장을 지지한다고 판정된 canonical source만 집계한다. 정확히 같은 주장 문자열만 병합하며,
   동의어 주장 통합과 중복 agent 방지는 아직 하지 않는다. 쌍 사이의 연결을 따라 membership을 전파하지 않는다.

프롬프트/schema는 cache 전에 system에도 명시한다. 기존 관계 감사와 NLI 가중치는 재사용한다.
변경은 raw 입력, 단계 순서, schema 노출, lexical guard의 적용 구간, NLI 길이 계약을 포함하므로 단일 요소 성능 개선으로 주장하지 않는다.

## 긴 원문과 실패 상태

기존 NLI provider의500자 제한은 그대로 두고 별도 `raw_nli.score_full` adapter를 추가한다.
동일 고정 모델로 원문 최대4,000자와 주장249자를 받고, pair token이512/모델 한도를 넘으면 잘라 추론하지 않는다.
전체 원문을 그대로 보관하고 `unchecked`로 보류한다. 토큰 한도 안의 긴 원문은 판정할 수 있다.
영어 NLI 범위이며 다국어 의미 품질은 검증하지 않는다.

각 고정 주장마다 `support / not_supported / uncertain / error / unchecked`를 저장한다.
인용/응답 오류는 `error`, 한도 초과/미예약은 `unchecked`다. 불확실이나 오류를 올바른 부정 판정으로 세지 않는다.
댓글이 여러 쌍에 등장해도 한 주장에서는 한 번만 세고, 중복 판정 입력은 ledger가 거부한다.
주장 hash·원문 hash·source ID를 묶으며 support에는 NLI/관계 검사/인용/조건 검사 기록이 필요하다.
모델의 구조적으로 유효한 오판까지 코드가 제거한다는 의미는 아니다.

이번 분모 N은 선택된64 canonical 댓글이다. 원본999개나 모든 영상 댓글로 확대 해석하지 않는다.
S는 판정 통과 댓글 수이지 실제 지지의 보장된 하한/사람 수/사실 검증 결과가 아니다.
`completed_count`는 확정 모델 판정인 support+not_supported만 세며 uncertain/error/unchecked는 별도로 표시한다.
주요 후보 `max(10,ceil(5%*N))`, 제한적3개 이상, 희소1~2개의 잠정 표시안을 적용하지만 agent 승격은 하지 않는다.

## 사전 고정 평가 계획

- 기존 OpenJev 비교의 직접 지지 회귀37개: 합성24개·실제13개, 기존 라벨을 수정하지 않는다.
- 기존 공통 주장 transfer12쌍: 정상6·비호환6. 원래 left/right 원문을 사용하며 만들어진 claim은 주입하지 않는다.
- 실제 raw64쌍: 전부 동일 알고리즘으로 처리한다. 과거 정상3쌍은 결과 조회에만 사용한다.
- 회귀의 오승인/오류/미검사가0일 때만 첫 두 exact-unique 통과 주장을 선택64댓글 전체에 확장한다.
  이는 실험 확장 중단 장치이며 runtime에 사람의 승인 파일이 필요하다는 뜻은 아니다.
  양성 보존율은 별도로 공개한다. 오류가 있으면 pair-level 결과만 남기고 확장/agent 생성은 하지 않는다.
- 이전 개발군과 같은 corpus를 사용하므로 독립 gold/새 영상/미사용 표본 검증이 아니다.
  모든 실제 통과 주장을 assistant가 원문과 대조하고 자동 판정을 덮어쓰지 않는 별도 평가를 저장한다.
- 실제64쌍 진단은 회귀 실패 시에도 원인 확인을 위해 완료한다. 전체1,000개/모델 교체/threshold 탐색은 하지 않는다.
  구조 수리 포함 새 LLM checkpoint 총900개 상한, pair 제안64개·검사128개 및 회귀·최대2×64 확장을 넘기지 않는다.

## 재현

기존 clustering ML 환경과 localhost8091의 Qwen3-4B-Instruct-2507 Q4_K_M 서버를 사용한다.
README의8192 context/no-context-shift/GPU 설정을 유지하고 실제 CUDA loading을 확인한다.
원문/출력/모델 파일은 Git 제외다. 먼저 코드를 커밋하고 plan을 생성한다.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.raw_support_probe \
  --run-dir runs/NEW-SUPPORT --phase plan --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.raw_support_probe \
  --run-dir runs/NEW-SUPPORT --phase run --diagnostic-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m experiments.raw_support_probe \
  --run-dir runs/NEW-SUPPORT --phase verify --diagnostic-only
```

이 개발 runner는 기존 private raw run과 고정 회귀 자료가 필요하다. 공개 저장소만 받은 사용자는 단위 테스트부터 실행할 수 있다.
일반 영상 입력용 CLI/UI는 아직 연결 전이며 팀원이 바로 전체 서비스를 실행할 수 있다는 안내가 아니다.
`plan.json`, `llm/`, `nli/`, `report.json`, `measurements.json`, `overview.html`을 보존한다.
verify는 checkpoint만 읽어 결과를 재구성하고 새 모델 호출을 금지한다.
원본 snapshot 만료를 상속하고 입력/코드/model revision을 고정한다. 시간에는 회귀 검사와 모델 loading이 포함돼 서비스 latency로 보고하지 않는다.
