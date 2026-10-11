"""Optional real Chromium acceptance check; uses the running local UI/model only.

Install Playwright separately for this developer check. No runtime dependency.
Screenshots/downloads contain private research data; keep --output-prefix ignored.
"""
import argparse
import json
import os
from pathlib import Path
import time

from playwright.sync_api import sync_playwright
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--output-prefix', type=Path, required=True)
    parser.add_argument('--question', action='append', required=True)
    args = parser.parse_args()
    if not 1 <= len(args.question) <= 6:
        parser.error('Use 1..6 questions')
    suffixes = ['.initial.png', '.first-answer.png', '.final.png', '.mobile.png',
                '.comparison.json', '.comparison.html', '.checks.json']
    paths = {s: Path(str(args.output_prefix) + s) for s in suffixes}
    if any(os.path.lexists(p) for p in paths.values()):
        parser.error('Choose a new output prefix')
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    origin = f'http://127.0.0.1:{args.port}'
    checks = {'artifact_kind': 'local-browser-acceptance-0.1', 'human_approved': False,
              'independent_gold': False, 'questions': args.question, 'page_errors': [],
              'external_requests_blocked': [], 'checks': {}}
    started = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-gpu'])
        checks['browser'] = browser.version
        context = browser.new_context(viewport={'width': 1440, 'height': 1100}, accept_downloads=True)

        def local_only(route):
            if route.request.url.startswith(origin + '/'):
                route.continue_()
            else:
                checks['external_requests_blocked'].append(route.request.url)
                route.abort()

        context.route('**/*', local_only)
        page = context.new_page()
        page.on('pageerror', lambda error: checks['page_errors'].append(str(error)))
        try:
            page.goto(origin, wait_until='networkidle')
            page.wait_for_function("() => document.querySelector('#ask').disabled === false")
            checks['checks']['profile_cards'] = page.locator('#profiles > .profile').count()
            page.screenshot(path=str(paths['.initial.png']), full_page=True)
            for i, question in enumerate(args.question, 1):
                page.locator('#question').fill(question)
                # Exercise the native keyboard path, not a direct HTTP substitution.
                page.locator('#question').press('Tab')
                assert page.locator('#ask').evaluate('(el) => el === document.activeElement')
                page.locator('#ask').press('Enter')
                print(json.dumps({'submitted_in_browser': i}), flush=True)
                page.wait_for_function('(n) => document.querySelectorAll("#rounds > .round").length === n',
                                       arg=i, timeout=600000)
                assert not page.locator('#error').is_visible(), page.locator('#error').inner_text()
                if i == 1:
                    citation = page.locator('#rounds .citation summary').first
                    if citation.count():
                        citation.click()
                        checks['checks']['citation_opened'] = page.locator('#rounds .citation[open]').count() >= 1
                    page.screenshot(path=str(paths['.first-answer.png']), full_page=True)
                print(json.dumps({'completed_in_browser': i,
                                  'answers': page.locator('#rounds > .round').last.locator('.answer').count()}), flush=True)
            for kind in ['json', 'html']:
                with page.expect_download() as download:
                    page.locator('#export-' + kind).click()
                download.value.save_as(str(paths['.comparison.' + kind]))
            report = read_json(paths['.comparison.json'])
            assert [r['question'] for r in report['rounds']] == args.question
            sources = {a['agent_id']: {c['evidence_id']: c for c in a['evidence']} for a in report['bundle']['agents']}
            for round_ in report['rounds']:
                for turn in round_['answers']:
                    if turn['status'] == 'abstain':
                        assert not turn['points']
                    for point in turn['points']:
                        assert point['citation'] == sources[turn['agent_id']][point['evidence_id']]
            checks['checks']['exact_own_source_bindings'] = True
            checks['checks']['keyboard_submit_and_downloads'] = True
            checks['expires_at'] = report['expires_at']
            checks['comparison_sha256'] = sha(paths['.comparison.json'])
            checks['outcomes'] = [{'question': i, 'agent': t['agent_id'], 'status': t['status'],
                                   'reason': t['reason'], 'citations': [x['evidence_id'] for x in t['points']]}
                                  for i, r in enumerate(report['rounds'], 1) for t in r['answers']]
            page.screenshot(path=str(paths['.final.png']), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            checks['checks']['mobile_no_horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(paths['.mobile.png']), full_page=True)
            other = context.new_page()
            other.goto(origin, wait_until='networkidle')
            other.wait_for_function("() => document.querySelector('#ask').disabled === false")
            assert other.locator('#rounds > .round').count() == 0
            checks['checks']['second_tab_fresh_session'] = True
            other.close()
            page.on('dialog', lambda dialog: dialog.accept())
            page.locator('#reset').click()
            page.wait_for_function('() => document.querySelectorAll("#rounds > .round").length === 0')
            checks['checks']['reset_clears_conversation'] = True
            assert not checks['page_errors']
            assert checks['checks']['mobile_no_horizontal_overflow']
            checks['status'] = 'passed'
        except Exception as error:
            checks['status'] = 'failed'
            checks['error'] = str(error)
            raise
        finally:
            checks['wall_seconds'] = round(time.monotonic() - started, 2)
            write_json_exclusive(paths['.checks.json'], checks)
            context.close()
            browser.close()
    print(json.dumps({'status': checks['status'], 'checks': checks['checks']}), flush=True)


if __name__ == '__main__':
    main()
