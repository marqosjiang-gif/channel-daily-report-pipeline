#!/usr/bin/env python3
"""Build the channel daily mobile dashboard HTML and PNG from backend export data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd


def money(v: float) -> str:
    return "¥" + f"{float(v):,.2f}"


def intfmt(v: float) -> str:
    return f"{int(round(float(v))):,}"


def load_store_counts(path: Path) -> dict[str, int]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("results", data.get("rows", data if isinstance(data, list) else []))
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    out: dict[str, int] = {}
    for row in rows:
        d = str(row.get("date") or row.get("日期") or "").strip()
        c = str(row.get("store_count") or row.get("售卖门店数") or "").strip()
        if d and c:
            out[d] = int(float(c.replace(",", "")))
    return out


def read_backend_excel(path: Path, store_counts: dict[str, int]) -> tuple[list[dict], dict]:
    raw = pd.read_excel(path, header=None)
    header_idx = None
    for i in range(min(30, len(raw))):
        vals = [str(x).strip() for x in raw.iloc[i].tolist()]
        if {"日期", "渠道", "售卖门店数"}.issubset(set(vals)):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("未找到包含 日期/渠道/售卖门店数 的表头行")

    headers = [str(x).strip() if pd.notna(x) else f"unnamed_{i}" for i, x in enumerate(raw.iloc[header_idx].tolist())]
    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = headers

    total_rows = df[df["日期"].astype(str).str.strip() == "总计："]
    if total_rows.empty:
        raise ValueError("未找到最终 总计： 行")
    total = total_rows.iloc[-1]
    detail = df[df["日期"].astype(str).str.strip() != "总计："].copy()
    detail["date"] = pd.to_datetime(detail["日期"]).dt.strftime("%Y-%m-%d")

    for col in ["订单数", "间夜数", "销售金额", "结算金额", "留存金额"]:
        detail[col] = pd.to_numeric(detail[col], errors="coerce").fillna(0)

    agg = detail.groupby("date", as_index=False).agg(
        {"订单数": "sum", "间夜数": "sum", "销售金额": "sum", "结算金额": "sum", "留存金额": "sum"}
    )
    agg["销售ADR"] = agg["销售金额"] / agg["间夜数"].replace(0, pd.NA)

    rows: list[dict] = []
    missing_stores: list[str] = []
    for _, r in agg.sort_values("date").iterrows():
        d = date.fromisoformat(r["date"])
        if r["date"] not in store_counts:
            missing_stores.append(r["date"])
        rows.append(
            {
                "date": r["date"],
                "label": f"{d.month}/{d.day}",
                "fullLabel": f"{d.year}/{d.month}/{d.day}",
                "stores": store_counts.get(r["date"]),
                "orders": int(round(r["订单数"])),
                "nights": int(round(r["间夜数"])),
                "sales": round(float(r["销售金额"]), 2),
                "settlement": round(float(r["结算金额"]), 2),
                "retention": round(float(r["留存金额"]), 2),
                "adr": round(float(r["销售ADR"]) if pd.notna(r["销售ADR"]) else 0, 2),
            }
        )

    if missing_stores:
        raise ValueError(f"售卖门店数缺少日期: {', '.join(missing_stores[:10])}")

    backend_total = {
        "stores_end": int(float(total["售卖门店数"])),
        "orders": int(float(total["订单数"])),
        "nights": int(float(total["间夜数"])),
        "sales": round(float(total["销售金额"]), 2),
        "settlement": round(float(total["结算金额"]), 2),
        "retention": round(float(total["留存金额"]), 2),
        "adr": round(float(total["销售ADR"]), 6),
    }
    computed = {
        "stores_end": rows[-1]["stores"],
        "orders": sum(r["orders"] for r in rows),
        "nights": sum(r["nights"] for r in rows),
        "sales": round(sum(r["sales"] for r in rows), 2),
        "settlement": round(sum(r["settlement"] for r in rows), 2),
        "retention": round(sum(r["retention"] for r in rows), 2),
        "adr": round(sum(r["sales"] for r in rows) / sum(r["nights"] for r in rows), 6),
    }
    diff = {k: round(computed[k] - backend_total[k], 6) for k in backend_total}
    bad = {k: v for k, v in diff.items() if abs(v) > (0.01 if k in {"sales", "settlement", "retention", "adr"} else 0)}
    if bad:
        raise ValueError(f"明细汇总与后台总计行不一致: {bad}")

    meta = {
        "start_date": rows[0]["date"],
        "end_date": rows[-1]["date"],
        "count": len(rows),
        "backend_total": backend_total,
        "computed": computed,
        "diff": diff,
    }
    return rows, meta


def nice_max(v: float) -> int:
    if v <= 0:
        return 1
    p = 10 ** math.floor(math.log10(v))
    return int(math.ceil(v / p * 1.08) * p)


def build_html(rows: list[dict], meta: dict) -> str:
    bt = meta["backend_total"]
    avg_stores = sum(r["stores"] for r in rows) / len(rows)
    data_json = json.dumps(
        [
            {
                "date": r["date"],
                "label": r["label"],
                "fullLabel": r["fullLabel"],
                "stores": r["stores"],
                "orders": r["orders"],
                "nights": r["nights"],
                "sales": r["sales"],
                "adr": r["adr"],
            }
            for r in rows
        ],
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>渠道经营数据看板</title>
<style>
:root{{--bg:#f3f6fb;--panel:#fff;--ink:#101827;--muted:#65748b;--line:#d9e3f0;--grid:#e5ecf5;--blue:#2563eb;--teal:#0f9f9a;--rose:#e11d48;--slate:#64748b}}
*{{box-sizing:border-box}}body{{margin:0;background:#dfe7f2;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif}}
.slide{{width:390px;min-height:900px;height:auto;margin:0 auto;padding:24px 14px 20px;overflow:visible;background:linear-gradient(135deg,#fbfdff 0%,#f4f7fb 54%,#eef4fb 100%)}}
h1{{margin:0;font-size:30px;line-height:1.15;letter-spacing:0;font-weight:900}}.badge{{margin-top:10px;border:1px solid var(--line);background:rgba(255,255,255,.9);padding:12px 16px;border-radius:8px;box-shadow:0 8px 24px rgba(30,49,82,.06)}}.badge .label{{color:var(--muted);font-size:13px;font-weight:700}}.badge .value{{margin-top:5px;font-size:22px;font-weight:900}}
.kpis{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:14px 0}}.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:13px;min-height:92px;box-shadow:0 12px 30px rgba(30,49,82,.07)}}.kpi .name{{color:var(--muted);font-size:12px;font-weight:800}}.kpi .num{{margin-top:10px;font-size:23px;line-height:1;font-weight:950}}.kpi .money{{font-size:21px}}.kpi .foot{{margin-top:9px;color:var(--muted);font-size:11px}}
.grid{{display:grid;grid-template-columns:1fr;gap:14px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:0 16px 34px rgba(30,49,82,.08);padding:15px 10px 8px;position:relative}}.card-head{{display:flex;gap:10px;justify-content:space-between;align-items:flex-start;margin:0 2px 8px}}h2{{margin:0 0 8px;font-size:31px;line-height:1.05;font-weight:900}}.legend{{display:flex;gap:8px 10px;flex-wrap:wrap;color:var(--ink);font-size:11px;font-weight:800}}.leg{{display:inline-flex;align-items:center}}.sw{{display:inline-block;width:9px;height:18px;border-radius:6px;margin-right:6px}}.note{{color:var(--muted);font-size:15px;max-width:210px;text-align:right;line-height:1.45;font-weight:700}}
.chart{{width:100%;height:520px;display:block}}.axis text{{fill:#65748b;font-size:10.5px;font-weight:650}}.x-axis text{{font-size:11px;font-weight:800}}.axis-label{{font-size:11px!important;font-weight:900}}.gridline{{stroke:var(--grid);stroke-width:1}}.hover-line{{stroke:#94a3b8;stroke-width:1;opacity:0}}
.tooltip{{position:absolute;pointer-events:none;z-index:5;opacity:0;background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 12px 25px rgba(30,49,82,.15);transform:translate(-50%,-100%);white-space:nowrap}}
</style></head><body><main class="slide">
<section><h1>渠道经营数据看板</h1><div class="badge"><div class="label">统计周期</div><div class="value">{meta["start_date"].replace("-", "/")} - {meta["end_date"].replace("-", "/")}</div></div></section>
<section class="kpis">
<div class="kpi"><div class="name">总订单数</div><div class="num">{intfmt(bt["orders"])}</div><div class="foot">有效订单</div></div>
<div class="kpi"><div class="name">总间夜数</div><div class="num">{intfmt(bt["nights"])}</div><div class="foot">有效间夜</div></div>
<div class="kpi"><div class="name">总销售金额</div><div class="num money">{money(bt["sales"])}</div><div class="foot">销售口径</div></div>
<div class="kpi"><div class="name">总留存金额</div><div class="num money">{money(bt["retention"])}</div><div class="foot">销售 - 结算</div></div>
<div class="kpi"><div class="name">整体销售ADR</div><div class="num">{money(bt["adr"])}</div><div class="foot">销售金额 / 间夜</div></div>
<div class="kpi"><div class="name">期末售卖门店数</div><div class="num">{intfmt(bt["stores_end"])}</div><div class="foot">周期均值 {intfmt(avg_stores)} 家</div></div>
</section>
<section class="grid">
<div class="card" id="volumeCard"><div class="card-head"><div><h2>供给与成交趋势</h2><div class="legend"><span class="leg"><i class="sw" style="background:var(--blue)"></i>订单数</span><span class="leg"><i class="sw" style="background:var(--teal)"></i>间夜数</span><span class="leg"><i class="sw" style="background:rgba(100,116,139,.55)"></i>售卖门店数</span></div></div><div class="note">订单/间夜与售卖门店数分层展示，避免不同数量级共用 Y 轴。</div></div><svg id="volumeChart" class="chart"></svg><div class="tooltip"></div></div>
<div class="card" id="revenueCard"><div class="card-head"><div><h2>收入与价格质量</h2><div class="legend"><span class="leg"><i class="sw" style="background:var(--blue)"></i>销售金额</span><span class="leg"><i class="sw" style="background:var(--rose)"></i>销售ADR</span></div></div><div class="note">销售金额与 ADR 使用独立面板，单位分别为元与元/间夜。</div></div><svg id="revenueChart" class="chart"></svg><div class="tooltip"></div></div>
</section>
<script>
const DATA = {data_json};
const COLORS = {{blue:'#2563eb', teal:'#0f9f9a', rose:'#e11d48', slate:'#64748b', grid:'#e5ecf5', muted:'#64748b'}};
const fmt = new Intl.NumberFormat('zh-CN');
const yuan2 = v => '¥' + Number(v).toLocaleString('zh-CN', {{minimumFractionDigits:2, maximumFractionDigits:2}});
function niceMax(v) {{ const p = Math.pow(10, Math.floor(Math.log10(v || 1))); return Math.ceil(v / p * 1.08) * p; }}
function pathLine(data, x, y, key) {{ return data.map((d,i)=>`${{i?'L':'M'}}${{x(i).toFixed(2)}},${{y(d[key]).toFixed(2)}}`).join(' '); }}
function axisY(svg, x0, x1, y0, y1, max, label, formatter) {{ const g=document.createElementNS(svg.namespaceURI,'g'); g.setAttribute('class','axis'); svg.appendChild(g); for(let i=0;i<=4;i++) {{ const val=max*i/4; const y=y1-(y1-y0)*i/4; const line=document.createElementNS(svg.namespaceURI,'line'); line.setAttribute('x1',x0); line.setAttribute('x2',x1); line.setAttribute('y1',y); line.setAttribute('y2',y); line.setAttribute('class','gridline'); g.appendChild(line); const t=document.createElementNS(svg.namespaceURI,'text'); t.setAttribute('x',x0-8); t.setAttribute('y',y+4); t.setAttribute('text-anchor','end'); t.textContent=formatter(val); g.appendChild(t); }} const l=document.createElementNS(svg.namespaceURI,'text'); l.setAttribute('x',x0); l.setAttribute('y',y0-10); l.setAttribute('class','axis-label'); l.textContent=label; g.appendChild(l); }}
function axisX(svg, data, x, y) {{ const g=document.createElementNS(svg.namespaceURI,'g'); g.setAttribute('class','axis x-axis'); svg.appendChild(g); const last=data.length-1; data.forEach((d,i)=>{{ const day=Number(d.date.slice(8,10)); const nearLast=(last-i)<18; const show=i===last || (day===1 && !nearLast); if(show) {{ const tick=document.createElementNS(svg.namespaceURI,'line'); tick.setAttribute('x1',x(i)); tick.setAttribute('x2',x(i)); tick.setAttribute('y1',y-8); tick.setAttribute('y2',y-2); tick.setAttribute('stroke','#a8b6c8'); tick.setAttribute('stroke-width','1'); g.appendChild(tick); const t=document.createElementNS(svg.namespaceURI,'text'); t.setAttribute('x',x(i)); t.setAttribute('y',y+13); t.setAttribute('text-anchor','middle'); t.textContent=d.label; g.appendChild(t); }} }}); }}
function makeLine(svg, d, color, width=3) {{ const p=document.createElementNS(svg.namespaceURI,'path'); p.setAttribute('d',d); p.setAttribute('fill','none'); p.setAttribute('stroke',color); p.setAttribute('stroke-width',width); p.setAttribute('stroke-linejoin','round'); p.setAttribute('stroke-linecap','round'); svg.appendChild(p); return p; }}
function bindChartTooltip(svg, hit, line, tip, W, m, renderTip) {{ const show = e => {{ e.preventDefault?.(); const source = e.touches ? e.touches[0] : e; const pt = svg.createSVGPoint(); pt.x=source.clientX; pt.y=source.clientY; const p=pt.matrixTransform(svg.getScreenCTM().inverse()); let i=Math.round((p.x-m.l)/((W-m.l-m.r)/(DATA.length-1))); i=Math.max(0,Math.min(DATA.length-1,i)); const d=DATA[i]; const px=m.l+i*(W-m.l-m.r)/(DATA.length-1); line.setAttribute('x1',px); line.setAttribute('x2',px); line.style.opacity=1; tip.innerHTML=renderTip(d); tip.style.opacity=1; tip.style.left=(px/W*100)+'%'; tip.style.top='250px'; }}; const hide=()=>{{line.style.opacity=0; tip.style.opacity=0;}}; hit.addEventListener('mousemove',show); hit.addEventListener('click',show); hit.addEventListener('touchstart',show,{{passive:false}}); hit.addEventListener('touchmove',show,{{passive:false}}); hit.addEventListener('mouseleave',hide); }}
function drawVolume() {{ const svg=document.getElementById('volumeChart'); const tip=document.getElementById('volumeCard').querySelector('.tooltip'); svg.innerHTML=''; const W=350,H=520,m={{l:50,r:12,t:26,b:34}},split=306,gap=56; svg.setAttribute('viewBox',`0 0 ${{W}} ${{H}}`); const x=i=>m.l+i*(W-m.l-m.r)/(DATA.length-1); const barW=(W-m.l-m.r)/DATA.length*.58; const countMax=niceMax(Math.max(...DATA.map(d=>Math.max(d.orders,d.nights)))); const storeMin=Math.floor((Math.min(...DATA.map(d=>d.stores))-80)/50)*50; const storeMax=Math.ceil((Math.max(...DATA.map(d=>d.stores))+80)/50)*50; const y1=v=>split-(split-m.t)*(v/countMax); const y2=v=>H-m.b-(H-m.b-(split+gap))*((v-storeMin)/(storeMax-storeMin)); axisY(svg,m.l,W-m.r,m.t,split,countMax,'单 / 间夜',v=>fmt.format(Math.round(v))); axisY(svg,m.l,W-m.r,split+gap,H-m.b,storeMax,'门店',v=>fmt.format(Math.round(v))); axisX(svg,DATA,x,H-12); makeLine(svg,pathLine(DATA,x,y1,'orders'),COLORS.blue); makeLine(svg,pathLine(DATA,x,y1,'nights'),COLORS.teal); DATA.forEach((d,i)=>{{ const rect=document.createElementNS(svg.namespaceURI,'rect'); rect.setAttribute('x',x(i)-barW/2); rect.setAttribute('y',y2(d.stores)); rect.setAttribute('width',barW); rect.setAttribute('height',H-m.b-y2(d.stores)); rect.setAttribute('rx',3); rect.setAttribute('fill','rgba(100,116,139,.45)'); svg.appendChild(rect); }}); const line=document.createElementNS(svg.namespaceURI,'line'); line.setAttribute('y1',m.t); line.setAttribute('y2',H-m.b); line.setAttribute('class','hover-line'); svg.appendChild(line); const hit=document.createElementNS(svg.namespaceURI,'rect'); hit.setAttribute('x',m.l); hit.setAttribute('y',m.t); hit.setAttribute('width',W-m.l-m.r); hit.setAttribute('height',H-m.t-m.b); hit.setAttribute('fill','transparent'); svg.appendChild(hit); bindChartTooltip(svg,hit,line,tip,W,m,d=>`<b>${{d.fullLabel}}</b><br>售卖门店数：${{fmt.format(d.stores)}}<br>订单数：${{fmt.format(d.orders)}}<br>间夜数：${{fmt.format(d.nights)}}`); }}
function drawRevenue() {{ const svg=document.getElementById('revenueChart'); const tip=document.getElementById('revenueCard').querySelector('.tooltip'); svg.innerHTML=''; const W=350,H=520,m={{l:62,r:12,t:26,b:34}},split=306,gap=56; svg.setAttribute('viewBox',`0 0 ${{W}} ${{H}}`); const x=i=>m.l+i*(W-m.l-m.r)/(DATA.length-1); const barW=(W-m.l-m.r)/DATA.length*.62; const salesMax=niceMax(Math.max(...DATA.map(d=>d.sales))); const adrMax=niceMax(Math.max(...DATA.map(d=>d.adr))); const y1=v=>split-(split-m.t)*(v/salesMax); const y2=v=>H-m.b-(H-m.b-(split+gap))*(v/adrMax); axisY(svg,m.l,W-m.r,m.t,split,salesMax,'元',v=>'¥'+fmt.format(Math.round(v))); axisY(svg,m.l,W-m.r,split+gap,H-m.b,adrMax,'元/间夜',v=>'¥'+Math.round(v)); axisX(svg,DATA,x,H-12); DATA.forEach((d,i)=>{{ const rect=document.createElementNS(svg.namespaceURI,'rect'); rect.setAttribute('x',x(i)-barW/2); rect.setAttribute('y',y1(d.sales)); rect.setAttribute('width',barW); rect.setAttribute('height',split-y1(d.sales)); rect.setAttribute('rx',3); rect.setAttribute('fill','rgba(37,99,235,.68)'); svg.appendChild(rect); }}); makeLine(svg,pathLine(DATA,x,y2,'adr'),COLORS.rose); const line=document.createElementNS(svg.namespaceURI,'line'); line.setAttribute('y1',m.t); line.setAttribute('y2',H-m.b); line.setAttribute('class','hover-line'); svg.appendChild(line); const hit=document.createElementNS(svg.namespaceURI,'rect'); hit.setAttribute('x',m.l); hit.setAttribute('y',m.t); hit.setAttribute('width',W-m.l-m.r); hit.setAttribute('height',H-m.t-m.b); hit.setAttribute('fill','transparent'); svg.appendChild(hit); bindChartTooltip(svg,hit,line,tip,W,m,d=>`<b>${{d.fullLabel}}</b><br>销售金额：${{yuan2(d.sales)}}<br>销售ADR：${{yuan2(d.adr)}}<br>订单数：${{fmt.format(d.orders)}}<br>间夜数：${{fmt.format(d.nights)}}`); }}
drawVolume(); drawRevenue();
</script></main></body></html>"""


def render_png(html_path: Path, png_path: Path, width: int = 390) -> None:
    node = os.environ.get("NODE_BIN") or shutil.which("node")
    if not node:
        raise RuntimeError("未找到 node（PNG 渲染需要 playwright）。请设置 NODE_BIN 或将 node 加入 PATH。")
    node_path = os.environ.get("NODE_PATH") or ""
    launch_options = {"headless": True, "args": ["--no-sandbox"]}
    code = f"""
const {{ chromium }} = require('playwright');
(async()=>{{
  const browser=await chromium.launch({json.dumps(launch_options, ensure_ascii=False)});
  const page=await browser.newPage({{viewport:{{width:{width},height:900}}, deviceScaleFactor:2}});
  const logs=[]; page.on('pageerror', e=>logs.push(e.message));
  await page.goto('file://{html_path}');
  if (logs.length) throw new Error(logs.join('\\n'));
  const h=await page.evaluate(() => Math.ceil(document.querySelector('.slide').getBoundingClientRect().height));
  await page.setViewportSize({{width:{width},height:h}});
  await page.screenshot({{path:{json.dumps(str(png_path))}, clip:{{x:0,y:0,width:{width},height:h}}}});
  await browser.close();
}})();
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    child_env = {**os.environ}
    if node_path:
        child_env["NODE_PATH"] = node_path
    try:
        subprocess.run([node, tmp], check=True, env=child_env)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build channel daily mobile dashboard HTML and PNG.")
    parser.add_argument("--excel", required=True, help="Backend exported daily channel orders Excel")
    parser.add_argument("--store-counts", required=True, help="Daily store-count JSON or CSV")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prefix", default="channel_dashboard")
    parser.add_argument("--no-png", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stores = load_store_counts(Path(args.store_counts).expanduser())
    rows, meta = read_backend_excel(Path(args.excel).expanduser(), stores)
    start = meta["start_date"].replace("-", "")
    end = meta["end_date"].replace("-", "")
    stem = f"{args.prefix}_mobile_{start}_{end}"
    html_path = out_dir / f"{stem}.html"
    png_path = out_dir / f"{stem}.png"
    json_path = out_dir / f"{args.prefix}_metrics_{start}_{end}.json"

    html_path.write_text(build_html(rows, meta), encoding="utf-8")
    json_path.write_text(json.dumps({"meta": meta, "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_png:
        render_png(html_path, png_path)

    print(json.dumps({"html": str(html_path), "png": None if args.no_png else str(png_path), "json": str(json_path), "diff": meta["diff"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
