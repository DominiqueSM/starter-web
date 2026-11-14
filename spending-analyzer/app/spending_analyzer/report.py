"""Export: CSV of transactions and a self-contained HTML report (no external resources)."""
from __future__ import annotations

import csv
import html
import os
from datetime import datetime

from .insights import money


def export_csv(path: str, transactions):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Company", "Category", "Category source", "Amount", "Direction",
                    "Counted as spending", "Excluded", "Duplicate", "Note", "Folder", "Account", "Source file"])
        for t in sorted(transactions, key=lambda t: t.date):
            w.writerow([t.date.isoformat(), t.description, t.merchant, t.category, t.category_source,
                        f"{t.amount:.2f}", "in" if t.is_credit else "out",
                        "yes" if t.is_spending and t.category not in ("Income", "Transfers & Payments") else "",
                        "yes" if t.excluded else "", "yes" if t.duplicate else "", t.note, t.group, t.account,
                        t.source_file])


def export_html(path: str, a, palette, scope=None, groups=None, files=None):
    e = html.escape
    max_cat = max((v for _, v in a.by_category), default=1) or 1
    max_mon = max((v for _, v in a.by_month), default=1) or 1

    cat_rows = "".join(
        f'<tr><td>{e(c)}</td><td class="bar"><span style="width:{v / max_cat * 100:.1f}%;background:{palette(c)}"></span></td>'
        f'<td class="num">{money(v / a.months)}</td><td class="num">{money(v)}</td>'
        f'<td class="num">{v / a.total_spent:.0%}</td></tr>' for c, v in a.by_category)
    mon_rows = "".join(
        f'<tr><td>{e(m)}</td><td class="bar"><span style="width:{v / max_mon * 100:.1f}%"></span></td>'
        f'<td class="num">{money(v)}</td></tr>' for m, v in a.by_month)
    sugg = ""
    for s in a.suggestions:
        items = "".join(f"<li>{e(i)}</li>" for i in s.items)
        save = (f'<span class="pill good">save ~{money(s.monthly_savings)}/mo</span>'
                if s.monthly_savings >= 1 else "")
        sugg += (f'<div class="card {s.kind}"><div class="head"><h3>{e(s.title)}</h3>{save}'
                 f'<span class="pill">{e(s.confidence)} confidence</span></div><p>{e(s.detail)}</p>'
                 f'{"<ul>" + items + "</ul>" if items else ""}</div>')
    rec_rows = "".join(
        f"<tr><td>{e(r.merchant)}</td><td>{e(r.kind)}</td><td>{e(r.category)}</td><td>{e(r.frequency)}</td>"
        f'<td class="num">{money(r.typical_amount)}</td><td class="num">{money(r.monthly_cost * 12)}</td>'
        f"<td>{r.last_date}</td><td>{e(', '.join(r.aliases))}</td></tr>" for r in a.recurring)
    merch_rows = "".join(
        f'<tr><td>{e(m)}</td><td class="num">{n}</td><td class="num">{money(v)}</td></tr>'
        for m, v, n in a.top_merchants[:15])
    group_html = ""
    if groups:
        group_html = ("<h2>By folder</h2><table><tr><th>Folder</th><th class=num>Transactions</th>"
                      "<th class=num>Spent</th><th class=num>Per month</th><th class=num>Money in</th>"
                      "<th class=num>Fees &amp; interest</th><th>Biggest category</th></tr>" + "".join(
                          f"<tr{' class=total' if i == 0 else ''}><td>{e(g['name'])}</td>"
                          f"<td class=num>{g['transactions']}</td><td class=num>{money(g['spent'])}</td>"
                          f"<td class=num>{money(g['per_month'])}</td><td class=num>{money(g['money_in'])}</td>"
                          f"<td class=num>{money(g['fees'])}</td><td>{e(g['top_category'])}</td></tr>"
                          for i, g in enumerate(groups)) + "</table>")
    files_html = ""
    if files:
        label = {"reconciled": "Adds up", "balance-verified": "Balance checked", "mismatch": "Doesn't add up",
                 "unverified": "Not checkable"}
        files_html = ("<h2>Statements read</h2><table><tr><th>File</th><th>Account</th><th>Check</th>"
                      "<th class=num>Rows</th><th>Notes</th></tr>" + "".join(
                          f"<tr><td>{e(os.path.basename(r.path))}</td><td>{e(r.info.account_key)}</td>"
                          f"<td>{e(label.get(r.info.recon_status, '') if r.status == 'ok' else r.status)}</td>"
                          f"<td class=num>{len(r.transactions)}</td>"
                          f"<td>{e(r.info.recon_detail if r.info.recon_status == 'mismatch' else r.note)}</td></tr>"
                          for r in files) + "</table>")

    period = f"{a.first_date:%b %d, %Y} to {a.last_date:%b %d, %Y}" if a.first_date else "n/a"
    if scope:
        period = f"Folder: {scope} &middot; " + period
    income = f"{money(a.income / a.months)}/mo" if a.income else "&ndash;"
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Spending Report</title>
<style>
:root{{--bg:#f3f5f9;--fg:#111827;--muted:#6b7280;--card:#fff;--line:#e3e7ee;--accent:#4f46e5;--good:#059669;--warn:#d97706;--info:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f141c;--fg:#e6e9ef;--muted:#9aa3b2;--card:#171d27;--line:#273041;--accent:#818cf8;--good:#34d399;--warn:#fbbf24;--info:#60a5fa}}}}
*{{box-sizing:border-box}}
body{{font:15px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:32px 16px}}
main{{max-width:980px;margin:auto}} h1{{margin:0 0 4px;font-size:28px}} .muted{{color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:22px 0}}
.kpi,.card,table{{background:var(--card);border:1px solid var(--line);border-radius:12px}}
.kpi{{padding:16px}} .kpi span{{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:600}}
.kpi b{{display:block;font-size:24px;margin-top:4px}} .kpi b.good{{color:var(--good)}}
.card{{padding:16px 20px;margin:12px 0;border-left:4px solid var(--info)}} .card.warn{{border-left-color:var(--warn)}}
.card.save{{border-left-color:var(--good)}} .card h3{{margin:0;font-size:17px;flex:1}}
.head{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.pill{{font-size:12px;font-weight:600;padding:2px 10px;border-radius:99px;background:var(--bg);color:var(--muted)}}
.pill.good{{color:var(--good)}} .card p{{margin:8px 0 0}} ul{{margin:8px 0 0;padding-left:20px}}
table{{width:100%;border-collapse:separate;border-spacing:0;margin:12px 0;overflow:hidden;display:block;overflow-x:auto}}
td,th{{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left}} th{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
tr:last-child td{{border-bottom:0}} tr.total td{{font-weight:700}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} .bar{{width:40%;min-width:120px}}
.bar span{{display:block;height:10px;border-radius:99px;background:var(--accent)}}
h2{{margin-top:36px;font-size:20px}}
</style></head><body><main>
<h1>Spending report</h1><div class="muted">{period} &middot; generated {datetime.now():%Y-%m-%d %H:%M} &middot; created offline</div>
<div class="kpis">
<div class="kpi"><span>Total spent</span><b>{money(a.total_spent)}</b></div>
<div class="kpi"><span>Per month</span><b>{money(a.total_spent / a.months)}</b></div>
<div class="kpi"><span>Income</span><b>{income}</b></div>
<div class="kpi"><span>Could save</span><b class="good">{money(a.potential_monthly_savings)}/mo</b></div>
</div>
<h2>What you could cut back on</h2>{sugg or "<p>No suggestions.</p>"}
<h2>Spending by category</h2><table><tr><th>Category</th><th></th><th class="num">Per month</th><th class="num">Total</th><th class="num">Share</th></tr>{cat_rows}</table>
<h2>Spending by month</h2><table>{mon_rows}</table>
<h2>Recurring charges</h2><table><tr><th>Company</th><th>Type</th><th>Category</th><th>Frequency</th><th class="num">Amount</th><th class="num">Per year</th><th>Last</th><th>Also listed as</th></tr>{rec_rows}</table>
<h2>Top merchants</h2><table><tr><th>Company</th><th class="num">Transactions</th><th class="num">Total</th></tr>{merch_rows}</table>
{group_html}{files_html}
</main></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
