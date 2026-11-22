"""Launch a bounded private QA or hosted assessment against registered Factory analyses."""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.product.analysis import from_factory
from commentscope.product.web import ProductServer
from commentscope.providers.execution_cycle import EVALUATION_CYCLE_VERSION, PRODUCT_CYCLE_VERSION, cycle_guard
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import dollars, units
from commentscope.storage import write_json_exclusive
from experiments.openrouter_factory_probe import private
from tools import serve_mvp


def load_catalog(path):
    private(path)
    catalog = read_json(path)
    folders = [(path.parent / item).resolve() for item in catalog['analyses']]
    if not folders or len(folders) != len(set(folders)):
        raise ValueError('Provide distinct analysis folders with the default video first.')
    deployment = (path.parent / catalog['deployment']).resolve()
    for item in [*folders, deployment]:
        private(item)
    analyses = [from_factory(folder) for folder in folders]
    for analysis in analyses:
        analysis.live()
    return folders, analyses, deployment


def write_matching(path, value):
    if path.exists():
        if read_json(path) != value:
            raise ValueError('Saved authorization changed: '+path.name)
    else:
        write_json_exclusive(path, value)


def server_plan(state, catalog, folders, analyses, deployment, cap, until):
    key = os.environ.get('OPENROUTER_API_KEY','').strip()
    if not key:
        raise ValueError('Set OPENROUTER_API_KEY in the server environment.')
    if not 0 < units(cap) <= units('2'):
        raise ValueError('The shared product window accepts a positive cap up to 2 USD.')
    cap = dollars(units(cap))
    if until is not None:
        until = datetime.fromisoformat(until)
        if until.utcoffset() is None:
            raise ValueError('Supply a grading deadline with an explicit time zone.')
    scope_path = state/'authorization.json'
    policy_path = state/'policy.json'
    cycle_path = state/'cycle.json'
    server_path = state/'server'
    identity = {'key_sha256':sha256(key.encode()).hexdigest(), 'cap':cap, 'catalog_sha256':sha(catalog),
                'folders':[str(p) for p in folders], 'analysis_ids':[a.id for a in analyses],
                'deadline_requested':until.isoformat() if until else None, 'deployment_sha256':sha(deployment)}
    if scope_path.exists():
        scope = read_json(scope_path)
        if scope['binding'] != identity:
            raise ValueError('The saved server is bound to another key, catalog, cap or grading deadline.')
    else:
        if any(p.exists() for p in (policy_path, cycle_path, server_path, state/'spend.sqlite')):
            raise ValueError('Restore this server’s original authorization from its backup.')
        metadata = serve_mvp.key_metadata()
        if any(metadata[k] is None for k in ('limit','limit_remaining','usage')):
            raise ValueError('The team OpenRouter key needs a configured spend limit.')
        total = units(metadata['limit'])
        opening = max(units(metadata['usage']),total-units(metadata['limit_remaining']))
        if total-opening < units(cap):
            raise ValueError('Insufficient remaining key credit for this window.')
        start = datetime.now(timezone.utc)
        expires = min(datetime.fromisoformat(a.compiled['expires_at']) for a in analyses)
        deadline = until or min(start+timedelta(hours=7),expires)
        duration = timedelta(days=14) if until else timedelta(hours=7)
        if not start < deadline <= min(expires,start+duration):
            raise ValueError('Choose a future deadline within 14 days and the registered sources’ lifetime.')
        scope = {'binding':identity, 'started_at':start.isoformat(), 'deadline':deadline.isoformat(),
                 'policy':{'account_id':'product-'+identity['key_sha256'][:16], 'ledger':str(state/'spend.sqlite'),
                           'maximum_usd':dollars(total), 'opening_charge_usd':dollars(opening)}}
        write_json_exclusive(scope_path,scope)
    write_matching(policy_path,scope['policy'])
    cycle = {'version':EVALUATION_CYCLE_VERSION if until else PRODUCT_CYCLE_VERSION,
             'tasks':['TASK-011','TASK-012'], 'started_at':scope['started_at'],'deadline':scope['deadline'],
             'maximum_additional_usd':cap, 'historical_charges_preserved':True,
             'shared_policy_file':str(policy_path), 'shared_policy_sha256':sha(policy_path),
             'selected_deployment':read_json(deployment),
             'user_request':'Serve the registered CommentScope analyses for the explicitly bounded evaluation.'}
    cycle_guard(cycle,allow_expired=server_path.exists())
    write_matching(cycle_path,cycle)
    if not server_path.exists():
        serve_mvp.prepare(server_path,folders[0],cycle_path,session_ttl_seconds=86400 if until else 3600,
                          room_maximum_usd=cap,automatic_debate=True,additional_factory_runs=folders[1:])
    return server_path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=Path('runs/qa-inputs/catalog.json'))
    parser.add_argument('--state',type=Path,default=Path('runs/qa-server'))
    parser.add_argument('--check',action='store_true',help='Validate the archived Factory analyses offline.')
    parser.add_argument('--max-usd',default='1')
    parser.add_argument('--evaluation-until',help='Fixed ISO timestamp, up to 14 days from the first launch.')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--public-origin',help='Exact HTTPS origin of the reverse proxy.')
    args=parser.parse_args(argv)
    os.chdir(ROOT)
    catalog=args.catalog.resolve()
    folders,analyses,deployment=load_catalog(catalog)
    for analysis in analyses:
        public=analysis.public()
        print(f"{public['video']['video_id']} | {public['analyzed_comments']} comments | "
              f"{len(public['perspectives'])} perspectives | expires {public['expires_at']}",flush=True)
    if args.check:return 0
    if args.public_origin:
        origin=urlsplit(args.public_origin)
        if (origin.scheme!='https' or not origin.hostname or origin.username or origin.password
                or origin.path not in ('','/') or origin.query or origin.fragment):
            raise ValueError('Provide the exact HTTPS origin without a path.')
    state=args.state.resolve()
    private(state)
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with experiment_lock(state):
        directory=server_plan(state,catalog,folders,analyses,deployment,args.max_usd,args.evaluation_until)
        product,legacy,broker=serve_mvp.build(directory)
        try:
            with ProductServer(product,legacy,args.port,public_origin=args.public_origin) as server:
                address=args.public_origin or f'http://127.0.0.1:{server.server_port}'
                print(address.rstrip('/')+'/mvp | '+broker.status(),flush=True)
                server.serve_forever()
        except KeyboardInterrupt:pass
        finally:product.close()
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,RuntimeError,TimeoutError) as error:sys.exit(str(error))
