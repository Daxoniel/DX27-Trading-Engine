"""Independent Decimal normal-equation check of QR factor-adjusted scores."""
from decimal import Decimal, localcontext


def solve(matrix, rhs):
    n = len(rhs); rows = [list(row)+[value] for row, value in zip(matrix, rhs)]
    for j in range(n):
        pivot = max(range(j, n), key=lambda i: abs(rows[i][j]))
        rows[j], rows[pivot] = rows[pivot], rows[j]
        if abs(rows[j][j]) < Decimal('1e-24'):
            raise ValueError('INDEPENDENT_SINGULAR_DESIGN')
        divisor = rows[j][j]; rows[j] = [v/divisor for v in rows[j]]
        for i in range(n):
            if i != j:
                scale = rows[i][j]; rows[i] = [a-scale*b for a, b in zip(rows[i], rows[j])]
    return [row[-1] for row in rows]


def independent_score(symbol, asof, prices, calendar, factors):
    with localcontext() as ctx:
        ctx.prec = 45
        year, month = map(int, asof[:7].split('-')); index = year*12+month-2
        months = [f'{n//12:04d}-{n%12+1:02d}' for n in range(index-35, index+1)]
        before = f'{(index-36)//12:04d}-{(index-36)%12+1:02d}'
        ends = {m: max(day for day in calendar if day[:7] == m and day <= asof) for m in [before]+months}
        def d(v):
            return Decimal(str(v))
        closes = [d(prices[symbol][ends[m]]) for m in [before]+months]
        y = [b/a-1-d(factors[m][3]) for a, b, m in zip(closes, closes[1:], months)]
        x = [[Decimal(1)]+[d(v) for v in factors[m][:3]] for m in months]
        normal = [[sum(row[i]*row[j] for row in x) for j in range(4)] for i in range(4)]
        rhs = [sum(row[i]*v for row, v in zip(x, y)) for i in range(4)]
        coef = solve(normal, rhs)
        u = [v-sum(a*b for a, b in zip(coef[1:], row[1:])) for v, row in zip(y, x)][-11:]
        center = sum(u)/11; sd = (sum((v-center)**2 for v in u)/10).sqrt()
        return dict(score=float(sum(u)/sd), coefficients=list(map(float, coef)), dispersion=float(sd),
                    fit_start=months[0], fit_end=months[-1], rank_start=months[-11], rank_end=months[-1])


def verify(primary, independent):
    for field in ('score', 'dispersion'):
        if abs(primary[field]-independent[field]) > 1e-8:
            raise ValueError('INDEPENDENT_SCORE_MISMATCH')
    for a, b in zip(primary['coefficients'], independent['coefficients']):
        if abs(a-b) > 1e-8:
            raise ValueError('INDEPENDENT_COEFFICIENT_MISMATCH')
    for field in ('fit_start', 'fit_end', 'rank_start', 'rank_end'):
        if primary[field] != independent[field]:
            raise ValueError('INDEPENDENT_WINDOW_MISMATCH')
