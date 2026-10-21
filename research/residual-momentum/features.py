"""Lagged monthly FF3 factor-adjusted momentum; stdlib QR, no trading calls."""
import csv
from datetime import date
import io
import math
from statistics import stdev
import zipfile


def month_shift(month, offset):
    year, m = map(int, month.split('-')); n = year*12+m-1+offset
    return f'{n//12:04d}-{n%12+1:02d}'


def parse_factors(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 5_000_000:
            raise ValueError('EXPECTED_ONE_BOUNDED_CSV')
        text = archive.read(names[0]).decode('utf-8-sig')
    rows = {}; header = False
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 5 and [x.strip() for x in row[:5]] == ['', 'Mkt-RF', 'SMB', 'HML', 'RF']:
            header = True; continue
        if not header or len(row) < 5 or len(row[0].strip()) != 6 or not row[0].strip().isdigit():
            continue
        stamp = row[0].strip(); month = stamp[:4]+'-'+stamp[4:]
        date.fromisoformat(month+'-01')
        if not '2022-04' <= month <= '2025-10':
            continue
        values = [float(x) for x in row[1:5]]
        if month in rows or any(not math.isfinite(x) or x in (-99.99, -999.) for x in values):
            raise ValueError('INVALID_OR_DUPLICATE_FACTOR_MONTH')
        rows[month] = [v/100 for v in values]
    expected = [month_shift('2022-04', i) for i in range(43)]
    if sorted(rows) != expected:
        raise ValueError('FACTOR_MONTH_COVERAGE_FAILED')
    return rows


def fit_qr(x, y, tolerance=1e-12):
    """Twice-reorthogonalized modified Gram-Schmidt and back substitution."""
    n = len(x); k = len(x[0])
    if len(y) != n or n <= k or any(len(row) != k for row in x):
        raise ValueError('INVALID_REGRESSION_SHAPE')
    q = []; r = [[0.]*k for _ in range(k)]
    for j in range(k):
        col = [row[j] for row in x]; norm = math.sqrt(sum(v*v for v in col))
        if not math.isfinite(norm):
            raise ValueError('NONFINITE_REGRESSION')
        for _ in range(2):
            for i in range(j):
                projection = sum(a*b for a, b in zip(q[i], col)); r[i][j] += projection
                col = [a-projection*b for a, b in zip(col, q[i])]
        r[j][j] = math.sqrt(sum(v*v for v in col))
        if r[j][j] <= tolerance*max(1., norm):
            raise ValueError('SINGULAR_FACTOR_DESIGN')
        q.append([v/r[j][j] for v in col])
    rhs = [sum(a*b for a, b in zip(col, y)) for col in q]; coefficients = [0.]*k
    for i in reversed(range(k)):
        coefficients[i] = (rhs[i]-sum(r[i][j]*coefficients[j] for j in range(i+1, k)))/r[i][i]
    if any(not math.isfinite(v) for v in coefficients):
        raise ValueError('NONFINITE_REGRESSION')
    return coefficients


def score(symbol, asof, prices, calendar, factors, rules):
    last_month = month_shift(asof[:7], -1)
    months = [month_shift(last_month, i) for i in range(-35, 1)]
    ends = {d[:7]: d for d in calendar if d <= asof}
    endpoints = [month_shift(months[0], -1)]+months
    if any(m not in ends for m in endpoints):
        raise ValueError('MONTH_END_CALENDAR_MISSING')
    p = prices.get(symbol, {})
    values = [p.get(ends[m]) for m in endpoints]
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('MONTHLY_STOCK_HISTORY_MISSING')
    if any(m not in factors for m in months):
        raise ValueError('FACTOR_HISTORY_MISSING')
    y = [b/a-1-factors[m][3] for a, b, m in zip(values, values[1:], months)]
    x = [[1., *factors[m][:3]] for m in months]
    coef = fit_qr(x, y, rules['numerics']['rank_tolerance'])
    # Intercept is fitted for the exposures, but not subtracted for rank returns.
    u = [excess-sum(b*f for b, f in zip(coef[1:], row[1:])) for excess, row in zip(y, x)]
    window = u[-11:]; dispersion = stdev(window)
    if dispersion <= rules['numerics']['score_sd_minimum']:
        raise ValueError('SCORE_DISPERSION_TOO_SMALL')
    return dict(score=sum(window)/dispersion, coefficients=coef, dispersion=dispersion,
        fit_start=months[0], fit_end=months[-1], fit_months=36,
        rank_start=months[-11], rank_end=months[-1], rank_months=11,
        monthly_returns=y, factor_adjusted_returns=u)
