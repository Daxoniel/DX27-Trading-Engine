"""R0-anchored exposed-data contrasts. No downloader or broker integration."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from dx27.adapters.intraday.data import load_csv
from dx27.research.opening_direction import OpeningDirectionFixture, MINUTE
from dx27.research.multisession import ResearchResult
from dx27.research.registration import load_registration, validate_dataset
from dx27.research.statistics import audit_result

ARMS = ('R0', 'LONG_ONLY', 'DELAY_1M', 'EARLY_CLOSE')
REPORT_HASHES = {'A': 'eb0fe643a1fdf59e97d4f6d53119004b9ad3f6a7df8a42f614ff5425ddeb4e59',
                 'B': 'd675aa4ffded773ee9da240cc86e4a1fa22406d6e9b8aa0688441899f5f7abed'}
CSV_HASHES = {'A': '250790d6ad8192b38c6b78a4d4fd1caf735dc239feb913c0c752ed960f20687e',
              'B': '4cc2469a1387ba1ba3cf0bbd5c153a6d3d1b2d38c7b0800ab8b1b782695ceadd'}


class ContrastFixture(OpeningDirectionFixture):
    def __init__(self, session, arm, *, starting_cash=25000.):
        if arm not in ARMS:
            raise ValueError('UNKNOWN_FIXED_ARM')
        super().__init__(session, 'R0', starting_cash=starting_cash)
        self.arm = arm
        if arm == 'DELAY_1M':
            self.entry_at += MINUTE

    def _freeze_signal(self):
        super()._freeze_signal()
        if self.arm == 'LONG_ONLY' and self.direction < 0:
            self.direction = 0
            self.decisions[-1]['reason'] = 'SHORT_DISABLED'

    def _manage(self, at, bar):
        if self.arm == 'EARLY_CLOSE' and at >= self.flatten_at:
            long = self.quantity > 0
            gap_stop = bar.open <= self.stop if long else bar.open >= self.stop
            gap_target = bar.open >= self.target if long else bar.open <= self.target
            if not gap_stop and not gap_target:
                self._fill(at, -self.quantity, bar.open, 'SCHEDULED_FLATTEN')
                return
        super()._manage(at, bar)

    def checkpoint(self):
        raise ValueError('CONTRAST_CHECKPOINT_NOT_SUPPORTED')

    @classmethod
    def restore(cls, *args, **kwargs):
        raise ValueError('CONTRAST_CHECKPOINT_NOT_SUPPORTED')


def run_arm(sessions, bars, arm):
    sessions = tuple(sessions)
    if not sessions or any(a.session_id >= b.session_id for a, b in zip(sessions, sessions[1:])):
        raise ValueError('INVALID_SESSION_PLAN')
    result = ResearchResult({}, [], [], [], [], [], [])
    cash, ambiguous = 25000., 0
    for session in sessions:
        model = ContrastFixture(session, arm, starting_cash=cash)
        while model.next_at < session.closes_at:
            at = model.next_at
            model.on_closed_minute(at, bars.get(at), as_of=at+MINUTE)
        r = model.report()
        if r['status'] != 'COMPLETE_FIXTURE' or r['cash'] <= 0:
            raise ValueError('INCOMPLETE_OR_NONPOSITIVE_CAPITAL')
        day = session.session_id
        result.daily.append(dict(session=day, starting_equity=cash, ending_equity=r['equity'],
            data_complete=r['data_valid'], open_positions=0, admissible=True,
            closed_trades=r['closed_trades'], net_pnl=r['equity']-cash,
            daily_return=r['cash']/cash-1))
        result.fills.extend(dict(asdict(f), session=day,
            cash_delta=(-1 if f.side == 'buy' else 1)*f.quantity*f.price-f.commission) for f in model.fills)
        result.equity.extend(dict(row, session=day) for row in model.equity)
        result.decisions.extend(dict(row, session=day) for row in model.decisions)
        if len(model.fills) == 2:
            result.trades.append(dict(session=day, net_pnl=r['realized_pnl'], gross_pnl=r['gross_pnl'],
                commission=r['commission'], spread_cost=r['spread_cost'], slippage_cost=r['slippage_cost']))
        cash = r['cash']
        ambiguous += r['ambiguous_minutes']
    result.summary = dict(status='COMPLETE_RESEARCH_SEQUENCE', initial_cash=25000., ending_cash=cash,
        ending_equity=cash, net_pnl=cash-25000., open_positions=0, ambiguous_minutes=ambiguous,
        evaluation_registered=False, performance_admissible=False, execution_enabled=False,
        effectiveness='NOT_ESTABLISHED')
    return result


def json_bytes(value):
    def default(v):
        if isinstance(v, datetime):
            return v.isoformat()
        raise TypeError(type(v).__name__)
    return (json.dumps(value, default=default, allow_nan=False, indent=2)+'\n').encode()


def verify_reference(result, folder):
    for kind in ('daily', 'fills', 'trades', 'equity', 'decisions', 'quality'):
        actual = json.loads(json_bytes(getattr(result, kind)))
        if actual != json.loads((Path(folder)/f'R0-{kind}.json').read_bytes()):
            raise ValueError('REFERENCE_REPRODUCTION_MISMATCH:'+kind)


def verify_original(root, stage):
    folder = root/f'work/orb-stage-{stage.lower()}/attempt-1'
    public = root/f'docs/reports/orb-stage-{stage.lower()}'
    for n in ('report.json', 'completion.json'):
        if (folder/n).read_bytes() != (public/n).read_bytes():
            raise ValueError('ORIGINAL_PUBLIC_BYTES_MISMATCH')
    if hashlib.sha256((folder/'report.json').read_bytes()).hexdigest() != REPORT_HASHES[stage]:
        raise ValueError('ORIGINAL_REPORT_HASH')
    manifest = json.loads((folder/'completion.json').read_bytes())['artifact_sha256']
    if len(manifest) != 22:
        raise ValueError('ORIGINAL_MANIFEST_COUNT')
    for n, digest in manifest.items():
        if Path(n).name != n or hashlib.sha256((folder/n).read_bytes()).hexdigest() != digest:
            raise ValueError('ORIGINAL_ARTIFACT_HASH')
    return folder


def run(root, output):
    from collections import Counter
    root, output = Path(root).resolve(), Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    hashes, stages = {}, {}
    def write(name, value):
        raw = json_bytes(value)
        with (output/name).open('xb') as f:
            f.write(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    try:
        for stage in ('A', 'B'):
            folder = verify_original(root, stage)
            receipt = json.loads((root/f'work/orb-stage-{stage.lower()}/receipt.json').read_bytes())
            regpath = root/f'docs/research/orb-literature/registrations/stage-{stage.lower()}.json'
            _, design, gate = load_registration(regpath, receipt['registration_sha256'], receipt,
                stage=stage, root=root,
                exposure_audit_path=root/f'docs/research/orb-literature/registrations/stage-{stage.lower()}-exposure.json',
                a_report_path=root/'docs/reports/orb-stage-a/report.json' if stage == 'B' else None)
            data = load_csv(root/f'work/orb-stage-{stage.lower()}/stage-{stage.lower()}-with-june-warmup.csv')
            if data.provenance['csv_sha256'] != CSV_HASHES[stage]:
                raise ValueError('FIXED_INPUT_CHANGED')
            _, _, sessions = validate_dataset(data, design, stage, gate)
            bars = {b.timestamp: b for b in data.bars if b.symbol == 'QQQ'}
            del data
            arms, reference_directions = {}, None
            for arm in ARMS:
                result = run_arm(sessions, bars, arm)
                metrics = audit_result(result, sessions)
                if arm == 'R0':
                    verify_reference(result, folder)
                directions = {f['session']: f['side'] for f in result.fills[::2]}
                if reference_directions is None:
                    reference_directions = directions
                arms[arm] = dict(metrics=metrics,
                    decision_event_counts=dict(sorted(Counter(d['reason'] for d in result.decisions).items())),
                    direction_or_presence_changed_days=sum(directions.get(s.session_id) !=
                        reference_directions.get(s.session_id) for s in sessions))
                for kind in ('summary', 'daily', 'fills', 'trades', 'equity', 'decisions', 'quality'):
                    write(f'{stage}-{arm}-{kind}.json', getattr(result, kind))
                del result
            baseline = arms['R0']['metrics']['net_return']
            stages[stage] = dict(reference_exact_reproduction=True, arms=arms,
                net_return_delta_pp={a: (arms[a]['metrics']['net_return']-baseline)*100 for a in ARMS[1:]},
                input_csv_sha256=CSV_HASHES[stage], input_report_sha256=REPORT_HASHES[stage])
            del bars
        report = dict(status='COMPLETE_EXPOSED_REFERENCE_CONTRASTS', evaluation_registered=False,
            effectiveness='NOT_ESTABLISHED', execution_enabled=False, new_market_data_downloaded=False,
            analysis_completed_at=datetime.now(timezone.utc).isoformat(), stages=stages)
        write('report.json', report)
        write('completion.json', dict(status='LOCAL_ARTIFACTS_COMPLETE', artifact_sha256=dict(hashes)))
        return report
    except Exception as exc:
        write('failure.json', dict(status='BLOCKED_EXPOSED_REFERENCE_CONTRASTS', reason=str(exc),
              exception_type=type(exc).__name__, execution_enabled=False))
        raise


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    run(args.root, args.output)
