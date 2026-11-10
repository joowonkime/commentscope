# 전체 Factory 비용 계획과 실행 경계

TASK-017, REQ-008/010, DEC-005/008. 구현 전 계약. 이번 작업은 유료호출0이다.

현재96개 실행은 공통후보5개를480개 원문/후보 pair로 비교하며,350개까지 판정하고 한도에서
멈췄다. 완료된584응답에는 source-context/world192개도 포함된다. 원문 문맥 캐시와 동일plan
checkpoint는 이미 있으므로 이를 새 절감이라고 집계하지 않는다. 호출수·입력크기·실청구·
최대예약·전체완료가능성은 각각 보고한다.

## 무료 감사와 예측

기존 run의 고정plan·원본request/result·공유장부를 읽는다. 외부/API/key 접근은 하지 않는다.
실제 공급자응답의 비용과 고정model/deployment를 확인해 stage별 비용 profile을 만든다.
공통제안은 adapter가 core로 전송했어도 실제prompt로 구별한다. nomination/initial/expanded는
membership-raw로 묶고 실행내 동일완료응답을 새호출로 세지 않는다. 미완료요청은 응답비용0의
정상응답으로 넣지 않는다. embedding·fact·runtime을 누락하지 않는다.

후보5개/원문96개의 pair 계획은 정확히480이다. shared 경로는 원문별extraction 없음이 의미
미해석 승인이 아니므로 expansion 상태를unresolved로 유지한다. 후보6개 이하이면 검색+확장으로
모든후보를 비교한다. 그보다 많으면 source별nominee를 포함한 `min(K,6+n_s)` 상한을 쓴다.
검색단계를 생략하거나 의미점수를 지지로 집계하는 비용절감은 채택하지 않는다.

profile은 과거요청의 비용참조다. 같은model/deployment라도 다른prompt/자료의 의미성공이나
정확한 서비스단가를 승계하지 않는다. 전체 workload는 공통발견, 원문/후보문맥,raw관계,
후속근거,core,원문node,입장연결,전제/귀속/감사,외부사실,runtime,embedding을 모두 명시한다.
모르는호출수나 단가는null로 남기며 전체예상액을null로 표시한다. 측정한부분 합계를 전체라고
부르지 않는다. 노드수·긍정edge·논거·사실수·Agent수는 모델결과에 따라 달라지므로 scenario의
가정을 표시한다. 실제96/999품질이 그가정대로나온다는 뜻이 아니다.

## 제안 후 본실행 gate

이번연결대상은 `tools/shared_factory_trial.py`의 공통관점 development 경로다. 보존된legacy/
formal 실행기에는 이새gate를자동이식하지않았다. 해당경로의기존권한·장부·formal admission은
그대로이며, 이문서로 다른실행기의새실행을승인하지않는다.

기존상한 내 proposal-only 단계는 유지한다. 후보가 확정되면 해당plan/candidate SHA와 모델배정,
비용profile SHA, 전체stage 호출상한, 안전여유를 고정한 `cost-preflight.json`을 준비한다.
실행용profile은 원래보관run을 다시무료감사해 정확히일치해야 한다. JSON에 임의의싼단가를
써넣거나 다른실행비용을 바꿔붙여 본실행을 승인할 수 없다. 거절된견적은별도파일로 보존하며
유효한preflight를만들지 않는다. 제안 checkpoint/돈/한도를 초기화하지 않고 무료견적을 보완할 수 있다.
본실행은 이 파일이 없거나 변경됐거나 stage가 미측정/미계획이거나, 남은예산으로 여유를 포함한
예상잔여비용을 감당하지 못하면 첫 membership 호출 전에 거절한다. 이 gate가 금융권한이나
실제완료 보장은 아니다. 원trial/owner/총50/시간/원문기한과 요청별wire 예약은 그대로 적용한다.

실행 중 실제 고유요청이 선언한stage상한을 넘으면 다음요청 전에 중단한다. 같은plan의 완료
checkpoint 재열람은 상한을 다시소비하지 않는다. 실패/미완료요청은 자동재전송하지 않는다.
embedding도 상한에 포함한다. 새로운서버/계획/별칭으로 비용이나 호출상한을 초기화하지 않는다.

다른run의 원격응답을 현재semantic 입력으로 재사용하지 않는다. profile은 비용 추정에만 쓴다.
알려지지 않은후속단계를0회로 간주해 본실행을 허용하지 않는다. 선언한0회도 명시적 가정이며,
실제로그stage가 필요하면 상한에서 멈춘다. 조건미달은 전체완료·MVP성공으로 기록하지 않는다.

## 정상과 부정 검사

- 실제지출·예상잔여·최대예약·보수적과금·전단계합계/미측정을 구별한다.
- 후보0개,고정96/5,많은nominee,단독/복수지지·원문node많음에 따른 pair와후속cost를 표시한다.
- 누락stage/null단가,다른model,변경된plan/후보/profile,기존지출미반영,부족한예산은 거절한다.
- 같은요청재열람은 무료/중복0,다른source/target/stage는 새요청이며 상한을 넘으면 provider 미호출이다.
- 무료감사는 모델/네트워크를 호출하지 않으며 과거의 의미품질·지지수·예산시작값을 바꾸지 않는다.

## 비용 최적화 후보

책임 계층은 구조v1로 유지한다. 같은원문의 여러후보에 대한raw판정을 묶는 transport와
원문관측의 공통입력 단일전송은 다음비교 후보이며 아직채택하지 않는다. 각candidate의 ID/출처/
조건/관측과 전체batch 영수증을 보존하고, 긍정edge의 독립근거검사·사실·host승인을 유지해야 한다.
호출수감소만으로 달러절감이나 의미품질동등을 승인하지 않는다.

[무료감사·시나리오 결과](FACTORY_COST_RESULT.md)에실측/미측정/예산한계를분리했다. Mermaid구조는[구조v1](ARCHITECTURE_BASELINE.md)을따른다.

## 비용을 쓰지 않는 사용 순서

각명령의출력은 Git에서제외한 `runs/` 아래에둔다. profile은 원래영수증과고정archive를읽으며
실제모델응답을새pipeline입력으로보내지않는다.

```bash
python tools/plan_factory_cost.py audit runs/previous \
  --output runs/cost-review/reference.json
python tools/plan_factory_cost.py template runs/current \
  --output runs/cost-review/workload.json
python tools/plan_factory_cost.py preview runs/current \
  --workload runs/cost-review/workload.json \
  --profiles runs/cost-review/reference.json \
  --available-usd 1.50 --output runs/cost-review/preview.json
```

`template`은확정후보와scope로 pair/runtime 등알수있는수를채우고 모르는stage를null로남긴다.
1.50은명령형식예시이며 새잔액/허가가아니다. 실제잔액은기존장부로확인한다. `preview`는
진단파일만생성하며 pending/미측정이있어도실행권한을만들지않는다.

필요한자료를측정하거나정당화한상한을고정한뒤 `review --workload ... --profiles ...`를사용한다.
누락된측정은모델을자동호출해서채우지않는다. 기존독립부품진단을향후승인된범위에서측정할수는
있지만 이번작업은신규모델호출0이다. 유효한preflight가있어도실제실행은기존시간/금융/품질조건을
별도로통과해야한다. 거절견적은보존되며 무료로보완할수있고, 수락한계획/입력은동결한다.

원문별 묶음 전송은 [SOURCE_MEMBERSHIP_BATCH](SOURCE_MEMBERSHIP_BATCH.md)의 opt-in 구현을 따른다. 별도 `membership-source-batch` stage와 최대 후보 수를 포함한 실제 profile이 필요하며 기존 scalar 단가를 승계하지 않는다.
