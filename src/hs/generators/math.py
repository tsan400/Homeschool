"""Math problem generators: one function per skill, (level, rng) -> Problem.

Every answer is computed here with exact arithmetic (fractions.Fraction); no
model ever computes an answer key. Prompts and steps are Typst markup.
"""

import random
from decimal import Decimal
from fractions import Fraction as F
from math import gcd

from hs.problem import Problem

GENERATORS = {}


def skill(fn):
    GENERATORS[fn.__name__] = fn
    return fn


# ---------- formatting helpers ----------

def ftext(f, mixed=False):
    """Plain-text answer: '3/4', '-2', '2 3/4' (mixed only when asked)."""
    f = F(f)
    if f.denominator == 1:
        return str(f.numerator)
    if mixed and abs(f) > 1:
        whole, rest = divmod(abs(f.numerator), f.denominator)
        return f"{'-' if f < 0 else ''}{whole} {rest}/{f.denominator}"
    return f"{f.numerator}/{f.denominator}"


def fm(f, mixed=False):
    """Typst math for a fraction, e.g. 3/4 or 2 3/4 (render inside $...$)."""
    f = F(f)
    if f.denominator == 1:
        return f"({f.numerator})" if f < 0 else str(f.numerator)
    if mixed and abs(f) > 1:
        whole, rest = divmod(abs(f.numerator), f.denominator)
        return f"{'-' if f < 0 else ''}{whole} thin {rest}/{f.denominator}"
    return f"{'-' if f < 0 else ''}{abs(f.numerator)}/{f.denominator}"


def dec(f):
    """Exact decimal string for a terminating fraction: F(7,4) -> '1.75'."""
    f = F(f)
    d = Decimal(f.numerator) / Decimal(f.denominator)
    s = format(d.normalize(), "f")
    return s


def neg(n):
    """Integer in Typst math, parenthesised when negative: (-3)."""
    return f"({n})" if n < 0 else str(n)


def lcm(a, b):
    return a * b // gcd(a, b)


def mixed_num(rng, dens, whole=(1, 4)):
    return rng.randint(*whole) + proper(rng, rng.choice(dens))


def proper(rng, d):
    """A proper fraction that really has denominator d (numerator coprime to d)."""
    return F(rng.choice([n for n in range(1, d) if gcd(n, d) == 1]), d)


# ---------- whole numbers ----------

@skill
def add_sub(level, rng):
    if level == 1:
        a = [rng.randint(1, 8), rng.randint(0, 8)]
        b = [rng.randint(1, 9 - a[0]), rng.randint(0, 9 - a[1])]
        x, y, op = a[0] * 10 + a[1], b[0] * 10 + b[1], "+"
    elif level == 5:
        x = rng.choice([2000, 3000, 4000, 5000, 7000, 8000]) + rng.randint(0, 9) * rng.choice([1, 10])
        y = rng.randint(1100, x - 100)
        op = "-"
    else:
        lo, hi = {2: (12, 99), 3: (102, 999), 4: (1002, 9999)}[level]
        x, y = rng.randint(lo, hi), rng.randint(lo, hi)
        op = rng.choice("+-")
        if op == "-" and y > x:
            x, y = y, x
    ans = x + y if op == "+" else x - y
    return Problem(f"${x} {op} {y} =$", str(ans), steps=[
        "Write the numbers in columns, lining up the ones place.",
        "Work right to left: " + ("carry when a column adds to 10 or more."
                                   if op == "+" else "borrow from the next column when the top digit is smaller."),
        f"${x} {op} {y} = {ans}$"])


FACT_SETS = {1: [0, 1, 2, 5, 10], 2: [3, 4], 3: [6, 7], 4: [8, 9], 5: list(range(2, 13))}


@skill
def mult_facts(level, rng):
    a, b = rng.choice(FACT_SETS[level]), rng.randint(0 if level == 1 else 2, 12)
    if rng.random() < 0.5:
        a, b = b, a
    return Problem(f"${a} times {b} =$", str(a * b), steps=[f"${a} times {b}$ means {a} groups of {b}.", f"${a} times {b} = {a * b}$"])


@skill
def div_facts(level, rng):
    d = rng.choice([x for x in FACT_SETS[level] if x > 1] or [2])
    q = rng.randint(1, 12)
    return Problem(f"${d * q} div {d} =$", str(q), steps=[
        f"Ask: what times {d} makes {d * q}?", f"${d} times {q} = {d * q}$, so ${d * q} div {d} = {q}$"])


@skill
def mult_multi(level, rng):
    da, db = {1: (2, 1), 2: (3, 1), 3: (2, 2), 4: (3, 2), 5: (4, 2)}[level]
    a = rng.randint(10 ** (da - 1) + 1, 10 ** da - 1)
    b = rng.randint(max(2, 10 ** (db - 1) + 1), 10 ** db - 1)
    steps = [f"Multiply ${a}$ by each digit of ${b}$, starting with the ones."]
    if db == 2:
        ones, tens = b % 10, b - b % 10
        steps += [f"${a} times {ones} = {a * ones}$", f"${a} times {tens} = {a * tens}$",
                  f"Add the partial products: ${a * ones} + {a * tens} = {a * b}$"]
    else:
        steps += [f"${a} times {b} = {a * b}$"]
    return Problem(f"${a} times {b} =$", str(a * b), steps=steps)


@skill
def long_div(level, rng):
    if level == 5:
        d, q = rng.randint(11, 39), rng.randint(11, 99)
    else:
        d = rng.randint(2, 9)
        lo, hi = {1: (10, 99), 2: (10, 99), 3: (100, 999), 4: (1000, 9999)}[level]
        q = rng.randint(-(-lo // d), (hi - (d - 1)) // d)  # keep the dividend in range even with a remainder
    r = 0 if level == 1 else rng.randint(0 if level > 2 else 1, d - 1)
    n = d * q + r
    ans = f"{q} R{r}" if r else str(q)
    return Problem(f"${n} div {d} =$", ans, form="remainder", hint="whole number, with remainder written like 12 R3", steps=[
        f"Divide step by step: how many {d}s fit into each part of {n}, left to right?",
        f"${d} times {q} = {d * q}$" + (f", and ${n} - {d * q} = {r}$ left over." if r else "."),
        f"Answer: {ans}"])


# ---------- fractions ----------

@skill
def frac_equiv(level, rng):
    d = rng.choice([2, 3, 4, 5, 6, 8] if level < 3 else [6, 7, 8, 9, 10, 12])
    a = proper(rng, d)
    k = 2 if level == 1 else rng.randint(2, 5 if level < 3 else 8)
    down = level == 4 or (level == 5 and rng.random() < 0.5)
    big = (a.numerator * k, a.denominator * k)
    if down:
        prompt, ans = f"${big[0]}/{big[1]} = square/{a.denominator}$", a.numerator
        how = f"Divide the bottom and top by {k}: ${big[1]} div {k} = {a.denominator}$, ${big[0]} div {k} = {a.numerator}$"
    else:
        prompt, ans = f"${a.numerator}/{a.denominator} = square/{big[1]}$", big[0]
        how = f"The bottom was multiplied by {k}, so multiply the top by {k}: ${a.numerator} times {k} = {big[0]}$"
    return Problem("Fill in the missing number: " + prompt, str(ans), steps=[how])


@skill
def frac_simplify(level, rng):
    if level == 4 or (level == 5 and rng.random() < 0.5):
        d = rng.choice([3, 4, 5, 6, 8])
        f = F(rng.randint(d + 1, 4 * d), d)
        k = rng.randint(2, 4)
        n, dd = f.numerator * k, f.denominator * k
        return Problem(f"Write as a mixed number in lowest terms: ${n}/{dd}$", ftext(f, mixed=True), form="lowest", steps=[
            f"Simplify first: divide top and bottom by {k} to get ${fm(f)}$.",
            f"${f.denominator}$ goes into ${f.numerator}$ {f.numerator // f.denominator} times with {f.numerator % f.denominator} left: ${fm(f, True)}$"])
    k = 2 if level == 1 else rng.randint(2, 4 if level == 2 else 9)
    while True:
        f = proper(rng, rng.choice([3, 4, 5, 6, 7, 8, 9, 10]))
        if f.denominator > 1:
            break
    n, dd = f.numerator * k, f.denominator * k
    return Problem(f"Simplify: ${n}/{dd}$", ftext(f), form="lowest", hint="fraction", steps=[
        f"Find the biggest number that divides both {n} and {dd}: it is {k}.",
        f"${n} div {k} = {f.numerator}$ and ${dd} div {k} = {f.denominator}$, so the answer is ${fm(f)}$"])


def _frac_op(a, b, op, mixed):
    ans = a + b if op == "+" else a - b
    return ans, f"${fm(a, mixed)} {op} {fm(b, mixed)} =$"


@skill
def frac_add_like(level, rng):
    d = rng.choice([4, 5, 6, 7, 8, 9, 10, 12])
    while True:
        if level >= 4:
            a, b = mixed_num(rng, [d], (2, 5)), mixed_num(rng, [d], (1, 2))
        else:
            a, b = proper(rng, d), proper(rng, d)
        op = "-" if level in (2, 5) else ("+" if level != 4 else rng.choice("+-"))
        if op == "-" and a < b:
            a, b = b, a
        ans = a + b if op == "+" else a - b
        if level == 1 and ans >= 1 or level == 3 and ans <= 1 or ans == 0:
            continue
        if level == 5 and (a - int(a)) >= (b - int(b)):
            continue  # level 5 needs borrowing
        break
    mixed = level >= 3
    return Problem(f"${fm(a, level >= 4)} {op} {fm(b, level >= 4)} =$", ftext(ans, mixed), form="lowest", hint="fraction or mixed number",
                   steps=["The denominators match, so " + ("add" if op == "+" else "subtract") + " the numerators and keep the denominator.",
                          f"Answer in lowest terms: ${fm(ans, mixed)}$"])


UNLIKE = {1: [(2, 4), (3, 6), (4, 8), (5, 10), (2, 6), (3, 12)], 2: [(2, 4), (3, 6), (4, 8), (2, 8), (5, 10)],
          3: [(2, 3), (3, 4), (2, 5), (3, 5), (4, 5)], 4: [(4, 6), (6, 8), (6, 9), (4, 10), (8, 12), (6, 10)]}


@skill
def frac_add_unlike(level, rng):
    while True:
        if level == 5:
            p = rng.choice(UNLIKE[3] + UNLIKE[4])
            a, b = mixed_num(rng, [p[0]], (2, 5)), mixed_num(rng, [p[1]], (1, 3))
        else:
            p = rng.choice(UNLIKE[level])
            a, b = proper(rng, p[0]), proper(rng, p[1])
        if rng.random() < 0.5:
            a, b = b, a
        op = "-" if level == 2 else rng.choice("+-") if level >= 3 else "+"
        if op == "-" and a < b:
            a, b = b, a
        ans = a + b if op == "+" else a - b
        if ans > 0:
            break
    m = level == 5
    L = lcm(a.denominator, b.denominator)
    return Problem(f"${fm(a, m)} {op} {fm(b, m)} =$", ftext(ans, mixed=m), form="lowest", hint="fraction or mixed number", steps=[
        f"Find a common denominator: the least common multiple of {a.denominator} and {b.denominator} is {L}.",
        f"Rewrite: ${fm(a, m)} = {fm_over(a, L, m)}$ and ${fm(b, m)} = {fm_over(b, L, m)}$",
        f"{'Add' if op == '+' else 'Subtract'}, then simplify: ${fm(ans, m)}$"])


def fm_over(f, L, mixed=False):
    """Show f with denominator L (keeping the whole part separate if mixed)."""
    whole = int(f) if mixed and f > 1 else 0
    rest = f - whole
    s = f"{rest.numerator * (L // rest.denominator)}/{L}"
    return f"{whole} thin {s}" if whole else s


@skill
def frac_mult(level, rng):
    if level == 1:
        a, b = F(rng.randint(2, 12)), F(1, rng.randint(2, 6))
    elif level == 2:
        a, b = F(rng.randint(2, 12)), proper(rng, rng.randint(3, 8))
    elif level == 3:
        a, b = proper(rng, rng.randint(2, 6)), proper(rng, rng.randint(3, 9))
    elif level == 4:  # a top and an opposite bottom share a factor, so you can cancel first
        while True:
            a, b = proper(rng, rng.randint(3, 10)), proper(rng, rng.randint(3, 12))
            if gcd(a.numerator, b.denominator) > 1 or gcd(b.numerator, a.denominator) > 1:
                break
    else:
        a, b = mixed_num(rng, [2, 3, 4]), mixed_num(rng, [2, 3, 4, 5], (1, 2))
    ans = a * b
    m = level == 5
    return Problem(f"${fm(a, m)} times {fm(b, m)} =$", ftext(ans, mixed=ans > 1), form="lowest", hint="fraction or mixed number", steps=(
        [f"Change mixed numbers to improper fractions: ${fm(a)} times {fm(b)}$"] if m else []) + [
        "Multiply the tops together and the bottoms together.",
        f"${a.numerator} times {b.numerator} = {a.numerator * b.numerator}$ and ${a.denominator} times {b.denominator} = {a.denominator * b.denominator}$",
        f"Simplify: ${fm(ans, ans > 1)}$"])


@skill
def frac_div(level, rng):
    if level == 1:
        a, b = F(1, rng.randint(2, 6)), F(rng.randint(2, 5))
    elif level == 2:
        a, b = F(rng.randint(2, 9)), F(1, rng.randint(2, 6))
    elif level == 3:
        a, b = proper(rng, rng.randint(2, 9)), proper(rng, rng.randint(2, 9))
    elif level == 4:
        a, b = mixed_num(rng, [2, 3, 4]), proper(rng, rng.randint(2, 6))
    else:
        a, b = mixed_num(rng, [2, 3, 4]), mixed_num(rng, [2, 3, 4], (1, 2))
    ans = a / b
    m = level >= 4
    return Problem(f"${fm(a, m)} div {fm(b, m)} =$", ftext(ans, mixed=ans > 1), form="lowest", hint="fraction, mixed number, or whole number", steps=[
        "Keep the first number, change $div$ to $times$, and flip the second number.",
        f"${fm(a)} times {fm(1 / b)} = {fm(ans)}$",
        f"In lowest terms: ${fm(ans, ans > 1)}$"])


# ---------- decimals ----------

def rdec(rng, lo, hi, places):
    """A decimal with exactly `places` digits after the point (last digit non-zero)."""
    while True:
        n = rng.randint(round(lo * 10 ** places), round(hi * 10 ** places))
        if n % 10:
            return F(n, 10 ** places)


@skill
def dec_add_sub(level, rng):
    if level == 1:
        a, b, op = rdec(rng, 0.1, 9.9, 1), rdec(rng, 0.1, 9.9, 1), "+"
    elif level == 2:
        a, b, op = rdec(rng, 0.01, 9.99, 2), rdec(rng, 0.01, 9.99, 2), "+"
    elif level == 3:
        a, b, op = rdec(rng, 1, 20, 2), rdec(rng, 0.01, 9.99, 2), "-"
    elif level == 4:
        a, b, op = rdec(rng, 1, 30, 1), rdec(rng, 0.01, 20, 2), rng.choice("+-")
    else:
        a, b, op = F(rng.randint(2, 50)), rdec(rng, 0.01, 1.99, 2), "-"
    if op == "-" and b > a:
        a, b = b, a
    ans = a + b if op == "+" else a - b
    return Problem(f"${dec(a)} {op} {dec(b)} =$", dec(ans), hint="decimal number", steps=[
        "Line up the decimal points. Fill empty places with zeros.",
        f"${dec(a)} {op} {dec(b)} = {dec(ans)}$"])


@skill
def dec_mult(level, rng):
    a, b = {1: lambda: (rdec(rng, 0.1, 0.9, 1), F(rng.randint(2, 9))),
            2: lambda: (rdec(rng, 0.1, 0.9, 1), rdec(rng, 0.1, 0.9, 1)),
            3: lambda: (rdec(rng, 0.01, 9.99, 2), F(rng.randint(2, 9))),
            4: lambda: (rdec(rng, 0.11, 9.99, 2), rdec(rng, 0.2, 9.9, 1)),
            5: lambda: (rdec(rng, 1.1, 30, 1), rdec(rng, 1.1, 30, 1))}[level]()
    ans = a * b
    places = len(dec(a).partition(".")[2]) + len(dec(b).partition(".")[2])
    return Problem(f"${dec(a)} times {dec(b)} =$", dec(ans), hint="decimal number", steps=[
        "Multiply as if there were no decimal points.",
        f"Count the digits after the decimal points in both numbers: {places}. Put that many in the answer.",
        f"${dec(a)} times {dec(b)} = {dec(ans)}$"])


@skill
def dec_div(level, rng):
    if level == 1:
        b, q = F(rng.randint(2, 9)), rdec(rng, 0.1, 9.9, 1)
    elif level == 2:
        b, q = rdec(rng, 0.1, 0.9, 1), F(rng.randint(2, 60))
    elif level == 3:
        b, q = rdec(rng, 0.2, 0.9, 1), rdec(rng, 1.1, 9.9, 1)
    elif level == 4:
        b, q = rdec(rng, 0.02, 0.99, 2), F(rng.randint(2, 99))
    else:
        b, q = F(rng.randint(11, 40)), rdec(rng, 1.1, 9.9, 1)
    a = b * q
    shift = len(dec(b).partition(".")[2])
    return Problem(f"${dec(a)} div {dec(b)} =$", dec(q), hint="decimal or whole number", steps=(
        [f"Move both decimal points {shift} place{'s' if shift > 1 else ''} right: ${dec(a * 10 ** shift)} div {dec(b * 10 ** shift)}$"] if shift else []) + [
        "Divide, keeping the decimal point straight above.", f"${dec(a)} div {dec(b)} = {dec(q)}$"])


# ---------- expressions ----------

@skill
def order_ops(level, rng):
    r = lambda lo=2, hi=9: rng.randint(lo, hi)
    if level == 1:
        a, b, c = r(1, 20), r(), r()
        expr, val, step = f"{a} + {b} times {c}", a + b * c, f"Multiply first: ${b} times {c} = {b * c}$"
    elif level == 2:
        a, b, c = r(), r(), r()
        expr, val, step = f"({a} + {b}) times {c}", (a + b) * c, f"Parentheses first: ${a} + {b} = {a + b}$"
    elif level == 3:
        a, b, d, q = r(), r(), r(2, 6), r(2, 6)
        c = d * q
        while a * b - q < 0:
            a += 1
        expr, val, step = f"{a} times {b} - {c} div {d}", a * b - q, f"Multiply and divide left to right first: ${a} times {b} = {a * b}$, ${c} div {d} = {q}$"
    elif level == 4:
        a, b, c = r(2, 5), r(), r()
        expr, val, step = f"{a}^2 + {b} times {c}", a * a + b * c, f"Exponents first: ${a}^2 = {a * a}$"
    else:
        a, b, c, d = r(), r(1, 5), r(2, 5), r(2, 12)
        expr, val, step = f"{d} + [{a} times ({b} + {c})]", d + a * (b + c), f"Innermost parentheses first: ${b} + {c} = {b + c}$"
    return Problem(f"${expr} =$", str(val), steps=[step, f"${expr} = {val}$"])


@skill
def exponents(level, rng):
    if level == 1:
        b, e = rng.randint(2, 12), 2
    elif level == 2:
        b, e = rng.randint(2, 6), 3
    elif level == 3:
        b, e = 10, rng.randint(2, 6)
    elif level == 4:
        b, e = rng.randint(2, 5), rng.randint(2, 3)
        c = rng.randint(2, 9)
        val = b ** e - c if b ** e > c else b ** e + c
        sign = "-" if b ** e > c else "+"
        return Problem(f"${b}^{e} {sign} {c} =$", str(val), steps=[f"Exponent first: ${b}^{e} = {b ** e}$", f"Then ${b ** e} {sign} {c} = {val}$"])
    else:
        b, e = rng.randint(2, 5), rng.randint(2, 3)
        if rng.random() < 0.5:
            return Problem(f"$(-{b})^{e} =$", str((-b) ** e), steps=[
                f"The negative is inside the parentheses, so it is multiplied {e} times.", f"$(-{b})^{e} = {(-b) ** e}$"])
        return Problem(f"$-{b}^{e} =$", str(-(b ** e)), steps=[
            f"No parentheses: the exponent applies to {b} only, then take the negative.", f"$-{b}^{e} = -{b ** e}$"])
    return Problem(f"${b}^{e} =$", str(b ** e), steps=[f"${b}^{e}$ means {e} copies of {b} multiplied together.", f"${b}^{e} = {b ** e}$"])


# ---------- ratios and percents ----------

@skill
def ratio(level, rng):
    a, b = rng.randint(1, 9), rng.randint(2, 9)
    while gcd(a, b) != 1:
        b += 1
    k = rng.randint(2, 9)
    if level == 1:
        return Problem(f"Fill in the missing number: ${a}:{b} = {a * k}:square$", str(b * k),
                       steps=[f"${a}$ was multiplied by {k}, so multiply ${b}$ by {k}: ${b * k}$"])
    if level == 2:
        return Problem(f"Fill in the missing number: ${a * k}:{b * k} = square:{b}$", str(a),
                       steps=[f"${b * k}$ was divided by {k}, so divide ${a * k}$ by {k}: ${a}$"])
    if level == 3:
        return Problem(f"Solve for $x$: $x/{b * k} = {a}/{b}$", str(a * k), hint="number (the value of x)",
                       steps=[f"${b} times {k} = {b * k}$, so $x = {a} times {k} = {a * k}$"])
    if level == 4:
        n, price = rng.randint(3, 9), rng.randint(2, 12)
        return Problem(f"{n} notebooks cost \\${n * price}. How many dollars does 1 notebook cost?", str(price),
                       steps=[f"Divide the total by the number of notebooks: ${n * price} div {n} = {price}$"])
    # a/b isn't in lowest terms and c isn't a multiple of b, e.g. 6/4 = x/10
    p, q = rng.randint(1, 9), rng.randint(2, 6)
    while gcd(p, q) != 1:
        p += 1
    s, m = rng.choice([2, 3]), rng.randint(2, 7)
    while m % s == 0:
        m += 1
    a, b, c, x = p * s, q * s, q * m, p * m
    return Problem(f"Solve for $x$: ${a}/{b} = x/{c}$", str(x), hint="number (the value of x)",
                   steps=[f"Cross-multiply: ${b} x = {a} times {c} = {a * c}$", f"$x = {a * c} div {b} = {x}$"])


@skill
def percent(level, rng):
    if level == 1:
        p = rng.choice([10, 25, 50])
        n = rng.randint(2, 20) * {10: 10, 25: 4, 50: 2}[p]
        return Problem(f"What is {p}% of {n}?", dec(F(p * n, 100)), steps=[f"{p}% is ${fm(F(p, 100))}$, so ${n} times {fm(F(p, 100))} = {dec(F(p * n, 100))}$"])
    if level == 2:
        p, n = rng.choice(range(5, 100, 5)), rng.randint(2, 30) * 20
        return Problem(f"What is {p}% of {n}?", dec(F(p * n, 100)), steps=[f"Change {p}% to {dec(F(p, 100))}.", f"${dec(F(p, 100))} times {n} = {dec(F(p * n, 100))}$"])
    if level == 3:
        whole = rng.choice([20, 25, 40, 50, 80, 200])
        part = whole * rng.choice(range(5, 100, 5)) // 100
        while F(part * 100, whole).denominator != 1 or part == 0:
            part += 1
        return Problem(f"What percent of {whole} is {part}?", dec(F(part * 100, whole)), hint="percent (number only)", steps=[
            f"Divide the part by the whole: ${part} div {whole} = {dec(F(part, whole))}$", f"Times 100: {dec(F(part * 100, whole))}%"])
    if level == 4:
        p, whole = rng.choice([10, 20, 25, 40, 50]), rng.randint(2, 30) * 10
        part = F(p * whole, 100)
        return Problem(f"{dec(part)} is {p}% of what number?", str(whole), steps=[
            f"{p}% of the number is {dec(part)}, so the number is ${dec(part)} div {dec(F(p, 100))}$", f"$= {whole}$"])
    p, n = rng.choice([10, 20, 25, 30, 50]), rng.randint(2, 20) * 20
    up = rng.random() < 0.5
    new = n + F(p * n, 100) * (1 if up else -1)
    word = "increased" if up else "decreased"
    return Problem(f"A price of \\${n} is {word} by {p}%. What is the new price in dollars?", dec(new), steps=[
        f"{p}% of {n} is {dec(F(p * n, 100))}.", f"${n} {'+' if up else '-'} {dec(F(p * n, 100))} = {dec(new)}$"])


# ---------- integers ----------

@skill
def int_add_sub(level, rng):
    big = 50 if level == 5 else 12
    r = lambda: rng.randint(1, big)
    if level == 1:
        a, b, op = r(), -r(), "+"
    elif level == 2:
        a, b, op = r() * rng.choice([1, -1]), r() * rng.choice([1, -1]), "-"
    elif level == 4:
        a, b, c = r() * rng.choice([1, -1]), r(), r() * rng.choice([1, -1])
        val = a - b + c
        return Problem(f"${neg(a)} - {b} + {neg(c)} =$", str(val), steps=["Work left to right.", f"${neg(a)} - {b} = {a - b}$", f"${neg(a - b)} + {neg(c)} = {val}$"])
    else:
        a, b, op = r() * rng.choice([1, -1]), r() * rng.choice([1, -1]), rng.choice("+-")
    val = a + b if op == "+" else a - b
    steps = ["Subtracting a number is the same as adding its opposite." if op == "-" else "Adding a negative moves left on the number line.",
             f"${neg(a)} {op} {neg(b)} = {val}$"]
    return Problem(f"${neg(a)} {op} {neg(b)} =$", str(val), hint="integer (may be negative)", steps=steps)


@skill
def int_mult_div(level, rng):
    s = lambda: rng.choice([1, -1])
    a, b = rng.randint(2, 12) * s(), rng.randint(2, 12) * s()
    if a > 0 and b > 0:  # this skill is about negatives
        a = -a
    if level == 1 or (level == 3 and rng.random() < 0.5):
        return Problem(f"${neg(a)} times {neg(b)} =$", str(a * b), hint="integer (may be negative)",
                       steps=["Same signs give a positive, different signs give a negative.", f"${neg(a)} times {neg(b)} = {a * b}$"])
    if level in (2, 3):
        return Problem(f"${neg(a * b)} div {neg(b)} =$", str(a), hint="integer (may be negative)",
                       steps=["Same signs give a positive, different signs give a negative.", f"${neg(a * b)} div {neg(b)} = {a}$"])
    if level == 4:
        c = rng.randint(2, 5) * s()
        return Problem(f"${neg(a)} times {neg(b)} times {neg(c)} =$", str(a * b * c), hint="integer (may be negative)",
                       steps=["Count the negatives: an even count gives a positive, odd gives a negative.", f"$= {a * b * c}$"])
    c = rng.randint(1, 20) * s()
    return Problem(f"${neg(a)} times {neg(b)} + {neg(c)} =$", str(a * b + c), hint="integer (may be negative)",
                   steps=[f"Multiply first: ${neg(a)} times {neg(b)} = {a * b}$", f"${neg(a * b)} + {neg(c)} = {a * b + c}$"])


# ---------- equations ----------

def eq_problem(lhs, rhs, x, steps):
    return Problem(f"Solve for $x$: ${lhs} = {rhs}$", str(x), hint="number (the value of x)", steps=steps + [f"$x = {x}$"])


def term(coef, var="x"):
    if coef == 1:
        return var
    if coef == -1:
        return f"-{var}"
    return f"{coef}{var}"


def plus(n):
    return f"+ {n}" if n >= 0 else f"- {-n}"


@skill
def one_step_eq(level, rng):
    x = rng.randint(2, 20) * (rng.choice([1, -1]) if level == 5 else 1)
    a = rng.randint(2, 12)
    if level == 5:
        level = rng.randint(1, 4)
    if level == 1:
        return eq_problem(f"x + {a}", x + a, x, [f"Subtract {a} from both sides."])
    if level == 2:
        return eq_problem(f"x - {a}", x - a, x, [f"Add {a} to both sides."])
    if level == 3:
        return eq_problem(f"{a}x", a * x, x, [f"Divide both sides by {a}."])
    return eq_problem(f"x/{a}", x, x * a, [f"Multiply both sides by {a}."])


@skill
def two_step_eq(level, rng):
    x = rng.randint(1, 12) * (-1 if level == 5 else 1)
    a, b = rng.randint(2, 9), rng.randint(1, 20)
    if level == 2:
        b = -b
    if level == 3:
        a = -a
    if level == 4:
        c = x + b
        x = x * a
        return eq_problem(f"x/{a} {plus(b)}", c, x, [f"Subtract {b} from both sides: $x/{a} = {c - b}$", f"Multiply both sides by {a}."])
    c = a * x + b
    return eq_problem(f"{term(a)} {plus(b)}", c, x, [f"{'Subtract' if b > 0 else 'Add'} {abs(b)} {'from' if b > 0 else 'to'} both sides: ${term(a)} = {c - b}$",
                                                  f"Divide both sides by {neg(a)}."])


@skill
def multi_step_eq(level, rng):
    x = rng.randint(-9, 12) if level >= 3 else rng.randint(1, 12)
    a = rng.randint(3, 9)
    c = rng.randint(1, a - 1)
    if level == 3:
        c = -c
    if level <= 3:
        d = 0 if level == 1 else rng.randint(1, 20)
        b = c * x + d - a * x
        rhs = f"{term(c)} {plus(d)}" if d else term(c)
        return eq_problem(f"{term(a)} {plus(b)}" if b else term(a), rhs, x, [
            f"Get the $x$ terms on one side: subtract ${term(c)}$ from both sides.", f"${term(a - c)} {plus(b)} = {d}$" if b else f"${term(a - c)} = {d}$",
            f"Then solve the two-step equation."])
    k, m = rng.randint(2, 5), rng.randint(1, 9)
    lhs_val = k * (x + m)
    if level == 4:
        d = lhs_val - c * x
        return eq_problem(f"{k}(x + {m})", f"{term(c)} {plus(d)}", x, [
            f"Distribute: ${k}x + {k * m} = {term(c)} {plus(d)}$", f"Subtract ${term(c)}$ and ${k * m}$ from both sides: ${term(k - c)} = {d - k * m}$"])
    j = rng.randint(1, k - 1) if k > 2 else 1
    n = F(lhs_val - j * x, j)
    while n.denominator != 1:
        j = 1
        n = F(lhs_val - j * x, j)
    n = int(n)
    return eq_problem(f"{k}(x + {m})", f"{j}(x {plus(n)})" if j > 1 else f"x {plus(n)}", x, [
        f"Distribute both sides: ${k}x + {k * m} = {j}x {plus(j * n)}$", f"Collect: ${term(k - j)} = {j * n - k * m}$"])


TRIPLES = {1: [(3, 4, 5)], 3: [(5, 12, 13), (8, 15, 17), (7, 24, 25), (20, 21, 29), (9, 40, 41)]}


@skill
def pythagorean(level, rng):
    if level in (1, 2):
        t, k = (3, 4, 5), rng.randint(1, 5)
    elif level == 3:
        t, k = rng.choice(TRIPLES[3]), 1
    else:
        t, k = rng.choice([(3, 4, 5)] + TRIPLES[3]), rng.randint(2, 4)
    a, b, c = (n * k for n in t)
    if rng.random() < 0.5:
        a, b = b, a
    leg = level == 2 or (level >= 3 and rng.random() < 0.5)
    if leg:
        return Problem(f"A right triangle has hypotenuse {c} and one leg {a}. How long is the other leg?", str(b), steps=[
            "$a^2 + b^2 = c^2$, so $b^2 = c^2 - a^2$", f"$b^2 = {c * c} - {a * a} = {b * b}$", f"$b = sqrt({b * b}) = {b}$"])
    return Problem(f"A right triangle has legs {a} and {b}. How long is the hypotenuse?", str(c), steps=[
        "$a^2 + b^2 = c^2$", f"${a * a} + {b * b} = {c * c}$", f"$c = sqrt({c * c}) = {c}$"])


@skill
def slope(level, rng):
    if level == 5:
        a, b = rng.randint(1, 6), rng.randint(2, 6)
        c = a * b * rng.randint(1, 3)
        m = F(-a, b)
        return Problem(f"What is the slope of the line ${a}x + {b}y = {c}$?", ftext(m), form="lowest", hint="fraction or integer (may be negative)", steps=[
            f"Solve for $y$: ${b}y = {-a}x + {c}$", f"$y = {fm(m)} x + {fm(F(c, b))}$", f"The slope is the number in front of $x$: ${fm(m)}$"])
    run = 1 if level <= 2 else rng.randint(2, 6)
    rise = rng.randint(1, 9) * (-1 if level in (2, 4) else 1)
    if level >= 3:
        while gcd(abs(rise), run) == run:
            rise += -1 if rise < 0 else 1
    k = rng.randint(1, 3)
    x1, y1 = rng.randint(-5, 5), rng.randint(-5, 5)
    x2, y2 = x1 + run * k, y1 + rise * k
    m = F(rise, run)
    return Problem(f"Find the slope of the line through $({x1}, {y1})$ and $({x2}, {y2})$.", ftext(m), form="lowest",
                   hint="fraction or integer (may be negative)", steps=[
                       "Slope = (change in $y$) / (change in $x$)", f"$({y2} - {neg(y1)}) / ({x2} - {neg(x1)}) = {y2 - y1}/{x2 - x1}$",
                       f"In lowest terms: ${fm(m)}$"])


def generate(skill_id, level, seed):
    """Deterministic: the same (skill, level, seed) always gives the same problem."""
    return GENERATORS[skill_id](level, random.Random(seed))
