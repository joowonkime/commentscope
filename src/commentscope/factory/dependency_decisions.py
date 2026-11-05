"""Blind source observations for the first J4-U/L development controls only."""
from copy import deepcopy
from commentscope.providers import openrouter_decisions as transport
from commentscope.factory.automatic_contract import digest

VERSION='blind-argument-dependency-decisions-20261105-v1'
KINDS={'fact':'An asserted empirical description of past or present conditions.',
       'value':'A normative/evaluative preference, importance judgment, or support for a policy.',
       'prediction':'A forecast or modal possibility about what may happen.',
       'uncertain':'The source type is mixed or cannot be established.'}
AUTHORSHIP={'asserted':'The original author asserts or endorses this unit.',
            'not_asserted':'The author reports, quotes or rejects this unit without endorsing it.',
            'uncertain':'Authorship cannot be established.'}
FUNCTIONS={'position':'The position itself, including an inferred conclusion.',
    'reason':'An offered explanation or because-ground for its own owner position.',
    'concession':'Accepted despite the position, not its offered justification.',
    'essential_condition':'A condition on when the author supports the position.',
    'factual_premise':'An empirical premise in the stated reasoning.',
    'scope_annotation':'An unasserted conditional antecedent or scope annotation.',
    'uncertain':'The function cannot be established.'}
RELATIONS={'necessary_fact':'This unit is an asserted factual premise the author uses to derive TARGET. Removing it loses the stated factual inference. A personal policy motive alone is not a factual prerequisite for a value claim.',
    'personal_ground':'An optional personal or evaluative reason for TARGET, not a required factual premise.',
    'condition':'A condition on when TARGET applies, not an assertion that the condition is satisfied.',
    'none':'This unit has none of these directed relations to TARGET. Ownership of a because-ground is not a factual dependency.',
    'uncertain':'The directed relation cannot be established from ORIGINAL.'}
COVERAGE={'complete':'All necessary source factual premises for TARGET are represented in UNITS, including when none is asserted.',
    'omitted':'A necessary factual premise appears in ORIGINAL but is missing from UNITS.',
    'uncertain':'Necessary-premise completeness cannot be established.'}


def source(observation):
    if (not isinstance(observation,dict) or set(observation)!={'id','original','parent_context_only','units','target_id','owner_position_id'}
            or not isinstance(observation['original'],str) or not observation['original']
            or not 1<=len(observation['units'])<=4):raise ValueError('Bounded complete original required')
    ids=[]
    for u in observation['units']:
        if set(u)!={'id','text','evidence'} or not u['text'] or not u['evidence']:raise ValueError('Literal units required')
        ids.append(u['id'])
        for e in u['evidence']:
            if (set(e)!={'start','end','text'} or type(e['start']) is not int or type(e['end']) is not int
                    or not 0<=e['start']<e['end']<=len(observation['original'])
                    or observation['original'][e['start']:e['end']]!=e['text'] or e['text']!=u['text']):
                raise ValueError('Unit evidence differs from original')
    if ids!=['U'+str(i+1) for i in range(len(ids))] or any(observation[k] not in ids for k in ('target_id','owner_position_id')):
        raise ValueError('Canonical source-local aliases required')
    return deepcopy(observation)


def choice(instructions,criteria):return {'type':'choice','instructions':instructions,'criteria':deepcopy(criteria)}


def request(observation,deployment):
    o=source(observation);target=o['target_id']
    state={'ORIGINAL':o['original'],'PARENT_CONTEXT_ONLY':o['parent_context_only'],'UNITS':{u['id']:u for u in o['units']},
           'TARGET':target,'OWNER_POSITION':o['owner_position_id']}
    questions={}
    for u in o['units']:
        alias=u['id']
        questions['kind_'+alias]=choice('Classify UNITS.'+alias+' by its literal content in ORIGINAL. Distinguish content kind from discourse function; a because-ground can express a value.',KINDS)
        questions['authorship_'+alias]=choice('Does the author assert or endorse UNITS.'+alias+' in ORIGINAL? Parent text cannot donate assertions.',AUTHORSHIP)
        if alias!=target:
            questions['relation_'+alias]=choice('What directed role does UNITS.'+alias+' have in the source reasoning leading to TARGET '+target+'? Read ORIGINAL. Do not compute factual truth or arithmetic; observe which stated premise the author uses. The reverse ownership relation is a different question.',RELATIONS)
    questions['function']=choice('What discourse function does TARGET '+target+' have in ORIGINAL relative to OWNER_POSITION?',FUNCTIONS)
    questions['coverage']=choice('Are necessary factual premises for TARGET '+target+' represented among all UNITS? Do not invent external premises.',COVERAGE)
    payload={'model':deployment['model'],'provider':transport.routing(deployment),'state':state,'questions':questions}
    transport.validate_request(payload,deployment)
    return payload


def observe(observation,response,deployment):
    payload=request(observation,deployment);answers=transport.answers(payload,response,deployment)
    labels={k:v['choice'] for k,v in answers.items()};target=observation['target_id'];required=[];guards=[]
    if labels['kind_'+target]=='uncertain':guards.append('target_kind_uncertain')
    if labels['authorship_'+target]!='asserted':guards.append('target_authorship_unverified')
    if labels['function']=='uncertain':guards.append('target_function_uncertain')
    if labels['coverage']!='complete':guards.append('premise_coverage_unverified')
    for u in observation['units']:
        alias=u['id']
        if alias==target:continue
        relation=labels['relation_'+alias]
        if relation=='uncertain':guards.append('premise_relation_uncertain')
        if relation=='necessary_fact':
            required.append(alias)
            if labels['kind_'+alias]!='fact' or labels['authorship_'+alias]!='asserted':guards.append('premise_type_or_authorship_unverified')
    return {'artifact_kind':VERSION,'source_sha256':digest(observation),'request_sha256':digest(payload),
            'wire_sha256':transport.wire_sha256(payload,deployment),
            'response_sha256':digest(response),'kind':labels['kind_'+target],'function':labels['function'],
            'requires':sorted(required),'guards':sorted(set(guards)),'answers':answers,
            'production_admission':False,'evaluation':'development_argmax_labels_only_uncalibrated'}


def compare(observation,observed,declaration):
    if observed['source_sha256']!=digest(source(observation)):raise ValueError('Observation belongs to another original')
    if set(declaration)!={'kind','function','requires'} or not isinstance(declaration['requires'],list):raise ValueError('Complete declaration required')
    ids={u['id'] for u in observation['units']}
    if (len(set(declaration['requires']))!=len(declaration['requires'])
            or any(i not in ids or i==observation['target_id'] for i in declaration['requires'])):
        raise ValueError('Invalid declared prerequisite aliases')
    guards=list(observed['guards'])
    if observed['kind']!=declaration['kind']:guards.append('kind_mismatch')
    if observed['function']!=declaration['function']:guards.append('function_mismatch')
    if set(observed['requires'])-set(declaration['requires']):guards.append('missing_factual_prerequisite')
    if set(declaration['requires'])-set(observed['requires']):guards.append('wrong_factual_prerequisite')
    return {'admitted':not guards,'guards':sorted(set(guards)),'declaration_sha256':digest(declaration),
            'observation_sha256':digest(observed),'production_admission':False}
