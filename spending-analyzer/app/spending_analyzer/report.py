"""Export: CSV of transactions and a self-contained HTML report (no external resources)."""
from __future__ import annotations

import csv
import html
from datetime import datetime

from .insights import money


def export_csv(path: str, transactions):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Merchant", "Category", "Amount", "Direction", "Excluded", "Source file"])
        for t in sorted(transactions, key=lambda t: t.date):
            w.writerow([t.date.isoformat(), t.description, t.merchant, t.category, f"{t.amount:.2f}",
                        "in" if t.is_credit else "out", "yes" if t.excluded else "", t.source_file])


def export_html(path: str, a, palette):
    e = html.escape
    max_cat = max((v for _, v in a.by_category), default=1) or 1
    max_mon = max((v for _, v in a.by_month), default=1) or 1

    cat_rows = "".join(
        f'<tr><td>{e(c)}</td><td class="bar"><span style="width:{v / max_cat * 100:.1f}%;background:{palette(c)}"></span></td>'
        f'<td class="num">{money(v)}</td><td class="num">{money(v / a.months)}</td>'
        f'<td class="num">{v / a.total_spent:.1%}</td></tr>'
        for c, v in a.by_category)
    mon_rows = "".join(
        f'<tr><td>{e(m)}</td><td class="bar"><span style="width:{v / max_mon * 100:.1f}%"></span></td>'
        f'<td class="num">{money(v)}</td></tr>' for m, v in a.by_month)
    sugg = ""
    for s in a.suggestions:
        items = "".join(f"<li>{e(i)}</li>" for i in s.items)
        save = f'<div class="save">Potential savings: ~{money(s.monthly_savings)}/month</div>' if s.monthly_savings >= 1 else ""
        sugg += (f'<div class="card p{s.priority}"><h3>{e(s.title)}</h3><p>{e(s.detail)}</p>'
                 f'{"<ul>" + items + "</ul>" if items else ""}{save}</div>')
    rec_rows = "".join(
        f"<tr><td>{e(r.merchant)}</td><td>{e(r.category)}</td><td>{e(r.frequency)}</td>"
        f'<td class="num">{money(r.typical_amount)}</td><td class="num">{money(r.monthly_cost * 12)}</td>'
        f"<td>{r.last_date}</td></tr>" for r in a.recurring)
    merch_rows = "".join(
        f'<tr><td>{e(m)}</td><td class="num">{n}</td><td class="num">{money(v)}</td></tr>'
        for m, v, n in a.top_merchants[:15])

    period = f"{a.first_date} to {a.last_date}" if a.first_date else "n/a"
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Spending Report</title>
<style>
:root{{--bg:#f6f7f9;--fg:#1d2330;--muted:#5d6676;--card:#fff;--line:#e3e6eb;--accent:#2f6fde}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171c;--fg:#e6e9ef;--muted:#9aa3b2;--card:#1d2128;--line:#2c323b;--accent:#6b9cff}}}}
body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:24px}}
main{{max-width:960px;margin:auto}} h1{{margin:0 0 4px}} .muted{{color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}}
.kpi,.card,table{{background:var(--card);border:1px solid var(--line);border-radius:10px}}
.kpi{{padding:14px}} .kpi b{{display:block;font-size:22px}}
.card{{padding:14px 18px;margin:12px 0;border-left:4px solid var(--muted)}} .card.p1{{border-left-color:#d9534f}}
.card.p2{{border-left-color:#e8a33d}} .card h3{{margin:0 0 6px}} .save{{font-weight:600;color:#2e9d5b}}
table{{width:100%;border-collapse:collapse;margin:12px 0;overflow:hidden}} td,th{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} .bar{{width:40%}}
.bar span{{display:block;height:12px;border-radius:3px;background:var(--accent)}}
h2{{margin-top:32px}}
</style></head><body><main>
<h1>Spending Report</h1><div class="muted">{e(period)} &middot; generated {datetime.now():%Y-%m-%d %H:%M} &middot; created offline</div>
<div class="kpis">
<div class="kpi"><span class="muted">Total spent</span><b>{money(a.total_spent)}</b></div>
<div class="kpi"><span class="muted">Average per month</span><b>{money(a.total_spent / a.months)}</b></div>
<div class="kpi"><span class="muted">Money in</span><b>{money(a.total_in)}</b></div>
<div class="kpi"><span class="muted">Possible savings</span><b>{money(a.potential_monthly_savings)}/mo</b></div>
</div>
<h2>What you could cut back on</h2>{sugg or "<p>No suggestions.</p>"}
<h2>Spending by category</h2><table><tr><th>Category</th><th></th><th class="num">Total</th><th class="num">Per month</th><th class="num">Share</th></tr>{cat_rows}</table>
<h2>Spending by month</h2><table>{mon_rows}</table>
<h2>Recurring charges</h2><table><tr><th>Merchant</th><th>Category</th><th>Frequency</th><th class="num">Amount</th><th class="num">Per year</th><th>Last</th></tr>{rec_rows}</table>
<h2>Top merchants</h2><table><tr><th>Merchant</th><th class="num">Transactions</th><th class="num">Total</th></tr>{merch_rows}</table>
</main></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
