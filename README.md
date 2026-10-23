# CommentScope — 현재 구현과 조원 테스트

**2026-10-23 최신 상태:** 전체 기능별 구현/미완료, 검증 한계, 실행 방법은 **[조원 공유 문서](docs/TEAM_STATUS.md)**를 먼저 읽습니다.

**클러스터링 → Agent 생성 초안을 함께 수정하려면 [파이프라인 개발 안내](docs/PIPELINE_DRAFT.md)를 읽습니다.** 저장소 루트에서 `python tools/check_factory_draft.py`로 모델 없이 연결·집계 계약을 검사할 수 있습니다. 실제 모델 품질 평가는 별도입니다.

- 실제UBI 자료에서Agent2개·각유효지지3개→실제6응답→HTTP 경로 검증.
- 전체Factory 활용률/G3/G4, 검증기 독립 정확도, 과거 수정 전체의 개선 효과, 조원 프론트·참가자 테스트는 미완료.
- Python3.12에서 `src` 폴더로 이동해 `python -m commentscope.agents.team_demo --session-dir ../runs/team-demo` 실행→**http://127.0.0.1:8766**. **합성 연동 데모**이며 실제 댓글·모델 성능 검증이 아닙니다.
- [API](docs/COMPARE_BACKEND_API.md) · [공개 검증 요약](docs/examples/backend-validation-summary.json) · [사용자 테스트 과업](docs/COMPARE_BACKEND_USER_TEST_TASKS.md)

실제corpus·댓글·ledger·모델응답은 공개하지 않습니다. 실제자료 재현에 필요한 조건은 위 공유 문서를 따릅니다.
