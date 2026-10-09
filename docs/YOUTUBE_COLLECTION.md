# 공식 YouTube API로 첫 댓글 표본 만들기

상태: 수집 CLI와 오프라인 테스트 구현 완료. 실제 API 키를 사용한 live 수집은 아직 검증하지 않았습니다.
이 경로는 개발자가 선택한 영상 1개의 연구 표본을 만드는 도구입니다. 공개 웹 서비스의 임의 URL 수집 기능은 아닙니다.

## 1. API 키 준비

1. [Google Cloud Console](https://console.cloud.google.com/)에 본인 Google 계정으로 로그인합니다.
2. 프로젝트를 만들거나 기존 프로젝트를 선택합니다. 예: `CommentScope`.
3. API 라이브러리에서 **YouTube Data API v3**를 찾아 사용 설정합니다.
4. 사용자 인증 정보에서 **사용자 인증 정보 만들기 → API 키**를 선택합니다.
5. 키의 API 제한을 **YouTube Data API v3**로 설정합니다. 이 CLI에는 공개 댓글 조회용 키가 필요합니다.

공식 안내: [시작하기](https://developers.google.com/youtube/v3/getting-started),
[키 만들기와 제한](https://developers.google.com/youtube/registering_an_application).
이 키는 YouTube 댓글 수집용이며 LLM 모델 API 키와 별개입니다. 키를 채팅·GitHub·보고서에 붙이지 않습니다.

## 2. 처음에는 소량으로 실행

프로젝트를 설치한 터미널에서 영상 URL을 바꿔 실행합니다. 키는 실행 후 숨김 입력으로 넣습니다.

```bash
python -m commentscope collect-youtube "https://www.youtube.com/watch?v=VIDEO_ID" --prompt-key --max-comments 100 --top-level-limit 40 --replies-per-thread 20 --max-requests 30 --output data/first-video-smoke.json
```

현재 WSL에서는 위 `python`을 `.venv/bin/python`으로 바꿉니다.
Windows에서는 `.venv\Scripts\python.exe`를 사용할 수 있습니다. 설치 안내는 [README](../README.md)를 따릅니다.
자동 실행 환경에서는 `--prompt-key` 없이 `YOUTUBE_API_KEY` 환경변수를 읽습니다. `.env` 파일을 자동으로 읽지는 않습니다.
API 키를 명령행 인자로 전달하는 옵션은 없습니다.

성공하면 수집한 원문·답글 수, 부분 수집된 스레드 수, API 호출 수, 중단 이유와 만료 시점이 표시됩니다.
댓글이 적거나 두 정렬이 겹치면 100개보다 적을 수 있습니다. 100은 **최상위 댓글과 답글을 합한 상한**입니다.

```bash
python -m commentscope validate data/first-video-smoke.json
python -m commentscope normalize data/first-video-smoke.json --output artifacts/first-video-normalized.json
```

기존 파일은 덮어쓰지 않습니다. 재수집할 때 새 파일명을 사용합니다.
실제 데이터는 Git에서 제외된 `data/`, 파생 결과는 `artifacts/`에 저장합니다.

## 3. 약 1,000개 목표로 확장

첫 조회가 확인되면 같은 방식으로 상한을 늘립니다.

```bash
python -m commentscope collect-youtube "https://www.youtube.com/watch?v=VIDEO_ID" --prompt-key --max-comments 1000 --top-level-limit 400 --replies-per-thread 100 --max-requests 100 --output data/first-video-research.json
```

필요하면 `--primary-language ko`로 표본의 주언어 설명을 지정합니다. 개별 댓글의 언어를 한국어로 강제 분류하지 않습니다.
`--usage-basis`에는 실제 확인한 사용 근거를 기록할 수 있습니다. 기본값은 연구 분석 사용 조건이 아직 검토 중임을 표시합니다.

## 수집 규칙

- `videos.list`로 영상 ID와 제목을 확인합니다. unavailable 영상은 명시적 오류로 반환합니다.
- 최상위 댓글 예산을 relevance/time에 나누어 조회합니다. 400이면 각 정렬의 **반환 항목** 최대 200개씩입니다.
- 두 정렬에서 같은 comment ID가 나타나면 한 번 저장하고 양쪽 정렬·순위를 모두 남깁니다. 중복 때문에 부족한 수를 임의 backfill하지 않습니다.
- 두 정렬의 결과를 교대로 배치하고, 선택된 parent에 대해 `comments.list`로 답글을 조회합니다.
- 답글은 스레드마다 한 번에 최대 20개씩 돌아가며 가져옵니다. 전체 상한·스레드별 상한·호출 상한 중 하나에 도달하면 멈춥니다.
- API key는 HTTPS header로만 전달하고 raw 응답이나 사용자명/프로필은 저장하지 않습니다.
- 재시도는 일시적인 서버/네트워크 오류에만 최대 2회, 1초·2초 간격입니다. 재시도도 호출 예산에 포함합니다.
- quota 소진·댓글 비활성화·잘못된 키 등 실제 API 오류는 실패로 종료합니다. 이 경우 최종 snapshot을 만들지 않습니다.
- 설정한 호출 예산에 도달한 경우에는 지금까지의 표본을 저장하고 `request_budget`과 partial 상태를 기록합니다.

quota의 1 unit과 실제 댓글 1개는 다른 단위입니다. 현재 사용한 세 list 메서드는 각각 요청당 1 unit입니다.
실제 요청/파라미터는 [commentThreads.list](https://developers.google.com/youtube/v3/docs/commentThreads/list),
[comments.list](https://developers.google.com/youtube/v3/docs/comments/list),
[videos.list](https://developers.google.com/youtube/v3/docs/videos/list)를 따릅니다.
키 header 사용은 [Google 공식 안내](https://docs.cloud.google.com/docs/authentication/api-keys-use)를 따릅니다.

## 원문과 완전성의 의미

공개 조회는 `textFormat=plainText`의 `snippet.textDisplay`를 그대로 보존합니다. HTML unescape나 번역을 추가하지 않습니다.
YouTube는 표시용 plain text가 작성 당시 원문과 다를 수 있다고 명시합니다. `textOriginal`은 일반 공개 조회에서 보장되지 않습니다.
따라서 현재 `text_original`은 **API에서 관측한 수정하지 않은 표시 텍스트**이며, 작성자의 원시 입력을 확보했다는 뜻이 아닙니다.
이 구분은 snapshot의 `sampling.description.text_source`에도 기록합니다.
[공식 comment 필드 설명](https://developers.google.com/youtube/v3/docs/comments#snippet.textDisplay).

`sampling.description`은 기존 schema 0.1의 문자열 필드를 유지하면서 JSON으로 인코딩한 수집 보고서입니다.
config, collector version, 호출 수, 정렬별 항목 수, stop_reasons, target_reached와 text_source를 포함합니다.
프로그램에서 세부 항목을 읽으려면 이 문자열을 JSON decode합니다.

parent의 reply 목록을 끝까지 읽었고 초기 `totalReplyCount` 이상을 확보한 경우에만 `complete`로 표시합니다.
초기 reply count가 0인 경우에는 그 관측 시점에 대해 complete입니다. 나머지는 partial입니다.
reply 자체의 `replies_status`는 unknown으로 둡니다. thread ID 대신 **실제 최상위 comment ID**를 parent로 사용합니다.
여러 API 요청 사이에 댓글이 수정/삭제될 수 있어 시점 전체가 원자적으로 고정되지는 않습니다. 중복 관측 시 처음 받은 텍스트를 유지합니다.
정렬 기반 표본은 전체 여론의 대표 표본이 아닙니다.

## 보관과 아직 확인할 것

수집 시작 시점 기준 최대 30일의 `usage.expires_at`를 저장합니다. `--retention-days`로 1–30일을 선택할 수 있습니다.
**이 값은 메타데이터입니다. 자동 갱신·자동 삭제·만료 데이터의 후속 사용 차단은 아직 구현하지 않았습니다.**
만료 시 원본뿐 아니라 해당 데이터를 담은 정규화 결과·사본도 함께 관리해야 합니다.

공식 API를 선택한 것은 접근 경로의 결정입니다. clustering, 외부 모델 전송, 사용자 테스트에서의 원문 표시 등
다운스트림 사용 조건은 별도 확인 사항으로 남아 있습니다. API 키나 이 CLI가 그 사용을 승인하는 것은 아닙니다.
[개발자 정책 III.E](https://developers.google.com/youtube/terms/developer-policies#e.-handling-youtube-data-and-content).

## 오류 해결

| 코드 | 다음 행동 |
| --- | --- |
| `MISSING_API_KEY` | `--prompt-key`를 쓰거나 환경변수를 설정 |
| `YOUTUBE_AUTH_ERROR` | API 활성화와 키/API 제한 설정 확인 |
| `YOUTUBE_REQUEST_REJECTED` | 키·접근 제한·요청 조건 확인; upstream 본문은 키 보호를 위해 출력하지 않음 |
| `COMMENTS_DISABLED` | 댓글이 활성화된 다른 영상 선택 |
| `YOUTUBE_NOT_FOUND` | 영상 ID와 현재 접근 가능 여부 확인 |
| `YOUTUBE_QUOTA_EXCEEDED` | Cloud console quota 확인 후 다시 실행 |
| `YOUTUBE_UNAVAILABLE` | 연결/서버 상태 확인 후 새 파일명으로 재실행 |
| `INVALID_API_RESPONSE` | 잘못된 응답·반복된 page token·parent 불일치; 수집 성공으로 처리하지 않음 |
| `OUTPUT_EXISTS` | 새 출력 파일명 선택 |

원격 CI와 로컬 테스트는 가짜 API 응답을 사용합니다. live 호출, 실제 표본 내용, quota 설정, 수집 텍스트의 품질은 첫 실행에서 확인해야 합니다.
