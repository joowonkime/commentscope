# CommentScope 인수인계 — 먼저 읽기

기준일: 2026-11-18. 연결: TASK-029 / REQ-001·005·006·007·008·009·010 / DEC-028.
이 문서는 새 담당자가 현재 코드·검증 범위·실행 방법을 빠르게 찾기 위한 진입점이다.
구현 구조는 [현재 구현 구조](design/IMPLEMENTED_STRUCTURE.md), 다음 작업 정본은
[MVP 명세](MVP_SPEC.md)와 [추적표](mvp-traceability.json)다.

## 1. 세 문장으로 보는 현재 상태

등록한 YouTube 댓글 snapshot에서 관점 후보와 지지 출처를 찾아 검증하고 Agent bundle을 만드는
Factory와, 그 bundle로 비교·1:1·그룹 대화·원문 조회·성찰 저장을 수행하는 웹/API를 구현했다.
실제 모델로도 연결을 실행했지만, 구별되는 관점의 발굴과 질문에 맞는 설명·상호 대응 품질은 부족하다.
999는 과거 실험의 canonical 댓글 수이며, 현재 일반 실행기는 별도로 확인된 기본1000개 제한
전달 문제 때문에 3000개 지원이 끝까지 연결된 상태가 아니다.

| 질문 | 인수인계 시 사용할 표현 |
| --- | --- |
| Agent 생성까지만 만들었나? | 아니오. 비교·1:1·그룹·근거·성찰 API와 화면도 구현·제한 실행했다. |
| 그러면 유용한 토론이 완성됐나? | 아니오. 실제 그룹 reply가 입장 반복에 그치는 사례가 있고 품질 보완이 필요하다. |
| Agent가 별도 학습 모델인가? | 관점·허용 근거·조건·이력·runtime을 가진 대화 단위다. 관점마다 별도 모델을 학습한 것이 아니다. |
| 임의 영상 URL을 넣으면 동작하나? | 수집 CLI는 있지만 웹의 임의 URL 등록→분석 작업 API는 없다. 등록된 분석을 사용한다. |
| 3000개까지 검증됐나? | 일부 registry/search 합성 검사는 있다. 일반 prepare의1001개 거절과 제품 import의 기본1000 호출이 남아 있고 실제3000 실행은 없다. |
| 공개 배포됐나? | 아니다. 재기동 가능한 로컬 화면/실행 기록이 있으며 지속 배포 URL은 없다. |

## 2. 새 컴퓨터에서 비용 없이 실행

Python3.12 이상을 사용한다. 아래는 저장소 루트에서 실행한다.
프로젝트의 기본 의존성에는 로컬 LLM 가중치가 필요하지 않다.

```bash
python -m venv .venv
```

가상환경을 활성화한 뒤:

```bash
python -m pip install -e .
python -m experiments.mvp_browser_fixture runs/handoff-preview --seeded
```

`runs/handoff-preview`는 없는 새 경로여야 한다. 이미 사용했다면 다른 이름을 쓴다.
명령이 출력한 `origin` 뒤에 `/mvp`를 붙여 브라우저로 연다. 종료는 `Ctrl+C`다.
Windows PowerShell의 활성화 명령은 `.venv\Scripts\Activate.ps1`,
Linux/macOS는 `source .venv/bin/activate`다. 활성화가 어렵다면 해당 환경의 Python 실행 파일을
직접 사용해도 된다.

**이 preview의 댓글·Agent·생성/판정 응답은 모두 합성이다. API 키·GPU·유료 호출은 없다.**
실제 댓글 분석의 품질이나 실제 모델 성능을 이 화면으로 증명하지 않는다.

1. 초기 의견에 `Safety reviews should be required.`를 적고 시작한다.
2. 관점 카드의 비교 버튼으로 내 의견·근거 연결을 확인한다.
3. 관점 하나 또는 둘을 선택해1:1/그룹을 열고 질문·원문·중단/재개를 확인한다.
4. Reflect에서 현재 의견을 적고 분석 또는 직접 작성 후 저장한다.
5. 새로고침하고 저장본과 대화를 다시 읽는다.

추가 무료 검사:

```bash
python tools/check_mvp_spec.py --resume
python docs/examples/check_snapshot_capacity.py
python -m unittest discover -s tests -p test_mvp_spec.py
```

용량 검사는 합성1000/1001/3000개와 실제 `prepare` 진입점을 검사한다.
provider preflight를 호출하면 실패하도록 막았으며 모델·비용 장부를 사용하지 않는다.
`prepared_video_prepare.accepted=false`는 현재 결함을 재현한 정상적인 진단 결과다.

## 3. 실제로 실행해 본 범위

상세 증거: [선정 영상의 실제 웹 검증](design/PREPARED_VIDEO_WEB_RESULT.md).

| 항목 | 2026-11-13 실행 기록 |
| --- | --- |
| 입력 | 고정180댓글,원댓글100/답글80 |
| 산출 |2개 profile,각 검증출처1개,승인된 원문 이유0개 |
| 성격 | 사용자 책임과 탐지기 신뢰라는 다른 관심사;교육 AI 허용/제한의 대조 관점은 아님 |
| 실제 대화 |1:1 질문8건,2인 그룹4턴 |
| 비교 | 기본 의견 비교2건은 빈 결과;별도 관련 의견에서 차이1건·원문 연결 |
| 유용성 | 새 논거1/2,준비 연구 설명0/2,없는 IQ 보장에 대한 한계 설명2/2 |
| 저장 | 성찰 분석·직접 수정·revision2 저장/재열람 |
| 비용 | Factory870요청/$3.20174896 +제품28요청/$0.182022526 |
| 코드 검사 | 실행 코드의 Factory960개;PR111 양OS 각2769개 통과,Windows의 기존 POSIX12개 skip |

이 수치는 독립 human gold·모델 정확도·대표 여론·3000개 원가·TA 사용성 평가가 아니다.
과거999개 실험과 새180개 실험의 입력·정책·실행 결과를 섞지 않는다.
현재 코드 인계의 기반은 main `ab6a34d`(PR111)이며, 위 실제 모델 실행 소스는 `b7738275`다.
이번 인계 추가는 문서/무료 진단이며 실행 알고리즘 변경이 아니다.

## 4. 넘겨야 할 것과 따로 관리할 것

**공유용 기본 묶음:** 현재 커밋의 tracked 코드·테스트·합성 fixture·이 문서·구조도·명세.
전달 ZIP은 이 항목만 포함한다. `.git`,실제 댓글,키,사용자 의견/대화,세션 token,DB,장부,모델 파일은
들어 있지 않다. ZIP만 받은 환경도 위 합성 preview로 기능 흐름을 확인할 수 있다.

실제 자료를 다시 검토하려면 원 담당자가 다음 자료를 **별도 비공개 경로**에서 제공해야 한다.

| 자료 | 필요한 이유 |
| --- | --- |
| 원 snapshot·parent·수집/사용기한 | 원문·문맥·중복/canonical 출처 대조 |
| Factory `plan/frozen/completed`와 해당 전체 artifact | 자동 산출물·입력/실행 hash·보류/실패 원본 확인 |
| `artifacts/agent-inputs.json`과`output.json` | Compiler 결과와 제품 analysis 등록 |
| 준비 문헌·정확한 발췌·기한 | 외부 근거의 실제 허용 범위 확인 |
| 정산/실행 owner·정책·장부의 관리 권한 | 기존 지출을 유지한 유료 실행 통제 |

실행 계획은 원래 절대 경로·소스 hash·입력·기한에 결합돼 있다. 다른 PC로 폴더를 복사하고
원 `plan.json`의 경로/기한을 고쳐 재개하는 절차를 안내하지 않는다. 완전한 portable import는
아직 구현하지 않았다. 새 환경에서 실제 자료를 실행하려면 무결성 확인·새 런타임 등록과
기존 금융 이력을 보존한 실행 설정을 따로 준비한다. 장부를 여러 사본으로 나눠 같은 팀 잔액을
독립적으로 쓰게 하지 않는다.

실제 서버 실행 계약은 [제품 API](PRODUCT_API.md)와
[최신 모드 연결](design/SEEDED_WEB_INTEGRATION.md)을 확인한다.
2026-11-13 trial의 새 AI 실행 권한은2026-11-14에 종료됐다.
남은 API credit,모델 실행 기한,사용자 인증 세션 기한,출처 사용기한은 서로 다른 조건이다.
인계나 서버 재시작으로 어느 것을 초기화하지 않는다.

## 5. 다음 담당자의 작업 구분

| 작업 | 현재 코드/근거 | 다음 완료 확인 |
| --- | --- | --- |
| 관점·논거 품질 | TASK-027,`source_evidence_adapter.py`,`seeded_runtime.py` | 원문/후보 보류 범위 분리;설명 제거 후 최종 답변의 질문 충족;구별되는 관점 |
| 용량 연결 | `prepared_video_trial.py`,`framed_corpus.py`,`product/analysis.py` | 기본1000 호출을 전 경로에서 대조하고2000/3000 합성 prepare→compile→제품 등록을 검증;실제 비용은 별도 |
| 홈·영상·개인 기록 | 현재 자동 첫 분석 선택/단일 세션 복원;11/17의 설계 제안 | 지원 영상 목록/URL 처리·실제 요청 상태·개인 기록 복원. 아직 구현하지 않은 제안임 |
| 제출용 운영 | `serve_mvp.py`,`product/web.py`,`product/store.py` | 외부 접속·채점 기간 유지·새 AI 호출 가능·기한 이후 기록 조회·세션/예산 유지 |
| 사용성 QA | `MVP_USER_CHECK.md`,TA의 시나리오 밖 사용 안내 | 초행 사용자의 세 과업·다른 질문·reload/뒤로가기/중복/실패를 점검 |

품질 작업의 첫 단계는 저장 응답의 무료 대조다. 한 실패를 고치기 위해 같은 유료 생성을 반복하지 않는다.
Agent merge/합의 후 새 Agent 생성,임의 영상의 즉시 분석,전체3000의 품질·원가 합격은 현재 기능이 아니다.
현재 소스에서 새 작업은 `AGENTS.md`→명세→resume→담당 TASK/design refs 순서로 시작한다.

## 6. 원 담당자 로컬 환경 주의

원 담당자는 미커밋 변경이 있는 기존 desktop checkout을 보존하고 별도 worktree에서 개발했다.
새 담당자는 저장소 main의 새 checkout 또는 전달 ZIP에서 시작한다.
원 담당자의 로컬 경로·키·`runs/`가 새 환경에 있다고 가정하지 않는다.
일시적인 `localhost` 서버와 영구적인 제출 URL도 구별한다.
