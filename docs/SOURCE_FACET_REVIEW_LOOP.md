# 원문 보존형 주장 계열과 assistant 검수 루프

## 이번에 만든 결과

사용자는 assistant가 평가·수정 루프를 맡고, 논문에 쓸 수 있도록 판단 근거를 남기기를 요청했습니다.
현재 결과는 자동 clustering 성공이 아니라 **검수 지원형 주장 계열 제안**입니다. 실제 댓글21개를 assistant가 읽고
13개 출력을 확인, 8개 출력을 수정했습니다. 필요성7/도입 예측4/가능한 이점2/보류8개로 전부 보존했습니다.
최소3개 계열은2개, 희소 계열은1개이며 승인 PerspectiveSpec/agent는0입니다.

로컬 최신 화면: `artifacts/source-facet-loop-20261011-reviewed.json.html`.
이전9개 한글 해석: `artifacts/assistant-cluster-review-20261011.html`.
실제 원문·출력·평가표·검수는 공개 저장소에 없고 snapshot 만료를 상속합니다.

## 무엇이 바뀌었나

이전 B는 한 원문의 **문장 전체**가 다른 원문에서 지원되는지를 검사했습니다. 이번 실험은 동일 주제 안에서
필요성/도입 예측/가능한 이점 등의 **주장 계열**을 분류하고, 이유·조건·확신의 정도는 원문 카드로 각각 보존합니다.
두 과제는 다릅니다. 결과 묶음이 늘었다고 이전 B보다 clustering 정확도가 올랐다고 주장하지 않습니다.
계열 이름은 모든 member가 공유하는 완전한 명제가 아니며, 실제 agent가 사용할 구체적인 공통 주장도 아닙니다.

`factory/source_facets.py`는 한 번에 원문 하나만 모델에 전달하고 topic_match/assertion_type/polarity/assertion_quote를 받습니다.
긍정/부정 계열은 분리하며 복합·불명확·질문·기타·범위 밖·계약 실패는 자동 배정하지 않습니다.
polarity의 affirmed는 술어의 부정 여부일 뿐 확실성/찬성 여부가 아닙니다. “필요할 수 있다”도 긍정 술어지만 유보를 포함합니다.
정확한 인용 일치가 의미 정확성을 보장하지 않으므로 원문 전체를 호스트가 별도 보존합니다.

현재 AI/자동화–UBI라는 한 주제, 영어 짧은 댓글, 최대24개 실험입니다. 분류 체계/주제는 고정되어 있고 일반 다국어 clustering이 아닙니다.
MVP의 동적 agent 수를 고정한 것도 아닙니다. 자동 승인이나 전체 pipeline 기본값 변경은 없습니다.

## 실행 경계

기본 설치와 README의 동일 Qwen 로컬 서버가 필요합니다. 아래 파일명은 실제 로컬 실행 예시이며 공개 fixture가 아닙니다.

```bash
python -m experiments.source_facet_loop data/ubi-research-20261010.json artifacts/source-facet-loop-20261011-plan.json --split development --revision v1 --output artifacts/YOUR-dev-v1.json --model-label Qwen3-4B-Instruct-2507-Q4_K_M --model-revision a06e946bb6b655725eafa393f4a9745d460374c9 --runtime "llama.cpp b11541 CUDA12.8 context8192 no-context-shift parallel1"
```

계획 JSON에는 snapshot_sha256, development와 confirmation 배열이 필요합니다. 각 요소의 계약은 다음과 같습니다.

```json
{
  "id": "D01",
  "source_comment_id": "ID_FROM_YOUR_SNAPSHOT",
  "source": "Exact source text from the snapshot",
  "allowed_types": ["need"],
  "allowed_polarities": ["affirmed"],
  "topic_match": true
}
```

기대 라벨은 모델에 전달하지 않습니다. 판단 기준과 이유는 실행 전에 기록하고 결과를 보고 바꾸지 않습니다.
`--revision v2`는 사전 정의한 추가 주의문을 사용합니다. `--split confirmation`은 분리한 배열을 한 번 실행합니다.
파일 출처/만료/원문 일치/중복·split 겹침을 확인하며, 실패와 원시 출력을 checkpoint에 보존합니다. 기존 출력은 덮어쓰지 않습니다.

## 검수를 실제 수정으로 연결

`experiments.review_source_facets`는 검수 JSON을 적용해 별도 결과를 만듭니다. 모델 결과는 model_result로 그대로 남기고,
새 판단은 origin=assistant_review로 표시합니다. expected labels를 자동으로 복사해 교정하지 않습니다.
이번 검수는 대화 assistant가 실제 원문21개를 읽고 작성했으며 자동 judge API나 독립 평가자가 아닙니다.

검수 JSON은 reviewer=conversation_assistant, human_approved=false, 입력 파일 순서에 맞는 input_sha256 배열,
summary_ko, experiment_notes_ko와 전체 입력을 정확히 한 번씩 다루는 entries가 필요합니다. 각 entry는
id, decision(confirm/correct/abstain), reason_ko, reading_ko, cautions_ko입니다.
correct에는 corrected={topic_match,assertion_type,polarity}를 추가하며 원문 인용은 호스트가 전체 원문에서 고정합니다.
잘못된 모델 인용도 조용히 수정하지 않고 explicit correct로만 복구합니다. confirm에는 수정 필드를 허용하지 않습니다.

```bash
python -m experiments.review_source_facets data/ubi-research-20261010.json artifacts/source-facet-loop-20261011-assistant-decisions.json artifacts/source-facet-loop-20261011-dev-v2.json artifacts/source-facet-loop-20261011-confirmation-v2.json --output artifacts/YOUR-reviewed.json
```

실제 검수 파일은 위의 특정 모델 출력 hash에 연결되어 있습니다. 새 실행에는 새 검수 파일이 필요하며 이전 검수를 무조건 재사용하지 않습니다.
수정된 결과의 자기 기대값 일치를 모델 정확도로 계산하지 않습니다. 사람 승인/최종 PerspectiveSpec 경로는 없습니다.

## 실패와 프로토콜 변경 기록

1. 기존9개 + 새로운12개의 선택 및 기대값을 실행 전에 기록. 확인12개는 기존 extraction/probe58개 source 제외,
   top-level/500자 이하/AI·자동화와 UBI 관련 regex에 맞는18개를 seed411로 섞어 선택했습니다.
2. 두 프롬프트를 미리 정의하고 개발9개에서 v1→v2 실행. 둘 다8/9로 미래 필요성을 도입 예측으로 오분류.
   자동 성공 기준9/9는 **실패**했습니다. 그대로 보존했습니다.
3. 실패 후 `...-review-stage-plan.json`에 명시적 프로토콜 변경을 기록. 자동 모델 성공 검증 대신 검수 지원 단계로 전환.
   v2를 고정하고12개를 한 번 진단했습니다. 계약10/12, 계약을 포함한 type/topic/polarity 사전 기준 일치5/12.
4. assistant가21개를 읽고 확인13/수정8. 이 중 의미 라벨 수정6, 의미·인용 수정1, 인용 수정1.
   모델의 실패 수치와 별도로 검수 결과2개 주요 계열+1개 희소 계열을 저장했습니다.

확인12개를 reviewer가 라벨 작성 및 구현 전에 읽었으므로 blind holdout이 아닙니다. 결과가 나온 뒤 재튜닝하지 않았지만
독립 검증이나 논문용 일반화 성능이라고 부를 수 없습니다. 기대값 작성자와 검수자가 같으므로 자기 일치는 성능 증거가 아닙니다.
이번 수정은 prompt/schema/representation/assembly가 달라 인과 효과를 단일 요소로 귀속하지 않습니다.

## 다음 논문/MVP 검증

- 현재 자동 classifier가 성공했다고 보고하지 않습니다. 검수 지원 workflow의 feasibility와 오류 유형을 기록할 수 있습니다.
- 새로운 실제 표본과 별도 사람 검수로 과도한 배정/정상 주장 누락/조건 왜곡을 평가해야 합니다. 팀원이 모든1,000개를 읽을 필요는 없지만 독립 검수 표본은 필요합니다.
- 복합 댓글의 주장 분해, 범위 밖 댓글의 다른 주제 연결, 희소 주장 보존을 이후 단계에서 다룹니다. 보류는 의미 없다는 뜻이 아닙니다.
- 원문을 보존해도 agent의 발화가 이를 왜곡할 수 있습니다. 주장별 출처·조건·불확실성을 지키는 agent 생성/응답 검증은 별도 남은 작업입니다.
