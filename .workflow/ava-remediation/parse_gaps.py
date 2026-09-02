import collections
rows = []
for line in open('.workflow/ava-remediation/gate-baseline-20260901.log', encoding='utf-8', errors='replace'):
    parts = line.split()
    if len(parts) >= 4 and parts[0].endswith('.py') and parts[3].endswith('%'):
        try:
            s, m = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        rows.append((parts[0], s, m))
total_s = sum(r[1] for r in rows); total_m = sum(r[2] for r in rows)
print(f'files={len(rows)} stmts={total_s} miss={total_m}')
sep_class = '[' + chr(92) + '/]'
agg = collections.Counter()
for name, s, miss in rows:
    top = name.split(sep_class[1])[0].split('/')[0]
    agg[top] += miss
print('--- top-level module missing ---')
for mod, miss in agg.most_common(12):
    print(f'{mod:35s} {miss}')
print('--- worst single files (miss>=8) ---')
for name, s, miss in sorted(rows, key=lambda r: -r[2]):
    if miss >= 8:
        print(f'{name:55s} miss={miss:4d} stmts={s}')
