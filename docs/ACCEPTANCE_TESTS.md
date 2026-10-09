# 단계별 검증 목록

2단계의 S01–S12는 [tests/test_ingestion.py](../tests/test_ingestion.py)에 구현했습니다.
ingestion은 29개 메서드이며 타입/참조/오류 사례 일부는 subTest로 나눕니다. C/R/E/A 항목은 아직 구현 예정입니다.
공식 API 수집 검사는 [tests/test_youtube.py](../tests/test_youtube.py)에 24개 메서드로 추가했습니다. 실제 HTTP 호출 없이 응답을 모사합니다.
정상 실행 결과와 모델 품질 평가는 별도로 보고합니다.

| ID | 단계 | 입력 / 상황 | 기대 결과 |
| --- | --- | --- | --- |
| S01 | 2 | 정상 다국어 snapshot | 원문·언어·sample provenance 보존 |
| S02 | 2 | 중복 comment ID | INVALID_SNAPSHOT |
| S03 | 2 | present인데 존재하지 않는 parent / self-parent / cycle | INVALID_REFERENCE |
| S04 | 2 | parent_status=missing, 외부 parent ID | snapshot 허용; 누락 문맥 명시 |
| S05 | 2 | root인데 parent ID 있음 / missing인데 실제 parent 존재 | INVALID_REFERENCE |
| S06 | 2 | 공백·Unicode 정규화 | text_analysis만 변경; text_original 보존 |
| S07 | 2 | 같은 텍스트와 parent / 다른 parent의 같은 reply | 전자는 alias 보존; 후자는 별도 원문 유지 |
| S08 | 2 | 순서가 다른 동일 comments 배열 | 동일 canonical duplicate 선택 |
| S09 | 2 | 알 수 없는 필드, bool likes, 음수 rank, NaN, 잘못된 timestamp | INVALID_SNAPSHOT |
| S10 | 2 | source/reply/target_count가 서로 다름 | 실제 source와 thread 집계를 구분 |
| S11 | 2 | 빈 원문 | 로드/보존; 빈 댓글끼리 의미 있는 duplicate로 묶지 않음 |
| S12 | 2 | 쓰기 실패 또는 존재하는 output 경로 | 원본 파일 보존; 명시적 오류, 묵시적 덮어쓰기 금지 |
| C01 | 3 | 독립 주장이 2개인 댓글 | 출처는 같고 span이 다른 claim 2개 |
| C02 | 3 | 찬성 + 예외 조건이 결합된 댓글 | 조건 누락 없이 conditional claim |
| C03 | 3 | 이모지 앞뒤의 한국어 quote | Unicode code point 기준 span 일치 |
| C04 | 3 | normalization/번역 좌표를 원문에 잘못 적용 | INVALID_SOURCE_SPAN |
| C05 | 3 | 이유가 없는 원문 | reason=null; 이유를 만들어내지 않음(의미 검토도 필요) |
| C06 | 3 | reaction / question / missing context / duplicate | eligibility 보존; standalone claim 생성 금지 |
| C07 | 3 | 빈 모델 응답 / 일부 comment 결과 누락 | INVALID_MODEL_OUTPUT; 0개 claim 성공으로 처리하지 않음 |
| C08 | 3 | model timeout | failed run과 오류; fixture 대체 금지 |
| C09 | 3 | embedding 개수/차원/ID 불일치, NaN, 영벡터 | INVALID_EMBEDDING |
| C10 | 3 | cluster에 배정되지 않은 claim | unassigned에 보존; coverage에 반영 |
| R01 | 4 | split에서 member 유실·중복·추가 | INVALID_REVIEW; 입력 상태 변경 없음 |
| R02 | 4 | merge 출력이 입력 합집합과 다름 | INVALID_REVIEW |
| R03 | 4 | superseded 후보를 다시 검토 | INVALID_REVIEW |
| R04 | 4 | 원문 1개의 claim 3개 / 중복 alias를 포함해 3개 | accept 불가; source 수 부풀림 방지 |
| R05 | 4 | 의미 있는 원문 2개 | rare; source 링크 보존; spec 없음 |
| R06 | 4 | 원문 3개 이상이지만 해석 불명확 | uncertain; spec 없음 |
| R07 | 4 | coherent한 canonical 원문 3개, 유효 인용 | accepted 및 spec 생성 |
| R08 | 4 | 하나의 claim이 두 accepted spec에 포함 | EVIDENCE_BOUNDARY_VIOLATION |
| R09 | 4 | 한 원문에 속한 서로 다른 claim이 다른 spec에 포함 | 허용; 각 span의 증거 권한을 분리 |
| R10 | 4 | summary/reason/condition에 미배정 claim 인용 | 공개 차단 |
| R11 | 4 | split/merge 후 후보가 아직 candidate | Factory completed 금지 |
| R12 | 4 | 일부 member만 inspected인 terminal review | INVALID_REVIEW |
| R13 | 4 | coherence/분리/인용 지원 중 하나가 false 또는 null | accept 거절 |
| E01 | 5 | V1/V2 비교 | 같은 입력 artifact hash; V2 재추출 없음 |
| E02 | 5 | rare/uncertain/추출 실패가 많음 | 전체 및 eligible 분모와 누락 항목을 모두 보고 |
| A01 | 6 | 같은 질문을 두 관점에 전달 | 증거와 history가 분리된 답변 |
| A02 | 6 | 실제 존재하지만 미배정인 citation / 문맥 전용 claim | 공개 차단 |
| A03 | 6 | 인용 ID는 맞지만 내용이 지지하지 않음 | 의미 Auditor가 revise/uncertainty/abstain; 초안 공개 금지 |

검토 시 구조 검사는 참조·상태 전이를 확인하고, 인간/모델 의미 검토는 coherence·조건 보존·인용의 지원 여부를 확인합니다.
구조 검사를 통과한 합성 예제는 실제 clustering 또는 다국어 성능을 증명하지 않습니다.

## 공식 API 수집 추가 검사

- 지원 URL/ID와 잘못된 host·중복 video ID 파라미터.
- relevance/time pagination, 순위 provenance, 같은 comment ID의 중복 관측.
- thread ID와 top-level comment ID 구분, parent별 reply pagination, round-robin 순서.
- total/per-thread/request 상한, partial 상태, 관측 reply count와 실제 확보량 차이.
- 키 header, redirect 차단, 오류 본문 비노출, 댓글 비활성화·quota·인증·일시적 오류.
- 일시적 오류 재시도 횟수와 호출 예산, 반복 page token 차단.
- 기존 output 확인 시 network 이전 종료, 오류 중간 결과를 최종 파일로 저장하지 않음.
- 수집 snapshot → 기존 validator → normalizer 연결.

첫 실제 API 키·영상으로 하는 소량 smoke test는 아직 수행하지 않았습니다.
