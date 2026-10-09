# 다음 세션 시작점

**공식 YouTube API 수집 CLI까지 구현했습니다. 실제 댓글 수집과 clustering MVP는 아직 미완료입니다.**

## 사용자 결정과 작업 단위

- 공식 YouTube Data API를 사용합니다. 실제 영상과 API 키는 아직 준비되지 않았습니다.
- 팀원들은 비개발자입니다. 다음 목표는 댓글을 입력하면 cluster와 근거를 검토할 수 있는 MVP입니다.
- 내부 구현은 순서대로 하되, 인터페이스/계약만 구현한 상태를 사용자 MVP 완료로 보고하지 않습니다.
- LLM provider/모델/예산, 실제 corpus의 분석·외부 전송 사용 조건은 미결정입니다.

## Git 상태

- 저장소: https://github.com/joowonkime/commentscope (public)
- 작업 브랜치: `feat/youtube-collection`
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

`VIDEO_ID`를 실제 영상으로 바꾸고 숨김 프롬프트에 키를 입력합니다. 이 명령은 실제 API 호출을 수행하며 아직 실행하지 않았습니다.
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
실제 키의 접근 가능 여부, 실제 영상의 응답, 분석 성능은 검증하지 않았습니다.

## 이어서 할 일

1. 현재 PR과 작업 트리를 확인하고 필요한 검토를 마칩니다.
2. 사용자에게 영상 URL과 API 키 준비 방법을 안내합니다. 키는 채팅/저장소에 받지 않습니다.
3. 키와 영상이 준비되면 소량 live smoke test로 요청·원문·parent·partial 상태를 확인합니다.
4. downstream 사용 조건과 모델/예산을 정해 실제 표본을 claim 추출 → 후보 cluster → 근거 확인 화면으로 연결합니다.
5. 기능 내부의 계약과 실패 테스트를 구현하되, 팀원이 볼 수 있는 cluster 결과를 다음 확인 지점으로 삼습니다.

[구조](ARCHITECTURE.md), [데이터 계약](DATA_CONTRACTS.md), [검증 목록](ACCEPTANCE_TESTS.md)을 기준으로 진행합니다.
