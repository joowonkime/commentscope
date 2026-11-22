# 실제 영상으로 M4 팀 QA하기

팀 공유본 `CommentScope_Live_QA_v3.zip`에는 이 브랜치의 Python 앱과 팀 전용 영상 분석이 들어 있다. Python 3.12 이상에서 ZIP을 풀고 `run_live_qa.py`가 있는 폴더에서 실행한다. Git에는 실행 코드와 문서를 배포하고 영상 입력과 대화 DB는 비공개로 관리한다.

```powershell
py -3 run_live_qa.py --check
py -3 run_live_qa.py --max-usd 1
```

macOS와 Linux에서는 `py -3` 대신 `python3`을 사용한다. 첫 명령은 키 없이 영상과 실제 생성 프로필을 검증한다. 두 번째 명령에서 팀용 OpenRouter 키를 비공개로 입력하고 출력된 주소의 `/mvp`를 연다. 각각의 PC에 복사해 실행하면 1달러 상한도 PC별로 적용된다. 한 호스트를 공유하면 해당 서버의 한도를 함께 사용한다. 준비된 영상은 YouTube 키 없이 열린다. 같은 폴더에서 재시작하면 기존 대화, 지출, 종료시각을 사용한다. 포트 충돌 시 `--port 0`을 붙여 빈 포트를 선택한다.

| 팀 공유본의 영상 | 재현할 수 있는 범위 |
| --- | --- |
| Jubilee, AI와 교육 | 기본 영상. 처리한 댓글 180개, 관점 2개. 두 입장은 도구 사용자의 책임과 AI 감지기 신뢰도를 다룬다. [영상](https://www.youtube.com/watch?v=7AGa5z69zqU) |
| CNBC, 주 4일 근무 | Library 또는 영상 URL로 열 수 있다. 처리 댓글 96개, 관점 4개. 고유 댓글 4개가 입장에 연결되며 네 관점 모두 짧은 근무를 지지한다. [영상](https://www.youtube.com/watch?v=RrFaNO3rTaA) |
| 스브스뉴스, 4.5일제 | 로우파이의 원래 영상. 비공개 수집본 751개에 댓글·답글과 좋아요가 저장됐다. 완주한 Factory 결과를 등록하기 전까지 입력 자료로 제공한다. [영상](https://www.youtube.com/watch?v=BAHKmi4F1L8) |

새 URL은 `py -3 run_live_qa.py --collect "YOUTUBE_URL" --max-comments 180`로 수집한다. 이때 서버 운영자에게 YouTube Data API 키가 필요하다. GitHub 브랜치에서는 확대 검색 계약의 3,000개 상한을 준비·재검사·제품 등록에 적용한다. v3 ZIP은 표에 명시한 두 실제 분석을 검증한 배포본이다. 실제 3,000개 영상의 비용과 관점 품질은 별도 측정 항목이다. 수집 후 운영자가 Factory에서 원문 대조를 통과한 Agent를 등록하면 모든 사용자가 Library와 URL로 열 수 있다. 미등록 URL을 입력하면 화면에 안내가 뜨고 작성 중인 의견과 기존 영상이 유지된다.

## 조원이 직접 확인할 흐름

1. 초기 의견을 적고 Explore로 들어간다. **Source comments**를 펼치고 입장과 개별 근거의 원댓글을 확인한다. 댓글 구성과 좋아요 구성에는 복수 연결과 기타 댓글이 각각 한 번만 집계된다.
2. **Compare with my view**를 열어 색과 글자로 표시된 관계를 양쪽 문장에서 찾는다. **Compare all with my view**로 카드별 결과를 비교한다. 새로고침해도 같은 초기 의견의 비교는 재사용한다.
3. Converse의 **New chat**에서 참여자를 고른다. 한 명이면 1:1, 여러 명이면 그룹 대화 또는 자동 토론을 선택할 수 있다. 그룹 대화에서 한 명을 지정해 후속 질문을 보낸다.
4. 검증 보류가 나오면 등록된 원댓글을 확인한다. 일반 대화가 오류로 멈추면 **Ask another question**으로 입력창을 다시 연다. 이전 발언과 지출이 유지된다.
5. 자동 토론의 참여자별 발언과 결론을 읽는다. 실제로 검증·비준을 통과한 합의가 생기면 합의 Agent를 열고 질문한다. 근거가 부족하면 결론에서 어느 단계까지 진행됐는지 확인한다. Reflect에서 직접 작성하거나 제안을 검토해 저장하고 Library에서 다시 연다.

## 개발과 운영의 역할

| 계층 | 구현과 책임 |
| --- | --- |
| 수집과 Agent 생성 | YouTube 수집 → 스냅샷 → Factory 후보 발굴·근거 판정 → Agent 입력 컴파일. 게시 가능한 관점 결정은 이 계층이 담당한다. 새 영상 시험에는 `tools/prepared_video_trial.py prepare --max-new-usd`로 그 실행의 추가 지출 상한을 지정할 수 있다. |
| 분석 표시 | `src/commentscope/product/analysis.py`가 등록 프로필을 카드로 변환한다. 원댓글 ID로 범위와 좋아요를 집계한다. 선택적인 `perspective-names.json`은 실제 등록 ID에 짧은 이름을 연결한다. |
| 대화와 상태 | `product/app.py`는 세션·질문·비교·성찰을 저장한다. `product/debate_service.py`와 `agents/structured_debate_runtime.py`가 자동 발언과 결론을, `agents/synthesis_agent.py`가 비준된 합의의 컴파일을 담당한다. |
| 화면 | `product/mvp.html`, `mvp.js`, `mvp.css`가 같은 호스트의 `/api/v1`을 사용한다. QA 기준은 기존 Figma 문서에 기록했다. [Figma 명세](https://www.figma.com/design/Q5oqIs2ekQIagiboAFX7Qc/MAS?node-id=823-3498) |
| 모델과 운영 | 생성과 검증은 기존 OpenRouter 브로커와 장부를 통과한다. `tools/launch_mvp.py`는 서버를 시작하고 운영자가 지정한 종료 시각과 추가 지출 한도를 고정한다. |

## 채점 기간에 접속할 URL 운영

공개 호스트에 Python 3.12 이상과 지속 디스크를 준비한다. 팀 ZIP의 `runs/qa-inputs/`를 같은 버전의 서버 코드 아래에 둔다. 기본 영상은 `catalog.json`의 첫 항목이다. 같은 사용자로 같은 절대 경로에서 실행하고 재시작 시 `runs/qa-server/` 전체를 재사용한다. 여기에 세션 SQLite, 권한 바인딩, 이전 지출과 호출 영수증이 저장된다. 채점 중에는 고정한 코드와 자료 버전을 사용한다.

1. 운영 서비스의 환경 변수에 팀용 `OPENROUTER_API_KEY`를 설정한다. 팀원이 브라우저를 열 때는 개인 키를 입력할 필요가 없다. 기존 분석만 제공하는 서버는 YouTube 키 없이 실행된다.
2. 운영자의 실제 HTTPS 호스트와 종료시각을 넣어 아래 명령을 실행한다. 평가용 창은 최초 시작부터 최대 14일이고 등록 근거 만료 전에 끝나야 한다. 명시한 총액은 이 기간 전체에 적용되며 최대 2달러다. 예산이 소진되면 새 AI 호출이 멈춘다. 실행 중인 서버에서 기존 기록 읽기와 수동 성찰 저장은 각 세션 유효기간 안에 가능하다.

```sh
python3 tools/launch_mvp.py --check
python3 tools/launch_mvp.py --port 8080 --public-origin "https://YOUR_HOST" \
  --evaluation-until "YYYY-MM-DDT23:59:00+09:00" --max-usd 2
```

3. 서비스 관리자가 같은 명령을 재시작하도록 설정하고 HTTPS 프록시가 같은 VM의 `127.0.0.1:8080`으로 원래 Host를 전달하게 한다. 사이트의 `/mvp`, `/mvp/*`, `/api/v1/*`만 전달한다. 아래는 Caddy에서 사용할 구성이다.

```caddyfile
YOUR_HOST {
    @product path /mvp /mvp/* /api/v1/*
    handle @product {
        reverse_proxy 127.0.0.1:8080
    }
    handle {
        redir / /mvp
        respond 404
    }
}
```

4. 다른 네트워크의 새 브라우저에서 가입이나 설치 없이 의견 저장, 원문, 실제 응답, 토론 결론, 성찰 저장을 확인한다. 서버 재시작 뒤 같은 브라우저에서 기록을 다시 연다. 이 검증을 끝낸 HTTPS 주소를 M4 PDF의 **Live evaluation URL**에 넣는다. 소스 저장소 링크는 별도 제출 항목이다.

과목 OpenRouter 크레딧은 모델 호출에 쓰인다. Google Cloud에서 서버를 만드는 경우 프로젝트에 사용 가능한 Cloud Billing 계정을 연결한다. 결제 계정이 없다면 팀이 승인한 계정을 만들거나 학교가 제공하는 계정의 연결 권한을 받는다. [Google Cloud 결제 계정 만들기](https://docs.cloud.google.com/billing/docs/how-to/create-billing-account) · [프로젝트 연결](https://docs.cloud.google.com/billing/docs/how-to/modify-project)
