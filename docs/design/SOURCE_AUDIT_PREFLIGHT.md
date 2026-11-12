# 통과 불가능한 출처의 후속 호출 생략

TASK-022 / REQ-001·003·008·010. 기존 승인 규칙을 그대로 사용하는 실행 최적화다.
새 의미 승인이나 source completeness 완화가 아니다. 원 실제 비교와 별도 코드로 검증한다.

## 관측과 계약

고정 실제 비교 A는18개 논거 record에서 의존성 질문1,731개/물리요청116개를 구성했다.
29개 unit을 가진 출처 하나가930개 질문/59개 요청을 만든다. unit U와 해당 후보 C에 대해
질문 수는 `U*(U-1+C)+2*U+C+(U+C)`이며 현재 chat 전송도16질문씩 분할한다.
실제91개 의존성 응답/$1.5948085 뒤 전체 실행이5달러 상한에서 멈췄다.

이18개 중13개는 이미 고정한 해석/의존성 선언 때문에 기존 모든 source policy에서
게시할 수 없다. 잠재적으로 가능한5개 출처의 의존성 요청은5개다.116→5는 이 자료에서의
정적 호출 수 비교이며 과거 비용 환불·새 모델 실행·일반 서비스 단가나 정확도 개선 증거가 아니다.

`candidate_source_coverage.potential_candidates(record)`는 먼저 기존 provenance를 검증한다.
현재 owned source 계약만 분석하며 다른 정상 legacy 형식은 보수적으로 전 후보를 유지한다.
다음은 현재 declaration을 후속 검토가 고쳐 주지 않는 기존 차단 조건이다.

- `dependency_status`가 complete가 아님.
- unresolved source에 원 hold가 없거나 기존 SCOPABLE 외의 hold가 있음.
- SCOPABLE만 있는 unresolved source라도 해당 후보의 자기 core position이 없거나,
  해당 후보의 고정 alignment가 uncertain임.

complete source는 유지한다. 다른 후보만 실패하고 자기 후보가 가능한 SCOPABLE source도 유지한다.
잠재 후보 목록은 승인이나 지지 표가 아니며 후속 owner/dependency/source/fact 검증을 전부 통과해야 한다.

## 실행 경계

legacy split typed 경로에서만 잠재 후보0인 출처의 owner/dependency/final audit 호출을 생략한다.
원 record·units·원 membership map·후보 수·보류는 그대로 보존한다. 명시적 preflight hold를 저장한다.
audit가 없다는 이유로 supported를 채우지 않는다. Compiler는 같은 전체 records를 받아
기존 검증 누락·지지3개·core-required source/fact 실패 규칙으로 계속 차단한다.
B1 graph 경로, 다른 source 형식과 비typed 경로의 의미 계약은 변경하지 않는다.

## 먼저 검증할 사례

- source 언어/타입/구문이 이미 unresolved인 경우 후속 요청 감소와 동일 게시 bundle/Agent.
- 다른 후보만 실패한 SCOPABLE source의 유효 후보 보존.
- 변조된 record 거절, map/보류 원문 보존, 미관측을 승인으로 채우지 않음.
- factual core의 필수 출처 실패와 최소3개 지지는 기존 검사를 유지.

현재 실제 실행은 budget stop으로 닫았으며 이 최적화의 신규 유료 호출은0회다.
유효한 긴 원문의 모든 단위 쌍을 비교하는 구조 자체와 B1의 과도한 annotation 일치 조건은 별도 미해결이다.

검증: 조기 종료5개 회귀가9.761초에 통과했고,최종 Factory798개가414.089초에 통과했다.
동일한 합성 응답에서 게시 bundle/Agent가 같고 호출만 감소하는 경우와,
모든 출처가 complete일 때2 Agent·요청 전체가 그대로인 경우를 비교했다.
실제 A의 고정 record에 적용한 계산은 dependency116→5,owner22→8,audit task116→13이며 신규 추론0회다.
