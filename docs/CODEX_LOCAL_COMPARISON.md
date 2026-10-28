# Codex와 로컬 Qwen 비교

개발 중 같은 요청을 고급 Codex 모델과 로컬 Qwen에 보내 결과 차이를 확인한다. OpenRouter 키·예산은 사용하지 않는다. Codex는 ChatGPT 로그인으로 사용하며 해당 계정 사용량을 소모한다. 이 도구는 기존 G1~G4 합격 판정과 별개인 개발 비교다.

`providers/codex_runner.py`가 Codex CLI를 기존 요청·응답 형식과 SQLite 호출 장부에 연결한다. `experiments/compare_local_codex.py`는 기존 Factory 모듈에서 만든 합성 요청 8개를 고정해 두 실행기에 그대로 전달한다. 요청·현행규칙·경험적 이유·가치 이유·예측·인용·참조·필수 조건을 다룬다. 실제 댓글이나 검토 정답은 요청 묶음에 포함하지 않는다.

## 실제 확인 결과 — 2026-10-26

`gpt-6.1-sol / low`, Codex CLI 0.164.0에서 합성 8요청의 첫 응답을 모두 저장했다. 같은 계획의 완료 checkpoint 4건을 재사용하고 나머지 4건만 이어서 호출했다. 이 실행의 새 요청 사이에는 최소60초를 두었고 429 오류는 없었다. 이전 실행들의 429·실패 기록은 보존했으며, 이 결과만으로 속도 제한이 해결됐다고 판단하지 않는다.

개발 담당 에이전트가 원문과 출력, 기존 바인딩 코드를 대조한 결과는 아래와 같다. **검토한 항목 8건 통과이며 독립 human gold·외부 사실 검증·전체 Factory 합격 결과는 아니다.**

| 입력에서 확인한 것 | 관측한 결과 |
| --- | --- |
| 진료 시간 확대 요청 | 작성자의 가치·요청으로 분류 |
| 현재 시행 중인 진료 규칙 | 사실 주장으로 분류 |
| 교통수단 선택을 설명하는 유가 상승 | 경험적 이유를 사실로 분류하고 같은 원문의 부모 입장에 연결 |
| 근무 방식 선호를 설명하는 자율성 | 가치 이유로 분류하고 같은 원문의 부모 입장에 연결 |
| 내일 항구가 닫힐 가능성 | 예측으로 분류하고 `tomorrow` 보존 |
| 동료의 요구를 인용한 뒤 반대하는 작성자 | 인용을 작성자의 주장으로 승인하지 않음 |
| `Inspect playgrounds. The process should be transparent.` | 대명적 표현을 대상인 `playgrounds`나 명령문으로 치환하지 않고 미해결로 보류 |
| 소규모 학교의 비용 면제를 전제로 한 의무 검사 | 작성자 입장으로 추출하면서 `only if` 조건 전체를 그대로 보존 |

같은 계획의 Qwen 비교는 시작 전 보호 검사에서 보류됐다. 당시 호스트 디스크 여유 약2.15GiB, RAM여유3872MiB, commit여유 약1.45GiB로 Qwen의 디스크6GiB·시작 RAM4096MiB·commit4GiB 기준을 충족하지 못했다. 이 비교의 Qwen 호출은 0건이다. 두 모델 간 품질 비교와 새 Qwen G1 검증은 아직 남았다. 이전 Qwen G1v5는 집계 지지 오류와 Agent 0개로 실패했으며, 이번 Codex 8건으로 그 실패를 해결한 것으로 처리하지 않는다. G2~G4도 통과하지 않았다.

Codex 8건의 native usage는 입력92,988·출력260토큰이었다. CLI 기본 지시문 등 실행 환경 비용을 포함하므로 짧은 JSON 출력만 보고 사용량을 예상하면 안 된다. 별도 한 건 진단에서는 [공식 `model_instructions_file` 설정](https://learn.chatgpt.com/docs/config-file/config-reference)으로 기본 지시문을 교체해 입력11,655→7,552토큰(35.2% 감소), 동일 JSON 출력을 관측했다. 논리 요청은 같지만 실행 지시문이 다른 진단이며 전체8건 재검증이나 운영 설정 변경은 하지 않았다. 아직 남는 CLI 비용도 커서 단건 결과를 근거로 대규모 호출을 시작하지 않는다.

원문·첫 응답·요청과 실행 계획 hash·native usage·개발 검토 기록은 비공개 runs에 보존한다. OpenRouter 및 유료 API 호출은 사용하지 않았다.

## 준비와 실행

Linux/WSL, ChatGPT로 로그인한 Codex CLI, 기존 로컬 Qwen deployment와 quota guard가 필요하다. 모델명은 해당 계정에서 지원하는 값을 지정한다. 모델·reasoning effort·CLI 버전/SHA·코드·요청 묶음·Qwen 설정을 실행 전에 동결한다.

```bash
python -m experiments.compare_local_codex prepare runs/my-comparison \
  --codex-model MODEL --codex-effort low \
  --qwen-deployment runs/my-qwen/deployment.json \
  --ledger runs/my-cycle/inference.sqlite --cycle-id my-cycle
python -m experiments.compare_local_codex run runs/my-comparison --backend codex
python -m experiments.compare_local_codex run runs/my-comparison --backend qwen
python -m experiments.compare_local_codex report runs/my-comparison
```

같은 장부를 사용할 때는 기존 cycle ID를 사용한다. 실제 개인 경로·모델·장부는 공개하지 않는다. 새 코드나 모델 설정으로 비교할 때 새 디렉터리를 사용한다.

## 결과 해석

각 모델의 `outputs.json`에 첫 응답·토큰 사용량·시간을 저장한다. `report`는 같은 요청 hash를 확인하고 두 출력을 나란히 보여준다. `same_json`은 JSON 일치 여부이며 정확도나 정답 판정이 아니다. Codex 결과도 원문과 대조해 검토하며, 개발자가 만든 표본을 독립 human gold로 취급하지 않는다.

Codex는 매 요청마다 저장소 밖의 빈 임시 작업 디렉터리와 별도 CLI home을 사용한다. 저장소 안의 빈 하위 폴더는 상위 AGENTS를 자동 발견할 수 있어 격리 용도로 사용하지 않는다. 기존 대화 resume/fork·프로젝트 설정·외부 도구를 사용하지 않는다. ChatGPT 인증은 실행 중 임시 링크로만 연결하고 종료 시 제거한다. 비밀정보가 없는 CLI 캐시는 비공개 runs에 남을 수 있다. API 키 인증을 거부하고 상속된 API 키 환경변수를 제거한다. 도구 사용 이벤트가 발견된 응답은 비교 결과로 승인하지 않는다. 임시 링크 제거는 원본 인증 파일을 삭제하지 않는다.

기존 quota guard가 주간 잔여40% 이하 또는 확인 불가를 보고하면 새 요청을 중단한다. Qwen의 기존 RAM·commit·디스크6GiB 및 기동/GPU 보호는 그대로 유지한다. 모델 파일을 적재하지 않는 Codex CLI는 별도 고정 프로필로 RAM여유1536MiB·commit여유1GiB·디스크여유1GiB를 검사하고 실행 중에도 관측한다. 이 프로필은 Codex 개발 비교에만 적용하며 로컬 Factory 기준을 낮추지 않는다. 상주 모델·CLI는 자신이 시작한 프로세스만 종료하며 완료 응답은 같은 계획에서만 재사용한다. 미확정 호출의 자동 재전송은 금지한다.

Codex CLI에는 API와 같은 hard `max_tokens` 옵션이 없다. 요청의 출력 예산은 기록하지만 advisory로 표시하며, 실제 Codex 사용량에는 harness·reasoning이 포함된다. Codex reasoning effort와 Qwen thinking off도 별도 기록한다. 따라서 이 결과는 두 실행 환경의 개발 비교이며 bare-model API의 동일 조건 벤치마크나 실제 API 비용 측정이 아니다. 최종 서비스 연동의 품질·비용·지연은 별도로 확인한다.

Codex 새 요청은 시작 시점 사이에 최소60초를 둔다. 완료 checkpoint 재사용에는 대기를 추가하지 않는다. 대기 중에도 quota와 자원을 확인하고, 429는 failed.json에 분류해 저장한 뒤 재전송 없이 중단한다. 이 간격은 속도 제한 완화책이며 서버 한도 해제를 보장하지 않는다.

오프라인 검사는 모델·API·실제 인증 없이 실행할 수 있다.

```bash
python -m unittest discover -s tests -p 'test_codex_runner.py'
python tools/check_factory_draft.py
```
