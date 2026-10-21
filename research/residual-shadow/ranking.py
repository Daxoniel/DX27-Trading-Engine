"""Audit all original eligible names before selection; frozen parent implementations."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


primary = load('rs_primary', 'research/residual-momentum/features.py')
independent = load('rs_independent', 'research/residual-momentum/audit.py')
parent = load('rs_parent', 'research/sector-momentum/study.py')
base_audit = load('rs_base_audit', 'research/sector-momentum/audit.py')


def finite_feature(value):
    for key in ('score', 'dispersion'):
        if not math.isfinite(value[key]):
            raise ValueError('NONFINITE_SCORE')
    if len(value['coefficients']) != 4 or not all(math.isfinite(x) for x in value['coefficients']):
        raise ValueError('INVALID_COEFFICIENTS')


def select_independent(rows, field):
    # Separate selection code: sorted full ranking, then sector occupancy scan.
    ordered = sorted(rows, key=lambda row: (-row[field], row['symbol']))
    picked = []; occupied = {}
    for row in ordered:
        sector = row['sector']
        if occupied.get(sector, 0) == 2:
            continue
        picked.append(dict(symbol=row['symbol'], sector=sector))
        occupied[sector] = occupied.get(sector, 0)+1
        if len(picked) == 10:
            break
    return picked


def build(asof, adjusted, raw, cohort, calendar, factor_values, rules, residual_rules):
    if 'SOXL' in adjusted or 'SOXL' in raw or any(r['symbol'] == 'SOXL' for r in cohort):
        raise ValueError('RESERVED_SYMBOL')
    formation = parent.features(asof, adjusted, raw, cohort, calendar, rules)
    checked_base = base_audit.verify_features([formation], adjusted, raw, calendar, rules)
    symbols = [r['symbol'] for r in formation['eligible']]
    if len(symbols) != len(set(symbols)):
        raise ValueError('DUPLICATE_ELIGIBLE')
    matched = []; rejected = {}
    for row in formation['eligible']:
        try:
            estimate = primary.score(row['symbol'], asof, adjusted, calendar, factor_values, residual_rules)
        except ValueError as error:
            if str(error) not in ('MONTHLY_STOCK_HISTORY_MISSING', 'SCORE_DISPERSION_TOO_SMALL'):
                raise
            rejected[row['symbol']] = str(error)
            continue
        audit = independent.independent_score(row['symbol'], asof, adjusted, calendar, factor_values)
        finite_feature(estimate); finite_feature(audit)
        independent.verify(estimate, audit)
        matched.append(dict(row, residual=estimate['score'], independent_residual=audit['score']))
    plans = {}
    for selector, rows, field in (
        ('parent_ordinary', formation['eligible'], 'momentum'),
        ('matched_ordinary', matched, 'momentum'),
        ('matched_relative', matched, 'relative'),
        ('matched_residual', matched, 'residual')):
        transformed = deepcopy(formation)
        transformed['eligible'] = [dict(r, momentum=r[field]) for r in rows]
        chosen = parent.targets(transformed, 'ordinary', rules)
        check_field = 'independent_residual' if selector == 'matched_residual' else field
        audited = select_independent(rows, check_field)
        if set(chosen) != {r['symbol'] for r in audited} or any(w != .1 for w in chosen.values()):
            raise ValueError('INDEPENDENT_RANK_MISMATCH')
        # Preserve score-tie symbol order from independent scan, targets are 1% each.
        plans[selector] = audited
    return dict(asof=asof, plans=plans, original_eligible=len(symbols), matched_eligible=len(matched),
                independently_checked_features=checked_base, independently_checked_scores=len(matched),
                rejected=rejected, source_authenticity_verified=False, prospective_ready=False,
                old_input_rehearsal=True, orders=0)
