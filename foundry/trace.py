"""Render trace.json into a self-contained HTML page.

Two views:
  1. Timeline (Gantt): one lane per worker instance, so parallel work is visible.
  2. Handoff ladder: every handoff as an arrow between levels
     (you / orchestrator / leads / workers), color coded by kind.
"""

import json

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Handoff trace</title>
<style>
:root{--bg:#fbfaf7;--card:#fff;--text:#1f1e1c;--muted:#6b6a65;--line:#e4e2db;
--dispatch:#378ADD;--return:#1D9E75;--accept:#1D9E75;--reject:#BA7517;--escalate:#E24B4A;--gate:#7F77DD;--merge:#534AB7;--skip:#888780}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1a1a19;--card:#242422;--text:#ecebe6;--muted:#a3a29b;--line:#3a3a37}}
:root[data-theme="dark"]{--bg:#1a1a19;--card:#242422;--text:#ecebe6;--muted:#a3a29b;--line:#3a3a37}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;font-weight:600;margin:0 0 4px}h2{font-size:17px;font-weight:600;margin:32px 0 4px}
.sub{color:var(--muted);margin:0 0 16px;font-size:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.stat b{display:block;font-size:22px;font-weight:600}.stat span{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;overflow-x:auto}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0;font-size:13px}
.legend button{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:999px;padding:3px 10px;cursor:pointer;font:inherit}
.legend button.off{opacity:.35}.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle}
.row{display:grid;grid-template-columns:52px 1fr;gap:8px;align-items:center;border-top:1px solid var(--line);padding:4px 0}
.row:first-child{border-top:0}.t{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.lbl{font-size:13px}.lbl code{font-size:12px;color:var(--muted)}.note{color:var(--muted);font-size:12px}
svg text{fill:var(--muted);font-size:11px}
</style></head><body><main>
<h1>Handoff trace</h1><p class="sub" id="req"></p>
<div class="stats" id="stats"></div>
<h2>Who was working when</h2><p class="sub">One lane per agent instance. Overlapping bars are agents running in parallel. Amber bars were rejected by their lead.</p>
<div class="card" id="gantt"></div>
<h2>Every handoff</h2><p class="sub">Arrows move between levels. Tap a kind to filter.</p>
<div class="legend" id="legend"></div>
<div class="card"><div id="cols"></div><div id="ladder"></div></div>
</main>
<script>
const D = __DATA__;
const css = k => getComputedStyle(document.documentElement).getPropertyValue('--'+k).trim();
const H = D.events.filter(e=>e.type==='handoff'), S = D.events.filter(e=>e.type==='span');
const end = Math.max(...D.events.map(e=>e.end||e.t));
document.getElementById('req').textContent = D.requirements || '';
const devs=S.filter(s=>/-dev#/.test(s.agent));let maxPar=0;
devs.forEach(s=>{const n=new Set(devs.filter(o=>o.start<=s.start&&o.end>s.start).map(o=>o.agent)).size;maxPar=Math.max(maxPar,n)});
const count=k=>H.filter(h=>h.kind===k).length;
[['Run time',end.toFixed(1)+'s'],['Handoffs',H.length],['Rejections',count('reject')],['Escalations',count('escalate')],['Merges',count('merge')],['Peak parallel devs',maxPar]]
 .forEach(([k,v])=>document.getElementById('stats').insertAdjacentHTML('beforeend',`<div class="stat"><b>${v}</b><span>${k}</span></div>`));

const lanes=[...new Set(S.map(s=>s.agent))].sort((a,b)=>(D.levels[a]-D.levels[b])||a.localeCompare(b));
const W=900,L=150,rowH=22,gh=lanes.length*rowH+24, sx=t=>L+(t/end)*(W-L-10);
let g=`<svg viewBox="0 0 ${W} ${gh}" width="100%" style="min-width:600px">`;
for(let i=0;i<=5;i++){const t=end*i/5;g+=`<line x1="${sx(t)}" x2="${sx(t)}" y1="0" y2="${gh-16}" stroke="${css('line')}"/><text x="${sx(t)}" y="${gh-4}" text-anchor="middle">${t.toFixed(1)}s</text>`}
lanes.forEach((a,i)=>{const y=i*rowH;g+=`<text x="0" y="${y+15}">${a}</text>`;
 S.filter(s=>s.agent===a).forEach(s=>{g+=`<rect x="${sx(s.start)}" y="${y+4}" width="${Math.max(3,sx(s.end)-sx(s.start))}" height="14" rx="3" fill="${s.ok?css('return'):css('reject')}"><title>${a}: ${s.label} ${s.start}s to ${s.end}s</title></rect>`})});
document.getElementById('gantt').innerHTML=g+'</svg>';

const colNames=['You','Orchestrator','Leads','Workers'], lx=lv=>30+(lv+1)*80;
const off=new Set();
const kinds=[...new Set(H.map(h=>h.kind))];
const legend=document.getElementById('legend');
kinds.forEach(k=>{const b=document.createElement('button');b.innerHTML=`<span class="sw" style="background:${css(k)}"></span>${k} (${count(k)})`;
 b.onclick=()=>{off.has(k)?off.delete(k):off.add(k);b.classList.toggle('off');draw()};legend.appendChild(b)});
document.getElementById('cols').innerHTML=`<div class="row"><span></span><svg viewBox="0 0 340 18" width="340" height="18">${colNames.map((n,i)=>`<text x="${lx(i-1)}" y="13" text-anchor="middle">${n}</text>`).join('')}</svg></div>`;
function lv(a){return a==='main'?2:(D.levels[a]??2)}
function draw(){
 document.getElementById('ladder').innerHTML=H.filter(h=>!off.has(h.kind)).map(h=>{
  const c=css(h.kind), x1=lx(lv(h.from)), x2=lx(lv(h.to));
  let mark = x1===x2 ? `<circle cx="${x1}" cy="11" r="5" fill="${c}"/>` :
   `<line x1="${x1}" y1="11" x2="${x2+(x2>x1?-6:6)}" y2="11" stroke="${c}" stroke-width="2"/><path d="M${x2} 11 l${x2>x1?-7:7} -5 v10z" fill="${c}"/><circle cx="${x1}" cy="11" r="3" fill="${c}"/>`;
  const dots=[0,1,2,3].map(i=>`<line x1="${lx(i-1)}" x2="${lx(i-1)}" y1="0" y2="22" stroke="${css('line')}"/>`).join('');
  return `<div class="row"><span class="t">${h.t.toFixed(2)}s</span><div><svg viewBox="0 0 340 22" width="340" height="22">${dots}${mark}</svg>
   <div class="lbl"><b style="color:${c}">${h.kind}</b> ${h.from} &rarr; ${h.to} ${h.artifacts.length?'<code>'+h.artifacts.join(', ')+'</code>':''}</div>
   ${h.note?`<div class="note">${h.note.replace(/</g,'&lt;')}</div>`:''}</div></div>`}).join('');
}
draw();
</script></body></html>"""


def render(trace_path, out_path, requirements=""):
    data = json.loads(open(trace_path).read())
    data["requirements"] = requirements
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    open(out_path, "w").write(html)
    return out_path
