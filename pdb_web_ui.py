#!/usr/bin/env python3
"""PDB Tracker Web UI — generates JS file at startup to avoid Python string escaping.

All paths are configurable via environment variables:
  PDB_DATA_DIR      - 数据根目录 (默认 ~/.pdb-tracker/)
  PDB_DB_DIR        - 数据库目录 (默认 $PDB_DATA_DIR/data/)
  PDB_DB_NAME       - 数据库文件名 (默认 pdb_tracker.db)
  PDB_WEEKLY_DIR    - 周报目录 (默认 $PDB_DATA_DIR/weekly_reports/)
  PDB_WEB_SCRIPT_DIR - Web UI 运行时目录 (默认 $PDB_DATA_DIR/web_scripts/)
  PDB_WEB_PORT      - 端口 (默认 5555)
"""
import os
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file
import re, sqlite3, subprocess, time, json, logging, datetime

# Setup logging first
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Load .env file for API keys
try:
    from dotenv import load_dotenv
    # Try workspace .env first, then openclaw .env
    for env_path in [
        Path.home() / '.openclaw' / '.env',
        Path.home() / '.env',
    ]:
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"[env] Loaded {env_path}")
            break
except ImportError:
    pass

# ─── 配置 (支持环境变量覆盖) ──────────────────────────────────────────────
def _get_data_dir() -> Path:
    if os.getenv("PDB_DATA_DIR"):
        return Path(os.getenv("PDB_DATA_DIR"))
    return Path("/Users/lijing/Documents/my_note/LLM-Wiki/data")

DATA_DIR = _get_data_dir()
DB_DIR = Path(os.getenv("PDB_DB_DIR", str(DATA_DIR)))
DB_PATH = DB_DIR / os.getenv("PDB_DB_NAME", "pdb_tracker.db")
REPORTS_DIR = Path(os.getenv("PDB_WEEKLY_DIR", str(DATA_DIR / "weekly_reports")))
SCRIPT_DIR = Path(os.getenv("PDB_WEB_SCRIPT_DIR", str(DATA_DIR / "web_scripts")))
SCRIPT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

# ─── Generate JS file at startup ───────────────────────────────────────────
def write_js():
    NL = "\n"
    lines = []

    def L(s):
        lines.append(s + NL)

    L("(function(){")
    L('"use strict";')
    L("var allEntries=[];var snapshots=[];var allReports=[];var activeWeek=null;var activeEvalMdReport=null;")
    L("var activeMethod='all';var activeSearch='';var sortCol='release_date';var sortAsc=false;")
    L("var activeTab='summary';var activeReport=null;var molViewer=null;")

    L("function escHtml(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}")
    L("function fmtMethod(m){if(!m)return '-';var mLower=m.toLowerCase();if(/electron crystallography/i.test(mLower))return 'ELECTRON CRYSTALLOGRAPHY';if(/electron microscopy|cryo/i.test(mLower))return 'Cryo-EM';if(/x-ray/i.test(mLower))return 'X-ray';if(/nmr/i.test(mLower))return 'NMR';return m;}")

    L("async function init(){try{snapshots=await fetch('/api/snapshots').then(function(r){return r.json();});}catch(e){snapshots=[];}renderWeeks();try{allReports=await fetch('/api/reports/list').then(function(r){return r.json();});}catch(e){allReports=[];}await loadEntries();}")

    L("function renderWeeks(){var list=document.getElementById('week-list');if(!snapshots||!snapshots.length){list.innerHTML='<div class=\"report-empty\">No data</div>';return;}var sel=document.getElementById('sel-week');sel.innerHTML=\"<option value='all'>All Weeks</option>\";list.innerHTML='';snapshots.forEach(function(s){var card=document.createElement('div');card.className='report-item';card.dataset.wid=s.week_id;card.innerHTML=\"<div class='rname' style='font-size:11px;'><span style='font-family:var(--mono);color:var(--accent);'>\"+s.week_id+\"</span> <span style='font-size:9px;color:var(--muted);'>\"+s.total_structures+\" entries</span></div><div class='rtitle' style='font-size:10px;'>\"+s.week_start+\" -> \"+s.week_end+\"</div><div class='rdate' style='font-size:9px;color:var(--muted);'>EM:\"+(s.cryoem_count||0)+\" | XR:\"+(s.xray_count||0)+\"</div>\";card.onclick=(function(wid,c){return function(){onWeekClick(wid,c);};})(s.week_id,card);list.appendChild(card);var opt=document.createElement('option');opt.value=s.week_id;opt.textContent=s.week_id+' ('+s.week_start+')';sel.appendChild(opt);});}")

    L(r"async function onWeekClick(weekId,card){console.log('onWeekClick called with weekId=',weekId);activeWeek=weekId;activeMethod='all';activeSearch='';document.getElementById('sel-method').value='all';document.getElementById('inp-search').value='';var list=document.getElementById('week-list');var weekCards=list.querySelectorAll('.report-item');var selectedCard=null;if(weekId===null){weekCards.forEach(function(c){c.style.display='';c.classList.remove('active');});document.getElementById('sel-week').value='all';await loadEntries();var oldReportsDiv=document.getElementById('week-reports');if(oldReportsDiv)oldReportsDiv.remove();document.getElementById('back-button-container').style.display='none';}else{weekCards.forEach(function(c){if(c.dataset.wid===weekId){c.classList.add('active');c.style.display='';selectedCard=c;}else{c.classList.remove('active');c.style.display='none';}});if(selectedCard&&selectedCard!==list.firstChild){list.insertBefore(selectedCard,list.firstChild);}document.getElementById('sel-week').value=weekId;await loadEntries();var snap=null;for(var j=0;j<snapshots.length;j++)if(snapshots[j].week_id===weekId){snap=snapshots[j];break;}var filteredReports=[];if(snap){filteredReports=allReports.filter(function(r){var m=r.name.match(/(\d{4}-\d{2}-\d{2})/);return m&&m[1]>=snap.week_start&&m[1]<=snap.week_end;});}var oldReportsDiv=document.getElementById('week-reports');if(oldReportsDiv)oldReportsDiv.remove();var reportsDiv=document.createElement('div');reportsDiv.id='week-reports';reportsDiv.className='week-reports';reportsDiv.style.cssText='padding:8px 10px;border-top:1px solid var(--border);background:var(--card);margin-top:4px;';if(selectedCard){selectedCard.insertAdjacentElement('afterend',reportsDiv);}renderReportListInDiv(filteredReports,reportsDiv);document.getElementById('back-button-container').style.display='block';}}")

    L("async function loadEntries(){var params=[];if(activeWeek!==null)params.push('week='+encodeURIComponent(activeWeek));if(activeMethod!=='all')params.push('method='+encodeURIComponent(activeMethod));if(activeSearch)params.push('q='+encodeURIComponent(activeSearch));params.push('limit=500');var url='/api/entries?'+params.join('&');try{allEntries=await fetch(url).then(function(r){return r.json();});}catch(e){allEntries=[];}var sortedRows=sortEntries(allEntries.slice());for(var si=0;si<sortedRows.length;si++){sortedRows[si]._origIdx=allEntries.indexOf(sortedRows[si]);}renderTable(sortedRows);}")

    L("function sortEntries(arr){return arr.slice().sort(function(a,b){var av=a[sortCol],bv=b[sortCol];if(sortCol==='journal_if'){av=(av==null||String(av).trim()===''||String(av).toLowerCase()==='unknown')?0:parseFloat(av);bv=(bv==null||String(bv).trim()===''||String(bv).toLowerCase()==='unknown')?0:parseFloat(bv);return sortAsc?(av-bv):(bv-av);}if(sortCol==='resolution'){av=(av==null||String(av).trim()===''||isNaN(parseFloat(av)))?999:parseFloat(av);bv=(bv==null||String(bv).trim()===''||isNaN(parseFloat(bv)))?999:parseFloat(bv);return sortAsc?(av-bv):(bv-av);}var an=parseFloat(av),bn=parseFloat(bv);var aNum=(av!=null&&String(av).trim()!==''&&!isNaN(an));var bNum=(bv!=null&&String(bv).trim()!==''&&!isNaN(bn));var cmp;if(aNum&&bNum){cmp=an-bn;}else if(aNum){cmp=-1;}else if(bNum){cmp=1;}else{cmp=String(av||'').localeCompare(String(bv||''));}return sortAsc?cmp:-cmp;});}")

    L("function renderTable(rows){var tbody=document.getElementById('table-body');tbody.removeAttribute('data-eval-table');document.getElementById('entry-count').textContent=rows.length+' entries';if(!rows.length){tbody.innerHTML=\"<tr><td colspan='7'><div class='preview-empty'><div class='preview-empty-icon'>&#128269;</div>No entries</div></td></tr>\";return;}var html=[];for(var i=0;i<rows.length;i++){var e=rows[i];var origIdx=e._origIdx!=null?e._origIdx:i;var method=e.method||'';var bClass='badge-oth',mLabel=method;var mLower=method.toLowerCase();if(/electron crystallography/i.test(mLower)){bClass='badge-em';mLabel='ELECTRON CRYSTALLOGRAPHY';}else if(/electron microscopy|cryo/i.test(mLower)){bClass='badge-em';mLabel='Cryo-EM';}else if(/x-ray/i.test(mLower)){bClass='badge-xr';mLabel='X-ray';}else if(/nmr/i.test(mLower)){bClass='badge-nmr';mLabel='NMR';}var res=e.resolution;var rClass='res-mid',rStr='-';if(res!=null&&String(res).trim()!==''&&!isNaN(parseFloat(res))&&parseFloat(res)>0){var rn=parseFloat(res);rClass=rn<=2.0?'res-good':rn>3.5?'res-poor':'res-mid';rStr=rn.toFixed(2);}var ifTier=e.if_tier||'';var tierBadge=(ifTier&&ifTier!=='unknown')?\"<span class='if-badge tier-\"+ifTier+\"'>\"+ifTier.toUpperCase()+\"</span>\":'';var ifNum=parseFloat(e.journal_if);var hasValidIf=e.journal_if!=null&&String(e.journal_if).trim()!==''&&String(e.journal_if).toLowerCase()!=='unknown'&&!isNaN(ifNum)&&ifNum>0;var ifVal=hasValidIf?\" <span class='if-val'>IF \"+ifNum.toFixed(1)+\"</span>\":\" <span class='if-val'>To be published</span>\";var ligand=(e.ligand_info||e.ligand||'').trim();var ligs=ligand?(ligand.split(/[;|,]/).map(function(l){var trimmed=l.trim();var colonIdx=trimmed.indexOf(':');return colonIdx>0?trimmed.substring(0,colonIdx):trimmed;}).filter(Boolean)):[];var ligHtml='-';if(ligs.length){var chips=[];for(var li=0;li<ligs.length;li++){chips.push(\"<span class='lig-chip' data-lig='\"+escHtml(ligs[li])+\"' data-idx='\"+origIdx+\"'>\"+escHtml(ligs[li])+\"</span>\");}ligHtml=chips.join(' ');}html.push(\"<tr><td><span class='pdb-link' data-idx='\"+origIdx+\"' data-pdb='\"+escHtml(e.pdb_id)+\"'>\"+escHtml(e.pdb_id)+\"</span></td>\"+\"<td><span class='method-badge \"+bClass+\"'>\"+escHtml(mLabel)+\"</span></td>\"+\"<td><span class='res \"+rClass+\"'>\"+(rStr!=='-'?rStr+' A':'-')+\"</span></td>\"+\"<td>\"+tierBadge+ifVal+\"</td>\"+\"<td class='title-cell' title='\"+escHtml(e.title||'')+\"'>\"+escHtml(e.title||'-')+\"</td>\"+\"<td>\"+(e.release_date||'-')+\"</td>\"+\"<td class='lig-cell'>\"+ligHtml+\"</td></tr>\");}tbody.innerHTML=html.join('');}")

    L("document.getElementById('table-head').onclick=function(e){var th=e.target.closest('th');if(!th||!th.dataset.col)return;var col=th.dataset.col;if(sortCol===col){sortAsc=!sortAsc;}else{sortCol=col;sortAsc=false;}document.querySelectorAll('#table-head th').forEach(function(t){t.dataset.sorted='false';var a=t.querySelector('.sort-arrow');if(a)a.innerHTML='&#8645;';});th.dataset.sorted='true';var sa=th.querySelector('.sort-arrow');if(sa)sa.innerHTML=sortAsc?'&#8593;':'&#8595;';if(currentMode==='eval'){var sorted=sortEvalStructures(currentEvalStructures.slice());currentEvalStructures=sorted;renderEvalTable(sorted,currentBlastResults);}else{renderTable(sortEntries(allEntries.slice()));}};")

    L("var ttPdb=document.getElementById('tt-pdb');")
    L("var ttLig=document.getElementById('tt-lig');")
    L("var ttHomolog=document.getElementById('tt-homolog');")
    L("function getBlastColorClass(type,val){if(type==='identity'){if(val>=70)return'blast-value-high';if(val>=40)return'blast-value-mid';return'blast-value-low';}if(type==='evalue'){if(val<1e-50)return'blast-value-high';if(val<1e-10)return'blast-value-mid';return'blast-value-low';}if(type==='coverage'){if(val>=80)return'blast-value-high';if(val>=50)return'blast-value-mid';return'blast-value-low';}return'';}")
    L("document.getElementById('table-body').addEventListener('mouseover',function(e){")
    L("  var pdbSpan=e.target.closest('.pdb-link');")
    L("  if(pdbSpan){")
    L("    var idx=parseInt(pdbSpan.getAttribute('data-idx'),10);")
    L("    var tbody=document.getElementById('table-body');")
    L("    var isEval=tbody&&tbody.getAttribute('data-eval-table')==='true';")
    L("    var entry=isEval?(currentEvalStructures.find(function(s){return s._origIdx===idx;})||{}):(allEntries[idx]||{});")
    L("    if(!entry)return;")
    L("    document.getElementById('tt-pdb-header').textContent=entry.pdb_id;")
    L("    document.getElementById('tt-pdb-method').textContent=fmtMethod(entry.method);")
    L("    document.getElementById('tt-pdb-res').textContent=(entry.resolution!=null)?entry.resolution+' A':'-';")
    L("    document.getElementById('tt-pdb-date').textContent=entry.release_date||'-';")
    L("    document.getElementById('tt-pdb-journal').textContent=entry.journal||'-';")
    L("    document.getElementById('tt-pdb-if').textContent=(entry.journal_if!=null)?Number(entry.journal_if).toFixed(1):'-';")
    L("    var ligs=((entry.ligand_info||entry.ligand||entry.ligands||'').trim())?((entry.ligand_info||entry.ligand||entry.ligands)||'').replace(/;/g,', '):'-';if(ligs!=='-'){var ligArr=entry.ligand_info?(entry.ligand_info.split('|').map(function(l){var parts=l.split(':');return parts[0]?parts[0].trim():l.trim();})):entry.ligand?(entry.ligand.split(/[;|]/).map(function(l){return l.trim().split(':')[0];})):entry.ligands?(entry.ligands.split(/[;|]/).map(function(l){return l.trim().split(':')[0];})):[];ligs=ligArr.filter(function(l){return l;}).join(', ')||'-';}document.getElementById('tt-pdb-ligs').textContent=ligs;")
    L("    var titleEl=document.getElementById('tt-pdb-title');")
    L("    if(entry.title){titleEl.textContent=entry.title;titleEl.style.display='block';}else{titleEl.style.display='none';}")
    L("    var img=document.getElementById('tt-pdb-img');")
    L("    img.src='https://cdn.rcsb.org/images/structures/'+(entry.pdb_id||'').toLowerCase()+'_assembly-1.jpeg';")
    L("    img.style.display='block';")
    L("    img.onerror=function(){this.style.display='none';};")
    L("    var homologSection=document.getElementById('tt-pdb-homolog-section');")
    L("    var pdbIdStr=entry.pdb_id||'';")
    L("    var blastInfo=isEval&&currentBlastResults?currentBlastResults.find(function(b){return b.pdb_id&&b.pdb_id.toUpperCase()===pdbIdStr.toUpperCase();}):null;")
    L("    if(blastInfo){")
    L("      homologSection.style.display='block';")
    L("      var seqLen=currentEvalData&&currentEvalData.uniprot?currentEvalData.uniprot.sequence_length:0;")
    L("      var identity=blastInfo.identity||0;")
    L("      var evalue=blastInfo.evalue||1;")
    L("      var qcov=blastInfo.query_coverage||0;")
    L("      var covPercent=seqLen>0?Math.round((qcov/seqLen)*100):0;")
    L("      document.getElementById('tt-pdb-homolog-identity').innerHTML='<span class=\\''+getBlastColorClass('identity',identity)+'\\'>'+identity+'%</span>';")
    L("      var evalueStr=evalue<0.001?evalue.toExponential(1):evalue.toFixed(3);")
    L("      document.getElementById('tt-pdb-homolog-evalue').innerHTML='<span class=\\''+getBlastColorClass('evalue',evalue)+'\\'>'+evalueStr+'</span>';")
    L("      document.getElementById('tt-pdb-homolog-coverage').innerHTML='<span class=\\''+getBlastColorClass('coverage',covPercent)+'\\'>'+covPercent+'%</span> ('+qcov+' aa)';if(seqLen<=0){document.getElementById('tt-pdb-homolog-coverage').textContent=qcov+' aa';}")
    L("    }else{")
    L("      homologSection.style.display='none';")
    L("    }")
    L("    var rect=pdbSpan.getBoundingClientRect();")
    L("    var x=rect.right+14,y=rect.top;")
    L("    if(x+230>window.innerWidth)x=rect.left-244;")
    L("    if(y+360>window.innerHeight)y=window.innerHeight-365;")
    L("    ttPdb.style.left=x+'px';")
    L("    ttPdb.style.top=y+'px';")
    L("    ttPdb.classList.add('show');")
    L("    ttLig.classList.remove('show');")
    L("    ttHomolog.classList.remove('show');")
    L("    return;")
    L("  }")
    L("  var chip=e.target.closest('.lig-chip');")
    L("  if(chip){")
    L("    var ligCode=chip.getAttribute('data-lig');")
    L("    if(!ligCode)return;")
    L("    document.getElementById('tt-lig-header').textContent=ligCode;")
    L("    document.getElementById('tt-lig-info').innerHTML='Loading...';")
    L("    var img=document.getElementById('tt-lig-img');")
    L("    img.style.display='none';")
    L("    img.onerror=function(){};")
    L("    var firstChar=ligCode.charAt(0);")
    L("    img.src='https://cdn.rcsb.org/images/ccd/labeled/'+firstChar+'/'+ligCode+'.svg';")
    L("    img.onload=function(){img.style.display='block';};")
    L("    img.onerror=function(){")
    L("      img.src='https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/'+encodeURIComponent(ligCode)+'/PNG';")
    L("      img.onload=function(){img.style.display='block';};")
    L("      img.onerror=function(){")
    L("        img.src='https://www.rcsb.org/ligand/graphics/'+ligCode+'-full.png';")
    L("        img.onload=function(){img.style.display='block';};")
    L("        img.onerror=function(){img.style.display='none';};")
    L("      };")
    L("    };")
    L("    fetch('/api/ligand/'+encodeURIComponent(ligCode)).then(function(r){return r.json();}).then(function(d){")
    L("      var name=d.name||ligCode;")
    L("      var infoLines=[];")
    L("      if(d.formula)infoLines.push('<span style=\\'color:var(--muted);\\'>Formula:</span> <span style=\\'color:var(--text);\\'>'+escHtml(d.formula)+'</span>');")
    L("      if(d.molecular_weight)infoLines.push('<span style=\\'color:var(--muted);\\'>MW:</span> <span style=\\'color:var(--text);\\'>'+Number(d.molecular_weight).toFixed(2)+' Da</span>');")
    L("      if(d.type)infoLines.push('<span style=\\'color:var(--muted);\\'>Type:</span> <span style=\\'color:var(--text);\\'>'+escHtml(d.type)+'</span>');")
    L("      if(d.description)infoLines.push('<span style=\\'color:var(--muted);\\'>Desc:</span> <span style=\\'color:var(--text);\\'>'+escHtml(d.description.substring(0,100))+(d.description.length>100?'...':'')+'</span>');")
    L("      var infoHtml=infoLines.length?infoLines.join('<br>'):'';")
    L("      document.getElementById('tt-lig-info').innerHTML='<div style=\\'font-size:12px;color:var(--primary);font-weight:600;margin-bottom:6px;border-bottom:1px solid var(--border);padding-bottom:4px;\\'>'+escHtml(name)+'</div>'+(infoHtml?'<div style=\\'font-size:10px;line-height:1.5;\\'>'+infoHtml+'</div>':'');")
    L("    }).catch(function(){")
    L("      document.getElementById('tt-lig-info').innerHTML='<div style=\\'font-size:12px;color:var(--primary);font-weight:600;\\'>'+escHtml(ligCode)+'</div><div style=\\'font-size:10px;color:var(--muted);\\'>No additional info</div>';")
    L("    });")
    L("    var rect=chip.getBoundingClientRect();")
    L("    var x=rect.right+10,y=rect.top-20;")
    L("    if(x+200>window.innerWidth)x=rect.left-210;")
    L("    if(y+200>window.innerHeight)y=window.innerHeight-205;")
    L("    ttLig.style.left=x+'px';")
    L("    ttLig.style.top=y+'px';")
    L("    ttLig.classList.add('show');")
    L("    ttPdb.classList.remove('show');")
    L("    ttHomolog.classList.remove('show');")
    L("    return;")
    L("  }")
    L("  var homologBadge=e.target.closest('.homolog-badge');")
    L("  if(homologBadge){")
    L("    var pdbId=homologBadge.getAttribute('data-blast-pdb');")
    L("    var identity=parseFloat(homologBadge.getAttribute('data-identity'))||0;")
    L("    var evalue=parseFloat(homologBadge.getAttribute('data-evalue'))||1;")
    L("    var qcov=parseInt(homologBadge.getAttribute('data-qcov'),10)||0;")
    L("    var seqLen=parseInt(homologBadge.getAttribute('data-seq-len'),10)||0;")
    L("    var method=homologBadge.getAttribute('data-method')||'Unknown';")
    L("    var res=homologBadge.getAttribute('data-res');")
    L("    var title=homologBadge.getAttribute('data-title')||'';")
    L("    var covPercent=seqLen>0?Math.round((qcov/seqLen)*100):0;")
    L("    document.getElementById('tt-homolog-pdb').textContent=pdbId||'N/A';")
    L("    document.getElementById('tt-homolog-identity').innerHTML='<span class=\\''+getBlastColorClass('identity',identity)+'\\'>'+identity+'%</span>';")
    L("    var evalueStr=evalue<0.001?evalue.toExponential(1):evalue.toFixed(3);")
    L("    document.getElementById('tt-homolog-evalue').innerHTML='<span class=\\''+getBlastColorClass('evalue',evalue)+'\\'>'+evalueStr+'</span>';")
    L("    document.getElementById('tt-homolog-coverage').innerHTML='<span class=\\''+getBlastColorClass('coverage',covPercent)+'\\'>'+covPercent+'%</span> ('+qcov+'/'+seqLen+' aa)';if(seqLen<=0){document.getElementById('tt-homolog-coverage').textContent=qcov+' aa';}")
    L("    document.getElementById('tt-homolog-method').textContent=fmtMethod(method);")
    L("    document.getElementById('tt-homolog-resolution').textContent=res?res+' A':'-';")
    L("    document.getElementById('tt-homolog-title').textContent=title?title.substring(0,100)+(title.length>100?'...':''):'No description';if(title){document.getElementById('tt-homolog-title').style.display='block';}else{document.getElementById('tt-homolog-title').style.display='none';}")
    L("    var rect=homologBadge.getBoundingClientRect();")
    L("    var x=rect.right+10,y=rect.top;")
    L("    if(x+220>window.innerWidth)x=rect.left-230;")
    L("    if(y+200>window.innerHeight)y=window.innerHeight-205;")
    L("    ttHomolog.style.left=x+'px';")
    L("    ttHomolog.style.top=y+'px';")
    L("    ttHomolog.classList.add('show');")
    L("    ttPdb.classList.remove('show');")
    L("    ttLig.classList.remove('show');")
    L("    return;")
    L("  }")
    L("});")
    L("document.getElementById('table-body').addEventListener('mouseout',function(e){if(e.relatedTarget&&ttPdb.contains(e.relatedTarget))return;if(!e.target.closest('.pdb-link'))return;ttPdb.classList.remove('show');if(e.relatedTarget&&ttLig.contains(e.relatedTarget))return;if(!e.target.closest('.lig-chip'))return;ttLig.classList.remove('show');if(e.relatedTarget&&ttHomolog.contains(e.relatedTarget))return;if(!e.target.closest('.homolog-badge'))return;ttHomolog.classList.remove('show');});")
    L("ttPdb.onmouseenter=function(){ttPdb.classList.add('show');};ttPdb.onmouseleave=function(){ttPdb.classList.remove('show');};")
    L("ttLig.onmouseenter=function(){ttLig.classList.add('show');};ttLig.onmouseleave=function(){ttLig.classList.remove('show');};")
    L("ttHomolog.onmouseenter=function(){ttHomolog.classList.add('show');};ttHomolog.onmouseleave=function(){ttHomolog.classList.remove('show');};")

    L("document.getElementById('table-body').onclick=function(e){var ligChip=e.target.closest('.lig-chip');if(ligChip){var ligCode=ligChip.getAttribute('data-lig');if(ligCode)window.open('https://www.rcsb.org/ligand/'+encodeURIComponent(ligCode),'_blank');return;}var homologBadge=e.target.closest('.homolog-badge');if(homologBadge){var pdbId=homologBadge.getAttribute('data-blast-pdb');if(pdbId)window.open('https://www.rcsb.org/structure/'+pdbId.toLowerCase(),'_blank');return;}var pdbSpan=e.target.closest('.pdb-link');if(pdbSpan){var pdbId=pdbSpan.getAttribute('data-pdb');if(pdbId)window.open('https://www.rcsb.org/structure/'+pdbId.toLowerCase(),'_blank');return;}};")

    L("function switchTab(tab){activeTab=tab;document.querySelectorAll('.preview-tab').forEach(function(t){t.classList.toggle('active',t.getAttribute('data-tab')===tab);});document.getElementById('preview-content').style.display='block';if(currentMode==='eval'){if(tab==='summary')showEvalSummary();else if(tab==='report')showEvalFullReport();}else{if(tab==='summary')showSummary(findSnap(activeReport));else if(tab==='report')showFullReport(activeReport);}}")

    L("function findSnap(name){if(!name||!snapshots||!snapshots.length)return null;var m=name.match(/(\\d{4}-\\d{2}-\\d{2})/);if(!m)return null;var d=m[1];for(var i=0;i<snapshots.length;i++){var s=snapshots[i];if(s.week_start<=d&&s.week_end>=d)return s;}return null;}")

    L("function showSummary(snap){var c=document.getElementById('preview-content');if(!snap){c.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#128200;</div>No data</div>\";return;}var emRes=snap.cryoem_avg_res||'-';var xrRes=snap.xray_avg_res||'-';c.innerHTML=\"<div class='report-meta'>\"+\"<div class='mr'><span class='ml'>Week</span><span class='mv'>\"+snap.week_id+\"</span></div>\"+\"<div class='mr'><span class='ml'>Period</span><span class='mv'>\"+snap.week_start+\" -> \"+snap.week_end+\"</span></div>\"+\"<div class='mr'><span class='ml'>Total</span><span class='mv'>\"+(snap.total_structures||0)+\"</span></div>\"+\"<div class='mr'><span class='ml'>Cryo-EM</span><span class='mv' style='color:var(--primary)'>\"+(snap.cryoem_count||0)+\" <span style='color:var(--muted)'>(Avg:\"+emRes+\" A)</span></span></div>\"+\"<div class='mr'><span class='ml'>X-ray</span><span class='mv' style='color:var(--secondary)'>\"+(snap.xray_count||0)+\" <span style='color:var(--muted)'>(Avg:\"+xrRes+\" A)</span></span></div>\"+\"</div>\";} ")

    L("function showFullReport(name){if(!name)return;var c=document.getElementById('preview-content');c.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#8987;</div>Loading...</div>\";fetch('/api/report?name='+encodeURIComponent(name)).then(function(res){return res.text();}).then(function(md){c.innerHTML=\"<div class='md-content'>\"+renderMD(md)+\"</div>\";}).catch(function(){c.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#9888;</div>Failed</div>\";});}")

    L("function onReportClick(name,item){activeReport=name;document.querySelectorAll('.report-item').forEach(function(i){i.classList.remove('active');});item.classList.add('active');document.getElementById('preview-panel').classList.remove('hidden');document.getElementById('preview-title').textContent=name;switchTab('summary');}")

    L("function closePreview(){activeEvalId=null;activeReport=null;currentEvalStructures=[];currentEvalData=null;currentBlastResults=[];document.getElementById('preview-panel').classList.add('hidden');}")

    L("function renderReportList(files){console.log('renderReportList called with',files?files.length:'null','files, allReports.length='+allReports.length);var list=document.getElementById('report-list');if(!files||!files.length){list.innerHTML=\"<div class='report-empty'>No PDB reports</div>\";return;}list.innerHTML='';files.forEach(function(f){var dm=f.name.match(/(\\d{4}-\\d{2}-\\d{2})/);var item=document.createElement('div');item.className='report-item';item.innerHTML=\"<div class='rname'>\"+escHtml(f.name)+\"</div><div class='rtitle'>\"+(f.title||'')+\"</div><div class='rdate'>\"+(dm?dm[1]:'')+\"</div>\";item.onclick=(function(n,it){return function(){onReportClick(n,it);};})(f.name,item);list.appendChild(item);});}")

    L("function renderReportListInDiv(files,container){console.log('renderReportListInDiv called with',files?files.length:'null','files');if(!container)return;if(!files||!files.length){container.innerHTML=\"<div class='report-empty' style='padding:10px;font-size:11px;'>No reports</div>\";return;}var html=\"<div style='font-size:11px;color:var(--primary);margin-bottom:8px;'>Reports</div><div style='display:flex;flex-direction:column;gap:4px;'>\";files.forEach(function(f){var dm=f.name.match(/(\\d{4}-\\d{2}-\\d{2})/);var dateStr=dm?dm[1]:'';html+=\"<div class='report-item' style='padding:8px 10px;font-size:11px;cursor:pointer;border-radius:6px;background:var(--bg);border:1px solid var(--border);transition:all 0.15s;'><div style='font-size:10px;color:var(--primary);'>\"+escHtml(f.title||f.name)+\"</div><div style='font-size:9px;color:var(--muted);margin-top:2px;'>\"+dateStr+\"</div></div>\";});html+=\"</div>\";container.innerHTML=html;var items=container.querySelectorAll('.report-item');items.forEach(function(item,idx){item.onclick=function(){items.forEach(function(i){i.classList.remove('active');});item.classList.add('active');var modal=document.getElementById('report-modal');if(modal){var title=document.getElementById('modal-title');var body=document.getElementById('modal-body');if(title)title.textContent=files[idx].name;if(body){body.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#8987;</div>Loading...</div>\";fetch('/api/report?name='+encodeURIComponent(files[idx].name)).then(function(res){return res.text();}).then(function(md){body.innerHTML=\"<div class='md-content'>\"+renderMD(md)+\"</div>\";}).catch(function(){body.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#9888;</div>Failed</div>\";});}modal.classList.add('show');}else{showFullReport(files[idx].name);}};});}")

    # FIXED renderMD: use [\s\S] instead of . to match any char including newlines
    L("function renderMD(md){var h=md.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');")
    L("h=h.replace(/```([\\s\\S]*?)```/g,'<pre><code>$1</code></pre>');")
    L("h=h.replace(/`([^`]+)`/g,'<code>$1</code>');")
    L("h=h.replace(/^### (.+)$/gm,'<h3>$1</h3>');")
    L("h=h.replace(/^## (.+)$/gm,'<h2>$1</h2>');")
    L("h=h.replace(/^# (.+)$/gm,'<h1>$1</h1>');")
    L("h=h.replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>');")
    L("h=h.replace(/^- (.+)$/gm,'<li>$1</li>');")
    L("h=h.replace(/(<li>[\\s\\S]*?<\\/li>)+/g,'<ul>$&</ul>');")
    L("h=h.replace(/^\\|.*\\|\\s*$/gm,function(row){var cells=row.split('|').slice(1,-1);var isSeparator=cells.every(function(c){return /^\\s*[-:]+\\s*$/.test(c);});if(isSeparator)return'';var htmlCells=cells.map(function(c){return'<td>'+c.trim()+'</td>';}).join('');return'<tr>'+htmlCells+'</tr>';});")
    L("h=h.replace(/(<tr>[\\s\\S]*?<\\/tr>\\s*)+/g,'<table class=\\'md-table\\'>$&</table>');")
    L("h=h.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');")
    L("h=h.replace(/\\*(.+?)\\*/g,'<em>$1</em>');")
    L("h=h.replace(/\\n\\n+/g,'</p><p>');")
    L("return '<p>'+h+'</p>'.replace(/<p>\\s*<\\/p>/g,'');}")
    L('var allEvalReports=[];')
    L('async function loadEvalReports(){try{var data=await fetch("/api/evaluation/reports/list").then(function(r){return r.json();});allEvalReports=data;renderEvalReports();}catch(e){allEvalReports=[];renderEvalReports();}}')
    L('function renderEvalReports(){if(!activeEvalId)return;var list=document.getElementById("preview-content");var entryReports=allEvalReports.filter(function(r){return r.uniprot_id===activeEvalId;});if(!entryReports.length){list.innerHTML="<div class=\'preview-empty\'><div class=\'preview-empty-icon\'>&#128196;</div>No evaluation report for this entry</div>";return;}var html="<div style=\'padding:14px;\'><h3 style=\'margin:0 0 10px;font-size:12px;color:var(--primary);border-bottom:1px solid var(--border);padding-bottom:6px;\'>Evaluation Reports</h3><div style=\'display:flex;flex-direction:column;gap:6px;\'>";entryReports.forEach(function(r){var isActive=activeEvalMdReport===r.uniprot_id;var dateStr=r.created?r.created.substring(0,10):\'\';html+="<div class=\'report-item\'"+(isActive?" active":"")+" data-uid=\'"+r.uniprot_id+"\' onclick=\'onEvalMdReportClick(this)\' style=\'padding:8px 10px;font-size:11px;cursor:pointer;border-radius:6px;background:var(--bg);border:1px solid var(--border);transition:all 0.15s;\'><div style=\'font-family:var(--mono);color:var(--secondary);font-size:10px;font-weight:600;\'>"+escHtml(dateStr)+"</div><div style=\'font-size:10px;color:var(--text);margin-top:3px;\'>"+escHtml(r.title||\'\')+"</div><div style=\'font-size:9px;color:var(--muted);margin-top:2px;\'>"+r.uniprot_id+"</div></div>";});html+="</div></div>";list.innerHTML=html;}')

    L('function renderEvalReportsInDiv(container){if(!activeEvalId||!container)return;var entryReports=allEvalReports.filter(function(r){return r.uniprot_id===activeEvalId;});if(!entryReports.length){container.innerHTML="<div class=\'report-empty\' style=\'padding:10px;font-size:11px;\'>No evaluation reports</div>";return;}var html="<div style=\'font-size:11px;color:var(--primary);margin-bottom:8px;\'>Evaluation Reports</div><div style=\'display:flex;flex-direction:column;gap:6px;\'>";entryReports.forEach(function(r){var dateStr=r.created?r.created.substring(0,10):\'\';html+="<div class=\'report-item\' data-uid=\'"+r.uniprot_id+"\' onclick=\'onEvalMdReportClick(this)\' style=\'padding:8px 10px;font-size:11px;cursor:pointer;border-radius:6px;background:var(--bg);border:1px solid var(--border);transition:all 0.15s;\'><div style=\'font-family:var(--mono);color:var(--secondary);font-size:10px;font-weight:600;\'>"+escHtml(dateStr)+"</div><div style=\'font-size:10px;color:var(--primary);margin-top:3px;\'>"+escHtml(r.title||\'\')+"</div></div>";});html+="</div>";container.innerHTML=html;}')

    L("function onEvalMdReportClick(el){var uid=el.getAttribute('data-uid');if(!uid)return;activeEvalMdReport=uid;var reportsDiv=document.getElementById('eval-reports-under');if(reportsDiv)renderEvalReportsInDiv(reportsDiv);var modal=document.getElementById('report-modal');var body=document.getElementById('modal-body');var title=document.getElementById('modal-title');title.textContent='Eval Report: '+uid;body.innerHTML=\"<div class=\\\"preview-empty\\\"><div class=\\\"preview-empty-icon\\\">&#8987;</div>Loading...</div>\";modal.classList.add('show');fetch('/api/evaluation/report?uniprot='+encodeURIComponent(uid)).then(function(res){return res.text();}).then(function(md){body.innerHTML=\"<div class=\\\"md-content\\\">\"+renderMD(md)+\"</div>\";}).catch(function(){body.innerHTML=\"<div class=\\\"preview-empty\\\"><div class=\\\"preview-empty-icon\\\">&#9888;</div>Failed to load</div>\";});}")
    L('window.onEvalMdReportClick=onEvalMdReportClick;')



    L("document.getElementById('sel-week').onchange=function(){var wid=this.value;if(wid==='all'){onWeekClick(null,null);}else{var cards=document.querySelectorAll('#week-list .report-item');var card=null;for(var i=0;i<cards.length;i++){if(cards[i].dataset.wid===wid){card=cards[i];break;}}onWeekClick(wid,card);}};")
    L("document.getElementById('sel-method').onchange=function(){activeMethod=this.value;loadEntries();};")
    L("document.getElementById('btn-search').onclick=function(){activeSearch=document.getElementById('inp-search').value.trim();loadEntries();};")
    L("document.getElementById('inp-search').onkeydown=function(e){if(e.key==='Enter'){activeSearch=this.value.trim();loadEntries();}};")
    L("document.getElementById('btn-reset').onclick=function(){activeWeek=null;activeMethod='all';activeSearch='';sortCol='release_date';sortAsc=false;document.getElementById('sel-week').value='all';document.getElementById('sel-method').value='all';document.getElementById('inp-search').value='';document.querySelectorAll('#week-list .report-item').forEach(function(c){c.classList.remove('active');});document.querySelectorAll('#table-head th').forEach(function(t){t.dataset.sorted='false';t.querySelector('.sort-arrow').innerHTML='&#8645;';});var oldReportsDiv=document.getElementById('week-reports');if(oldReportsDiv)oldReportsDiv.remove();document.getElementById('back-button-container').style.display='none';renderReportList([]);allEntries=[];renderTable([]);};")
    L("document.getElementById('btn-back').onclick=function(){activeWeek=null;document.querySelectorAll('#week-list .report-item').forEach(function(c){c.style.display='';c.classList.remove('active');});var oldReportsDiv=document.getElementById('week-reports');if(oldReportsDiv)oldReportsDiv.remove();document.getElementById('back-button-container').style.display='none';document.getElementById('sel-week').value='all';loadEntries();};")
    L("document.getElementById('btn-close').onclick=closePreview;")
    L("document.querySelectorAll('.preview-tab').forEach(function(t){t.onclick=(function(tab){return function(){switchTab(tab);};})(t.getAttribute('data-tab'));});")

    L("var currentMode='weekly';var activeEvalId=null;var activeEvalSearch='';var currentEvalStructures=[];var currentEvalData=null;var currentBlastResults=[];")
    L("function setMode(mode){currentMode=mode;activeEvalId=null;currentEvalStructures=[];currentBlastResults=[];activeEvalMethod='all';activeEvalPdbSearch='';filteredEvalStructures=[];document.getElementById('btn-mode-weekly').classList.toggle('active',mode==='weekly');document.getElementById('btn-mode-eval').classList.toggle('active',mode==='eval');document.getElementById('btn-mode-weekly').style.background=mode==='weekly'?'rgba(6,182,212,0.12)':'var(--card)';document.getElementById('btn-mode-weekly').style.color=mode==='weekly'?'var(--primary)':'var(--muted)';document.getElementById('btn-mode-weekly').style.borderColor=mode==='weekly'?'rgba(6,182,212,0.4)':'var(--border)';document.getElementById('btn-mode-eval').style.background=mode==='eval'?'rgba(139,92,246,0.12)':'var(--card)';document.getElementById('btn-mode-eval').style.color=mode==='eval'?'var(--secondary)':'var(--muted)';document.getElementById('btn-mode-eval').style.borderColor=mode==='eval'?'rgba(139,92,246,0.4)':'var(--border)';document.getElementById('sidebar-weeks-header').style.display=mode==='weekly'?'block':'none';document.getElementById('week-list').style.display=mode==='weekly'?'flex':'none';document.getElementById('eval-sidebar').style.display=mode==='eval'?'flex':'none';document.getElementById('weekly-toolbar').style.display=mode==='eval'?'none':'flex';document.getElementById('eval-toolbar-main').style.display=mode==='eval'?'flex':'none';document.getElementById('weekly-table').style.display='block';var weekReportsDiv=document.getElementById('week-reports');if(weekReportsDiv)weekReportsDiv.style.display='none';var evalReportsDiv=document.getElementById('eval-reports-under');if(evalReportsDiv)evalReportsDiv.style.display='none';document.getElementById('eval-back-container').style.display='none';document.getElementById('back-button-container').style.display='none';var weekRep=document.getElementById('week-reports');if(weekRep)weekRep.remove();if(mode==='weekly'){activeWeek=null;document.getElementById('preview-panel').classList.add('hidden');document.getElementById('table-body').removeAttribute('data-eval-table');document.querySelectorAll('#week-list .report-item').forEach(function(c){c.style.display='';c.classList.remove('active');});document.getElementById('sel-week').value='all';renderTable(sortEntries(allEntries.slice()));}else{document.getElementById('sel-eval-main-method').value='all';document.getElementById('inp-eval-search').value='';document.getElementById('preview-panel').classList.add('hidden');closePreview();renderEvalTable([],[]);loadEvalList();}}")

    L("function renderEvalMD(md){var h=md.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');")
    L("h=h.replace(/```([\\s\\S]*?)```/g,'<pre><code>$1</code></pre>');")
    L("h=h.replace(/`([^`]+)`/g,'<code>$1</code>');")
    L("h=h.replace(/^### (.+)$/gm,'<h3>$1</h3>');")
    L("h=h.replace(/^## (.+)$/gm,'<h2>$1</h2>');")
    L("h=h.replace(/^# (.+)$/gm,'<h1>$1</h1>');")
    L("h=h.replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>');")
    L("h=h.replace(/^- (.+)$/gm,'<li>$1</li>');")
    L("h=h.replace(/(<li>[\\s\\S]*?<\\/li>)+/g,'<ul>$&</ul>');")
    L("h=h.replace(/^\\|.*\\|\\s*$/gm,function(row){var cells=row.split('|').slice(1,-1);var isSeparator=cells.every(function(c){return /^\\s*[-:]+\\s*$/.test(c);});if(isSeparator)return'';var htmlCells=cells.map(function(c){return'<td>'+c.trim()+'</td>';}).join('');return'<tr>'+htmlCells+'</tr>';});")
    L("h=h.replace(/(<tr>[\\s\\S]*?<\\/tr>\\s*)+/g,'<table class=\\'md-table\\'>$&</table>');")
    L("h=h.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');")
    L("h=h.replace(/\\*(.+?)\\*\\*/g,'<em>$1</em>');")
    L("h=h.replace(/\\n\\n+/g,'</p><p>');")
    L("return '<p>'+h+'</p>'.replace(/<p>\\s*<\\/p>/g,'');}")

    L("async function loadEvalList(){console.log('loadEvalList called, search=',activeEvalSearch);var q=encodeURIComponent(activeEvalSearch);var url='/api/evaluations';if(q)url+='?q='+q;try{var evals=await fetch(url).then(function(r){return r.json();});renderEvalList(evals);}catch(e){renderEvalList([]);}}")

    L("function renderEvalList(evals){var list=document.getElementById('eval-list');if(!evals||!evals.length){list.innerHTML=\"<div class='report-empty' style='font-size:11px;'>\"+(activeEvalSearch?'无匹配结果':'暂无评估记录')+\"</div>\";return;}list.innerHTML='';evals.forEach(function(e){var item=document.createElement('div');item.className='report-item'+(activeEvalId===e.uniprot_id?' active':'');item.dataset.uid=e.uniprot_id;var scores=e.scores||{};var bestScore=0;for(var m in scores)if(scores[m].score>bestScore)bestScore=scores[m].score;var scoreColor=bestScore>=7?'var(--success)':bestScore>=5?'var(--accent)':'var(--danger)';item.innerHTML=\"<div class='rname' style='font-size:11px;'><span style='font-family:var(--mono);color:var(--accent);'>\"+e.uniprot_id+\"</span> <span style='font-size:9px;color:\"+scoreColor+\";'>\"+bestScore+\"</span></div><div class='rtitle' style='font-size:10px;'>\"+escHtml(e.protein_name||'')+\"</div><div class='rdate' style='font-size:9px;color:var(--muted);'>\"+e.gene_name+\"</div>\";item.onclick=(function(uid){return function(){onEvalClick(uid);};})(e.uniprot_id);list.appendChild(item);});}")

    L("document.getElementById('btn-modal-close').onclick=function(){document.getElementById('report-modal').classList.remove('show');};")
    L("document.getElementById('report-modal').onclick=function(e){if(e.target===this)document.getElementById('report-modal').classList.remove('show');};")

    L("async function onEvalClick(uniprotId){activeEvalId=uniprotId;activeEvalMethod='all';activeEvalPdbSearch='';document.getElementById('sel-eval-main-method').value='all';document.getElementById('inp-eval-search').value='';var oldReportsDiv=document.getElementById('eval-reports-under');if(oldReportsDiv){oldReportsDiv.remove();}var list=document.getElementById('eval-list');var items=list.querySelectorAll('.report-item');var selectedItem=null;items.forEach(function(i){if(i.dataset.uid===uniprotId){i.classList.add('active');i.style.display='';selectedItem=i;}else{i.classList.remove('active');i.style.display='none';}});if(selectedItem&&selectedItem!==list.firstChild){list.insertBefore(selectedItem,list.firstChild);}document.getElementById('eval-back-container').style.display='block';try{var data=await fetch('/api/evaluations/'+encodeURIComponent(uniprotId)).then(function(r){return r.json();});if(data.error){currentEvalData=null;currentEvalStructures=[];filteredEvalStructures=[];currentBlastResults=[];renderEvalTable([],[]);return;}currentEvalData=data;var rawStructures=data.pdb_structures||[];currentEvalStructures=rawStructures.map(function(s,i){s._origIdx=i;return s;});currentBlastResults=data.blast_results||[];filteredEvalStructures=currentEvalStructures.slice();renderEvalTable(filteredEvalStructures,currentBlastResults);activeEvalMdReport=null;await loadEvalReports();var reportsDiv=document.createElement('div');reportsDiv.id='eval-reports-under';reportsDiv.className='eval-reports-under';reportsDiv.style.cssText='padding:8px 10px;border-top:1px solid var(--border);background:var(--card);margin-top:4px;';if(selectedItem){selectedItem.insertAdjacentElement('afterend',reportsDiv);}renderEvalReportsInDiv(reportsDiv);reportsDiv.style.display='block';}catch(e){currentEvalData=null;currentEvalStructures=[];filteredEvalStructures=[];currentBlastResults=[];renderEvalTable([],[]);}}")

    
    
    
    L("function renderEvalTable(structures,blastResults){var tbody=document.getElementById('table-body');tbody.setAttribute('data-eval-table','true');var allStructuresForLookup=[];var blastMap={};if(blastResults&&blastResults.length){for(var i=0;i<blastResults.length;i++){var b=blastResults[i];if(b.pdb_id){blastMap[b.pdb_id.toUpperCase()]=b;}}}var totalCount=structures.length+Object.keys(blastMap).length;document.getElementById('eval-entry-count').textContent=totalCount+' PDB structures';if(!structures.length&&!blastResults.length){tbody.innerHTML=\"<tr><td colspan='7'><div class='preview-empty'><div class='preview-empty-icon'>&#128269;</div>No PDB structures</div></td></tr>\";return;}var html=[];var idxCounter=0;for(var i=0;i<structures.length;i++){var s=structures[i];s._origIdx=idxCounter++;allStructuresForLookup.push(s);var pdbId=typeof s==='string'?s:(s.pdb_id||'');var method=typeof s==='string'?'':(s.method||'');var res=typeof s==='string'?null:s.resolution;var title=typeof s==='string'?'':(s.title||'');var releaseDate=typeof s==='string'?'':(s.release_date||'');var ligand=typeof s==='string'?'':(s.ligand||s.ligands||'');var journalIf=typeof s==='string'?null:(s.journal_if||s.if||null);var ifTier=typeof s==='string'?'':(s.if_tier||'');var journal=typeof s==='string'?'':(s.journal||'');var bClass='badge-oth',mLabel=method;var mLower=method.toLowerCase();if(/electron crystallography/i.test(mLower)){bClass='badge-em';mLabel='ELECTRON CRYSTALLOGRAPHY';}else if(/electron microscopy|cryo/i.test(mLower)){bClass='badge-em';mLabel='Cryo-EM';}else if(/x-ray/i.test(mLower)){bClass='badge-xr';mLabel='X-ray';}else if(/nmr/i.test(mLower)){bClass='badge-nmr';mLabel='NMR';}var rClass='res-mid',rStr='-';if(res!=null&&!isNaN(res)&&res>0){rClass=res<=2.0?'res-good':res>3.5?'res-poor':'res-mid';rStr=Number(res).toFixed(2);}var tierBadge=(ifTier&&ifTier!=='unknown')?\"<span class='if-badge tier-\"+ifTier+\"'>\"+ifTier.toUpperCase()+\"</span>\":'';var ifNum=parseFloat(journalIf);var hasValidIf=journalIf!=null&&String(journalIf).trim()!==''&&String(journalIf).toLowerCase()!=='unknown'&&!isNaN(ifNum)&&ifNum>0;var ifVal=hasValidIf?\" <span class='if-val'>IF \"+ifNum.toFixed(1)+\"</span>\":\" <span class='if-val'>To be published</span>\";var ligs=ligand?(ligand.split(/[;|,]/).map(function(l){var trimmed=l.trim();var colonIdx=trimmed.indexOf(':');return colonIdx>0?trimmed.substring(0,colonIdx):trimmed;}).filter(Boolean)):[];var ligHtml='-';if(ligs.length){var chips=[];for(var li=0;li<ligs.length;li++){chips.push(\"<span class='lig-chip' data-lig='\"+escHtml(ligs[li])+\"' data-idx='\"+s._origIdx+\"'>\"+escHtml(ligs[li])+\"</span>\");}ligHtml=chips.join(' ');}var titleShort=title.substring(0,80);html.push(\"<tr><td><span class='pdb-link' data-idx='\"+s._origIdx+\"' data-pdb='\"+escHtml(pdbId)+\"' style='font-family:var(--mono);font-weight:700;color:var(--primary);cursor:pointer;font-size:12px;'>\"+escHtml(pdbId)+\"</span></td><td><span class='method-badge \"+bClass+\"'>\"+escHtml(mLabel)+\"</span></td><td><span class='res \"+rClass+\"'>\"+(rStr!=='-'?rStr+' A':'-')+\"</span></td><td>\"+tierBadge+ifVal+\"</td><td class='title-cell' title='\"+escHtml(title)+\"'>\"+escHtml(titleShort||'-')+\"</td><td>\"+(releaseDate||'-')+\"</td><td class='lig-cell'>\"+ligHtml+\"</td></tr>\");}if(blastResults&&blastResults.length){for(var j=0;j<blastResults.length;j++){var b=blastResults[j];b._origIdx=idxCounter++;allStructuresForLookup.push(b);var pdbId=b.pdb_id||'';if(!pdbId)continue;var method=b.method||'';var res=b.resolution||null;var title=b.title||b.description||'';var releaseDate=b.release_date||'';var ligand=b.ligand||b.ligands||'';var journalIf=b.journal_if||b.if||null;var ifTier=b.if_tier||'';var bClass='badge-oth',mLabel=method;var mLower=method.toLowerCase();if(/electron crystallography/i.test(mLower)){bClass='badge-em';mLabel='ELECTRON CRYSTALLOGRAPHY';}else if(/electron microscopy|cryo/i.test(mLower)){bClass='badge-em';mLabel='Cryo-EM';}else if(/x-ray/i.test(mLower)){bClass='badge-xr';mLabel='X-ray';}else if(/nmr/i.test(mLower)){bClass='badge-nmr';mLabel='NMR';}var rClass='res-mid',rStr='-';if(res!=null&&!isNaN(res)&&res>0){rClass=res<=2.0?'res-good':res>3.5?'res-poor':'res-mid';rStr=Number(res).toFixed(2);}var tierBadge=(ifTier&&ifTier!=='unknown')?\"<span class='if-badge tier-\"+ifTier+\"'>\"+ifTier.toUpperCase()+\"</span>\":'';var ifNum=parseFloat(journalIf);var hasValidIf=journalIf!=null&&String(journalIf).trim()!==''&&String(journalIf).toLowerCase()!=='unknown'&&!isNaN(ifNum)&&ifNum>0;var ifVal=hasValidIf?\" <span class='if-val'>IF \"+ifNum.toFixed(1)+\"</span>\":\" <span class='if-val'>To be published</span>\";var ligs=ligand?(ligand.split(/[;|,]/).map(function(l){var trimmed=l.trim();var colonIdx=trimmed.indexOf(':');return colonIdx>0?trimmed.substring(0,colonIdx):trimmed;}).filter(Boolean)):[];var ligHtml='-';if(ligs.length){var chips=[];for(var li=0;li<ligs.length;li++){chips.push(\"<span class='lig-chip' data-lig='\"+escHtml(ligs[li])+\"' data-idx='\"+b._origIdx+\"'>\"+escHtml(ligs[li])+\"</span>\");}ligHtml=chips.join(' ');}var identityRaw=b.identity||0;var identityPct=b.query_coverage>0?Math.round((identityRaw/b.query_coverage)*100):identityRaw;var identity=identityPct>100?100:identityPct;var evalue=b.evalue!=null?b.evalue.toExponential(1):'-';var qcov=b.query_coverage||0;var seqLen=currentEvalData&&currentEvalData.uniprot?currentEvalData.uniprot.sequence_length:0;var covPercent=seqLen>0?Math.round((qcov/seqLen)*100)+'%':'N/A';var badgeDataAttrs=\"data-blast-pdb='\"+escHtml(pdbId)+\"' data-identity='\"+identity+\"' data-evalue='\"+b.evalue+\"' data-qcov='\"+qcov+\"' data-seq-len='\"+seqLen+\"' data-method='\"+escHtml(method)+\"' data-res='\"+(res||'')+\"' data-title='\"+escHtml(title)+\"'\";html.push(\"<tr class='blast-row'><td><span class='pdb-link blast-homolog-link' data-idx='\"+b._origIdx+\"' data-pdb='\"+escHtml(pdbId)+\"' style='font-family:var(--mono);font-weight:700;color:var(--secondary);cursor:pointer;font-size:12px;'>\"+escHtml(pdbId)+\"</span> <span class='homolog-badge' \"+badgeDataAttrs+\">Homolog</span></td><td><span class='method-badge \"+bClass+\"'>\"+escHtml(mLabel)+\"</span></td><td><span class='res \"+rClass+\"'>\"+(rStr!=='-'?rStr+' A':'-')+\"</span></td><td>\"+tierBadge+ifVal+\"</td><td class='title-cell' title='\"+escHtml(title)+\"'>\"+escHtml(title.substring(0,80))+\"</td><td>\"+(releaseDate||'-')+\"</td><td class='lig-cell'>\"+ligHtml+\"</td></tr>\");}}currentEvalStructures=allStructuresForLookup;tbody.innerHTML=html.join('');}")



    L("function showEvalPreview(data){currentEvalData=data;document.getElementById('preview-panel').classList.remove('hidden');document.getElementById('preview-title').textContent=data?data.uniprot_id:'—';showEvalSummary();switchTab('summary');}")
    L("function showEvalSummary(){var data=currentEvalData;var c=document.getElementById('preview-content');if(!data){c.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#9888;</div>Failed to load</div>\";return;}var covColor=data.coverage>=50?'var(--success)':'var(--accent)';var uniprot=data.uniprot||{};var scores=data.scores||{};var scoresHtml='';for(var method in scores){var info=scores[method];var pct=info.score*10;var color=info.score>=7?'var(--success)':info.score>=5?'var(--accent)':'var(--danger)';scoresHtml+='<div style=\"margin-bottom:8px;\"><div style=\"display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px;\"><span>'+method+'</span><span style=\"color:'+color+';font-weight:700;\">'+info.score+'/10 '+info.assessment+'</span></div><div style=\"height:3px;background:var(--card);border-radius:2px;\"><div style=\"height:3px;width:'+pct+'%;background:'+color+';border-radius:2px;\"></div></div></div>';}c.innerHTML=\"<div class='report-meta'>\"+'<div class=\"mr\"><span class=\"ml\">UniProt</span><span class=\"mv\"><a href=\"https://www.uniprot.org/uniprot/'+data.uniprot_id+'\" target=\"_blank\" style=\"color:var(--primary);\">'+data.uniprot_id+'</a></span></div>'+'<div class=\"mr\"><span class=\"ml\">Protein Name</span><span class=\"mv\">'+escHtml(uniprot.protein_name||'N/A')+'</span></div>'+'<div class=\"mr\"><span class=\"ml\">Gene Name</span><span class=\"mv\">'+escHtml((uniprot.gene_names||[]).join(', '))+'</span></div>'+'<div class=\"mr\"><span class=\"ml\">Organism</span><span class=\"mv\">'+escHtml(uniprot.organism||'N/A')+'</span></div>'+'<div class=\"mr\"><span class=\"ml\">Sequence Length</span><span class=\"mv\">'+(uniprot.sequence_length||0)+' aa</span></div>'+'<div class=\"mr\"><span class=\"ml\">Coverage</span><span class=\"mv\" style=\"color:'+covColor+';font-weight:700;\">'+(data.coverage||0)+'%</span></div>'+'<div class=\"mr\"><span class=\"ml\">PDB Structures</span><span class=\"mv\">'+(data.pdb_structures||[]).length+'</span></div>'+'</div>'+'<h3 style=\"margin:10px 0 6px;font-size:12px;color:var(--primary);\">Feasibility Score</h3><div style=\"padding:6px;background:var(--card);border-radius:6px;margin-bottom:8px;\">'+scoresHtml+'</div>';}")
    L("function showEvalFullReport(){var data=currentEvalData;var c=document.getElementById('preview-content');if(!data){c.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#9888;</div>No data</div>\";return;}var reportContent=(typeof data==='string')?data:(data.report||'');if(!reportContent){c.innerHTML=\"<div class='preview-empty'><div class='preview-empty-icon'>&#9888;</div>No full report available</div>\";return;}c.innerHTML=\"<div class='md-content'>\"+renderEvalMD(reportContent)+'</div>';}")

    L("var evalSearchTimer=null;document.getElementById('eval-search').addEventListener('input',function(e){clearTimeout(evalSearchTimer);evalSearchTimer=setTimeout(function(){activeEvalSearch=e.target.value.trim();loadEvalList();},300);});document.getElementById('eval-search').addEventListener('keydown',function(e){if(e.key==='Enter'){clearTimeout(evalSearchTimer);activeEvalSearch=e.target.value.trim();loadEvalList();loadEvalReports();}});")
    L("function sortEvalStructures(arr){var copy=arr.slice();for(var si=0;si<copy.length;si++){if(copy[si]._origIdx==null)copy[si]._origIdx=si;}return copy.sort(function(a,b){var col=sortCol;var av=a[col],bv=b[col];if(col==='journal_if'||col==='if'){av=(av==null||String(av).trim()===''||String(av).toLowerCase()==='unknown')?0:parseFloat(av);bv=(bv==null||String(bv).trim()===''||String(bv).toLowerCase()==='unknown')?0:parseFloat(bv);return sortAsc?(av-bv):(bv-av);}if(col==='resolution'){av=(av==null||String(av).trim()===''||isNaN(parseFloat(av)))?999:parseFloat(av);bv=(bv==null||String(bv).trim()===''||isNaN(parseFloat(bv)))?999:parseFloat(bv);return sortAsc?(av-bv):(bv-av);}var an=parseFloat(av),bn=parseFloat(bv);var aNum=(av!=null&&String(av).trim()!==''&&!isNaN(an));var bNum=(bv!=null&&String(bv).trim()!==''&&!isNaN(bn));var cmp;if(aNum&&bNum){cmp=an-bn;}else if(aNum){cmp=-1;}else if(bNum){cmp=1;}else{cmp=String(av||'').localeCompare(String(bv||''));}return sortAsc?cmp:-cmp;});}")
    L("document.getElementById('btn-mode-weekly').onclick=function(){setMode('weekly');};")
    L("document.getElementById('btn-mode-eval').onclick=function(){setMode('eval');};")
    L("document.getElementById('btn-eval-back').onclick=function(){activeEvalId=null;document.querySelectorAll('#eval-list .report-item').forEach(function(i){i.style.display='';i.classList.remove('active');});document.getElementById('eval-back-container').style.display='none';var reportsDiv=document.getElementById('eval-reports-under');if(reportsDiv){reportsDiv.remove();}renderEvalTable([],[]);};")
    L("var activeEvalMethod='all';var activeEvalPdbSearch='';var filteredEvalStructures=[];")
    L("function filterEvalStructures(){if(!currentEvalStructures)return [];var filtered=currentEvalStructures.slice();if(activeEvalMethod!=='all'){filtered=filtered.filter(function(s){var m=(s.method||'').toLowerCase();if(activeEvalMethod==='cryoem')return /electron microscopy|cryo(?!.*crystallography)/i.test(m);if(activeEvalMethod==='electron_crystallography')return /electron crystallography/i.test(m);if(activeEvalMethod==='xray')return /x-ray|xray/i.test(m);if(activeEvalMethod==='nmr')return /nmr/i.test(m);return true;});}if(activeEvalPdbSearch){var q=activeEvalPdbSearch.toLowerCase();filtered=filtered.filter(function(s){var pdbId=(s.pdb_id||'').toLowerCase();var title=(s.title||'').toLowerCase();return pdbId.indexOf(q)>=0||title.indexOf(q)>=0;});}return filtered;}")
    L("function renderBlastHomologs(blastResults){\nvar section=document.getElementById('blast-homologs-section');\nif(!blastResults||!blastResults.length){section.classList.remove('visible');section.innerHTML='';return;}\nsection.classList.add('visible');\nvar html='<div class=\"blast-section-header\">&#128279; \u540c\u6e90\u86cb\u767d (BLAST)<span class=\"blast-count-badge\">'+blastResults.length+'</span></div>';\nhtml+='<div class=\"blast-table-container\"><table class=\"blast-table\"><thead><tr><th>PDB</th><th>Method</th><th>Res</th><th>IF</th><th>Identity</th><th>E-value</th><th>Description</th></tr></thead><tbody>';\nfor(var i=0;i<blastResults.length;i++){\nvar b=blastResults[i];\nvar pdbId=escHtml(b.pdb_id||'-');\nvar method=escHtml(b.method||'-');\nvar res=b.resolution!=null?b.resolution.toFixed(1)+' ':'-';\nvar jif=b.journal_if?'<span class=\"if-badge\">'+b.journal_if.toFixed(1)+'</span>':'-';\nvar identityRaw=b.identity||0;var identityPct=b.query_coverage>0?Math.round((identityRaw/b.query_coverage)*100):identityRaw;var identity=identityPct>100?100:identityPct;\nvar evalue=b.evalue!=null?b.evalue.toExponential(1):'-';\nvar desc=escHtml((b.title||b.title||b.description||'').substring(0,80));\nvar idClass=identity>=70?'high':identity>=40?'mid':'low';\nhtml+='<tr>';\nhtml+='<td><span class=\"blast-pdb-link\" data-pdb=\"'+pdbId+'\">'+pdbId+'</span> <span class=\"homolog-badge\">\u540c\u6e90</span></td>';\nhtml+='<td class=\"blast-method\">'+method+'</td>';\nhtml+='<td class=\"blast-res\">'+res+'</td>';\nhtml+='<td class=\"blast-if\">'+jif+'</td>';\nhtml+='<td><span class=\"blast-identity '+idClass+'\">'+identity+'</span></td>';\nhtml+='<td><span class=\"blast-evalue\">'+evalue+'</span></td>';\nhtml+='<td class=\"blast-desc\" title=\"'+escHtml(b.title||b.description||'')+'\">'+desc+'</td>';\nhtml+='</tr>';\n}\nhtml+='</tbody></table></div>';\nsection.innerHTML=html;\nsection.querySelectorAll('.blast-pdb-link').forEach(function(el){el.onclick=function(){var pdb=el.getAttribute('data-pdb');if(pdb)showPdbPreview(pdb);};});\n}");
    L("function applyEvalFilters(){filteredEvalStructures=filterEvalStructures();renderEvalTable(filteredEvalStructures,currentBlastResults);}")
    L("document.getElementById('sel-eval-main-method').onchange=function(){activeEvalMethod=this.value;applyEvalFilters();};")
    L("document.getElementById('btn-eval-main-search').onclick=function(){activeEvalPdbSearch=document.getElementById('inp-eval-search').value.trim();applyEvalFilters();};")
    L("document.getElementById('inp-eval-search').onkeydown=function(e){if(e.key==='Enter'){activeEvalPdbSearch=this.value.trim();applyEvalFilters();}};")
    L("document.getElementById('btn-eval-main-reset').onclick=function(){activeEvalMethod='all';activeEvalPdbSearch='';document.getElementById('sel-eval-main-method').value='all';document.getElementById('inp-eval-search').value='';applyEvalFilters();};")
    L("document.getElementById('btn-modal-close').onclick=function(){document.getElementById('report-modal').classList.remove('show');};")
    L("document.getElementById('report-modal').onclick=function(e){if(e.target===this)document.getElementById('report-modal').classList.remove('show');};")
    L("init().then(function(){setMode('weekly');});")
    L("})();")

    with open(SCRIPT_DIR / "pdb_app.js", 'w', encoding='utf-8') as f:
        f.writelines(lines)


def init_weekly_reports_db():
    """Create weekly_reports and evaluation_reports tables if they don't exist."""
    conn = get_eval_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_id TEXT UNIQUE,
            week_start TEXT,
            week_end TEXT,
            report_type TEXT DEFAULT 'all',
            title TEXT DEFAULT '',
            filename TEXT,
            content TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT UNIQUE,
            title TEXT DEFAULT '',
            filename TEXT,
            content TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    logging.info("[init_weekly_reports_db] tables ready")

    # Migration: import existing .md files into DB
    _migrate_weekly_reports()
    _migrate_evaluation_reports()

def _migrate_weekly_reports():
    """Import weekly .md files from summaries/ into weekly_reports DB table.
    Incremental: only imports new files not already in DB."""
    try:
        if not REPORTS_DIR.exists():
            logging.info("[_migrate_weekly_reports] summaries dir does not exist, skipping")
            return
        conn = get_eval_db()
        migrated = 0
        for f in sorted(REPORTS_DIR.glob("*.md")):
            try:
                # Check if already in DB by filename
                existing = conn.execute(
                    "SELECT id FROM weekly_reports WHERE filename = ?", (f.name,)
                ).fetchone()
                if existing:
                    continue
                # Import new file
                content = f.read_text(encoding='utf-8', errors='ignore')
                # Extract week from filename: "X射线晶体学结构周报-W16-2026-04-15.md" or "X射线晶体学结构周报-2026-04-15.md"
                week_match = re.search(r'(\d{4}-\d{2}-\d{2})', f.name)
                week_id = week_match.group(1) if week_match else f.stem
                # Determine report_type from filename
                fname_lower = f.name.lower()
                if 'cryo' in fname_lower or '冷冻' in fname_lower:
                    rtype = 'cryoem'
                elif 'x' in fname_lower and ('xray' in fname_lower or '射线' in fname_lower or '晶体' in fname_lower):
                    rtype = 'xray'
                else:
                    rtype = 'all'
                # Extract title from first H1
                h1 = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                title = h1.group(1).strip() if h1 else f.stem
                conn.execute("""
                    INSERT OR IGNORE INTO weekly_reports (week_id, title, filename, report_type, content)
                    VALUES (?, ?, ?, ?, ?)
                """, (week_id, title, f.name, rtype, content))
                migrated += 1
                logging.info(f"[_migrate_weekly_reports] imported: {f.name} -> week_id={week_id}")
            except Exception as ex:
                logging.info(f"[_migrate_weekly_reports] skip {f.name}: {ex}")
        conn.commit()
        conn.close()
        if migrated > 0:
            logging.info(f"[_migrate_weekly_reports] migrated {migrated} new weekly reports")
    except Exception as e:
        logging.error(f"[_migrate_weekly_reports] error: {e}")

def _migrate_evaluation_reports():
    """Import evaluation .md files from evaluations/ into evaluation_reports DB table.
    Idempotent: skips if evaluation_reports table already has rows with content."""
    try:
        conn = get_eval_db()
        count = conn.execute("SELECT COUNT(*) FROM evaluation_reports WHERE content IS NOT NULL AND content != ''").fetchone()[0]
        if count > 0:
            conn.close()
            logging.info(f"[_migrate_evaluation_reports] {count} reports already in DB, skipping migration")
            return
        migrated = 0
        eval_dir = EVAL_DATA_DIR
        if not eval_dir.exists():
            logging.info("[_migrate_evaluation_reports] evaluations dir does not exist, skipping")
            conn.close()
            return
        for f in sorted(eval_dir.glob("*.md")):
            try:
                # Only process evaluation report files (not .json)
                if not f.suffix == '.md':
                    continue
                content = f.read_text(encoding='utf-8', errors='ignore')
                existing = conn.execute(
                    "SELECT id FROM evaluation_reports WHERE filename = ?", (f.name,)
                ).fetchone()
                if existing:
                    continue
                # Extract uniprot_id from filename: "Q9GZU1_TRPML1_结构可行性评估.md"
                uniprot_match = re.match(r'^([A-Z0-9]+)_', f.stem)
                uniprot_id = uniprot_match.group(1) if uniprot_match else f.stem
                # Extract title from content
                h1 = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                title = h1.group(1).strip() if h1 else f.stem
                conn.execute("""
                    INSERT OR IGNORE INTO evaluation_reports (uniprot_id, title, filename, content)
                    VALUES (?, ?, ?, ?)
                """, (uniprot_id, title, f.name, content))
                migrated += 1
            except Exception as ex:
                logging.info(f"[_migrate_evaluation_reports] skip {f.name}: {ex}")
        conn.commit()
        conn.close()
        logging.info(f"[_migrate_evaluation_reports] migrated {migrated} evaluation reports")
    except Exception as e:
        logging.error(f"[_migrate_evaluation_reports] error: {e}")


# ─── Flask routes ───────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_eval_db():
    """Get a connection to the evaluation database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_blast_results_table(conn):
    """Add missing columns to evaluation_blast_results table if they don't exist."""
    try:
        cursor = conn.execute("PRAGMA table_info(evaluation_blast_results)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        columns_to_add = [
            ('target_coverage', 'INTEGER'),
            ('method', 'TEXT DEFAULT ""'),
            ('resolution', 'REAL'),
            ('release_date', 'TEXT DEFAULT ""'),
            ('journal', 'TEXT DEFAULT ""'),
            ('journal_if', 'REAL'),
            ('if_tier', 'TEXT DEFAULT "unknown"'),
            ('ligand', 'TEXT DEFAULT ""'),
            ('title', 'TEXT DEFAULT ""'),
        ]

        for col_name, col_type in columns_to_add:
            if col_name not in existing_cols:
                try:
                    conn.execute(f'ALTER TABLE evaluation_blast_results ADD COLUMN {col_name} {col_type}')
                    logging.info(f'[_migrate_blast_results_table] Added column: {col_name}')
                except Exception as e:
                    logging.warning(f'[_migrate_blast_results_table] Failed to add {col_name}: {e}')
    except Exception as e:
        logging.error(f'[_migrate_blast_results_table] Migration error: {e}')



def init_eval_db():
    """Create evaluation tables if they don't exist."""
    conn = get_eval_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            uniprot_id TEXT PRIMARY KEY,
            entry_name TEXT,
            protein_name TEXT,
            gene_names TEXT,
            organism TEXT,
            sequence_length INTEGER,
            coverage REAL DEFAULT 0,
            scores TEXT DEFAULT '{}',
            report TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_pdb_structures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            pdb_id TEXT NOT NULL,
            method TEXT DEFAULT '',
            resolution REAL,
            title TEXT DEFAULT '',
            deposition_date TEXT DEFAULT '',
            release_date TEXT DEFAULT '',
            ligand TEXT DEFAULT '',
            ligand_names TEXT DEFAULT '',
            journal TEXT DEFAULT '',
            journal_if REAL,
            doi TEXT DEFAULT '',
            pubmed_id TEXT DEFAULT '',
            organism TEXT DEFAULT '',
            authors TEXT DEFAULT '',
            is_cryoem INTEGER DEFAULT 0,
            is_xray INTEGER DEFAULT 0,
            is_nmr INTEGER DEFAULT 0,
            if_tier TEXT DEFAULT 'unknown',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (uniprot_id) REFERENCES evaluations(uniprot_id) ON DELETE CASCADE
        )
    """)
    # Unique index on (uniprot_id, pdb_id)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_pdb
        ON evaluation_pdb_structures(uniprot_id, pdb_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_blast_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id TEXT NOT NULL,
            pdb_id TEXT,
            uniprot_ref TEXT,
            description TEXT,
            identity INTEGER,
            evalue REAL,
            query_coverage INTEGER,
            target_coverage INTEGER,
            method TEXT DEFAULT '',
            resolution REAL,
            release_date TEXT DEFAULT '',
            source TEXT,
            taxonomy_id INTEGER,
            journal TEXT DEFAULT '',
            journal_if REAL,
            if_tier TEXT DEFAULT 'unknown',
            ligand TEXT DEFAULT '',
            updated_at TEXT,
            FOREIGN KEY (uniprot_id) REFERENCES evaluations(uniprot_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eval_blast_uniprot
        ON evaluation_blast_results(uniprot_id)
    """)

    # Migrate: add missing columns to evaluation_blast_results if they don't exist
    _migrate_blast_results_table(conn)

    conn.commit()
    conn.close()

    # Migration: if DB is empty but JSON files exist, import them
    try:
        conn = get_eval_db()
        count = conn.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0]
        conn.close()
        if count == 0:
            logging.info('[init_eval_db] DB empty -- migrating from JSON files...')
            import json as _json
            migrated = 0
            for f in sorted(EVAL_DATA_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    with open(f, encoding='utf-8') as fp:
                        data = _json.load(fp)
                    uid = data.get('uniprot_id')
                    if uid and save_evaluation(data):
                        migrated += 1
                except Exception as ex:
                    logging.info(f'[init_eval_db] skip {f.name}: {ex}')
            logging.info(f'[init_eval_db] migrated {migrated} evaluations from JSON')
    except Exception as e:
        logging.warning(f'[init_eval_db] migration check error (non-fatal): {e}')


@app.route("/api/snapshots")
def api_snapshots():
    conn = get_db()
    rows = conn.execute("SELECT * FROM weekly_snapshots ORDER BY week_start DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/entries")
def api_entries():
    week_id = request.args.get("week", "all")
    method = request.args.get("method", "all")
    search = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 500)), 500)
    conn = get_db()
    params = []
    if week_id != "all":
        snap = conn.execute("SELECT week_start, week_end FROM weekly_snapshots WHERE week_id = ?", (week_id,)).fetchone()
        if snap:
            q = "SELECT * FROM pdb_structures WHERE release_date BETWEEN ? AND ?"
            params = [snap["week_start"], snap["week_end"]]
            logging.info(f"[api_entries] week={week_id} date_range={snap['week_start']} to {snap['week_end']}")
        else:
            q = "SELECT * FROM pdb_structures WHERE week_id = ?"
            params = [week_id]
            logging.info(f"[api_entries] week={week_id} (fallback to week_id column)")
    else:
        q = "SELECT * FROM pdb_structures WHERE 1=1"
        logging.info(f"[api_entries] week=all (no filter)")
    if method == "cryoem":
        q += " AND is_cryoem = 1"
    elif method == "xray":
        q += " AND is_xray = 1"
    elif method == "nmr":
        q += " AND (method LIKE '%NMR%' OR method LIKE '%nuclear magnetic resonance%')"
    elif method == "electron_crystallography":
        q += " AND (method LIKE '%electron crystallography%')"
    if search:
        s = f"%{search}%"
        q += " AND (pdb_id LIKE ? OR title LIKE ? OR journal LIKE ? OR ligand_info LIKE ?)"
        params += [s, s, s, s]
    q += f" ORDER BY release_date DESC LIMIT {limit}"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    logging.info(f"[api_entries] returning {len(rows)} rows for week={week_id}")
    return jsonify([dict(r) for r in rows])

@app.route("/api/reports/list")
def api_reports_list():
    """List all weekly PDB reports from DB, optionally filtered by type."""
    report_type = request.args.get("type", "all").strip()
    try:
        conn = get_eval_db()
        if report_type in ('cryoem', 'xray', 'nmr'):
            rows = conn.execute(
                "SELECT week_id, title, filename, report_type, created_at "
                "FROM weekly_reports WHERE report_type = ? OR report_type = 'all' ORDER BY week_id DESC",
                (report_type,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT week_id, title, filename, report_type, created_at "
                "FROM weekly_reports ORDER BY week_id DESC"
            ).fetchall()
        conn.close()
        result = []
        for row in rows:
            rd = dict(row)
            result.append({
                "name": rd.get('week_id', rd.get('filename', '')),
                "file": rd.get('filename', ''),
                "title": rd.get('title', ''),
                "type": rd.get('report_type', ''),
                "created": rd.get('created_at', ''),
            })
        logging.info(f"[api_reports_list] returning {len(result)} weekly reports")
        return jsonify(result)
    except Exception as e:
        logging.error(f"[api_reports_list] error: {e}")
        return jsonify([])

@app.route("/api/report")
def api_report():
    """Get a weekly PDB report by name (week_id or filename stem). Reads from DB."""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        conn = get_eval_db()
        # Escape LIKE wildcards in name to prevent injection
        safe_name = name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        row = conn.execute(
            "SELECT content FROM weekly_reports WHERE week_id = ? OR filename LIKE ?",
            (name, f"%{safe_name}%")
        ).fetchone()
        conn.close()
        if row:
            return Response(row['content'], mimetype="text/markdown; charset=utf-8")
        return jsonify({"error": f"Report '{name}' not found"}), 404
    except Exception as e:
        logging.error(f"[api_report] error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/ligand/<code>")
def api_ligand(code):
    import urllib.request, json
    code = code.upper()
    result = {
        "code": code,
        "name": code,
        "molecular_weight": None,
        "type": None,
        "formula": None,
        "description": None
    }

    # Try to get ligand info from PDB data first (local database)
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ligand_info, ligand_names FROM pdb_structures
            WHERE ligand_info LIKE ? OR ligand_info LIKE ?
            LIMIT 1
        """, (f"%{code}%", f"%{code}%"))
        row = cursor.fetchone()
        if row and row[0]:
            # Parse ligand_info to find matching ligand name
            ligand_info = row[0]
            # Format: "CODE:Name|CODE2:Name2"
            for part in ligand_info.split('|'):
                if ':' in part:
                    parts = part.split(':', 1)
                    if parts[0].strip().upper() == code:
                        result["name"] = parts[1].strip()
                        break
    except Exception:
        pass

    # Fetch additional data from RCSB API
    try:
        # Get chemical component info
        url = f"https://data.rcsb.org/rest/v1/core/chemcomp/{code}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            chem_comp = data.get("chem_comp", {})

            # Get name
            if not result["name"] or result["name"] == code:
                result["name"] = chem_comp.get("name", code)

            # Get formula
            result["formula"] = chem_comp.get("formula", None)

            # Get type
            result["type"] = chem_comp.get("type", None)

            # Get molecular weight
            result["molecular_weight"] = chem_comp.get("formula_weight", None)

    except Exception:
        pass

    # Try alternative API endpoint for description
    try:
        url = f"https://data.rcsb.org/rest/v1/core/cheminfo/{code}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            chem_info = data.get("rcsb_chem_info", {})
            if not result["description"]:
                result["description"] = chem_info.get("description", None)
    except Exception:
        pass

    return jsonify(result)

@app.route("/pdb_app.js")
def serve_js():
    import time, os
    js_path = SCRIPT_DIR / "pdb_app.js"
    ts = int(js_path.stat().st_mtime)
    resp = send_file(js_path, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp

@app.route("/")
def index():
    import time
    html_path = SCRIPT_DIR / "pdb_index.html"
    ts = int(html_path.stat().st_mtime)
    with open(html_path, encoding='utf-8') as f:
        html = f.read()
    html = html.replace('/pdb_app.js"></script>', '/pdb_app.js?v=' + str(ts) + '"></script>')
    return Response(html, mimetype='text/html; charset=utf-8')

# ─── Target Evaluation Storage ───────────────────────────────────────────────
EVAL_DATA_DIR = Path("/Users/lijing/Documents/my_note/LLM-Wiki/wiki/evaluations")

# Journal Impact Factor lookup (sourced from existing data)
JOURNAL_IF_MAP = {
    'Science': 56.9,
    'Protein Cell': 21.1,
    'Nucleic Acids Res.': 19.2,
    'Nat Commun': 17.7,
    'Nature Communications': 17.7,
    'Nat. Commun.': 17.7,
    'Angew.Chem.Int.Ed.Engl.': 16.6,
    'Angew. Chem. Int. Ed. Engl.': 16.6,
    'J.Am.Chem.Soc.': 15.0,
    'J. Am. Chem. Soc.': 15.0,
    'Proc.Natl.Acad.Sci.USA': 11.1,
    'Proc. Natl. Acad. Sci. USA': 11.1,
    'PNAS': 11.1,
    'Embo J.': 8.3,
    'EMBO J.': 8.3,
    'Int.J.Biol.Macromol.': 8.2,
    'Int. J. Biol. Macromol.': 8.2,
    'J.Med.Chem.': 7.3,
    'J. Med. Chem.': 7.3,
    'Br.J.Pharmacol.': 7.3,
    'Br. J. Pharmacol.': 7.3,
    'Commun Biol': 5.1,
    'Communications Biology': 5.1,
    'J.Biol.Chem.': 4.5,
    'J. Biol. Chem.': 4.5,
    'J. Biol Chem': 4.5,
    'Structure': 4.4,
    'Biochem.J.': 3.7,
    'Biochem. J.': 3.7,
    'Biochemistry': 3.1,
    'J.Struct.Biol.': 3.0,
    'J. Struct. Biol.': 3.0,
    'Acta Biochim.Biophys.Sin.': 2.9,
    'Acta Biochim. Biophys. Sin.': 2.9,
    'Beilstein J Org Chem': 2.8,
    'Chembiochem': 2.4,
    'Acta Crystallogr D Struct Biol': 2.3,
    'Acta Crystallogr. D Struct. Biol.': 2.3,
    'Nat. Struct. Mol. Biol.': 18.0,
    'Nature Structural & Molecular Biology': 18.0,
    'Cell': 45.5,
    'Nature': 43.1,
    'Nat. Med.': 30.4,
    'Nature Medicine': 30.4,
    'eLife': 6.4,
    'Mol. Cell': 15.6,
    'Cell Res.': 44.1,
    'Nat. Biotechnol.': 33.2,
    'Nature Biotechnology': 33.2,
    'Science Advances': 11.7,
    'Pnas Nexus': 8.0,
    'Cancer Discov': 29.1,
    'Cancer Discovery': 29.1,
    'Cell Rep': 8.8,
    'Cell Reports': 8.8,
    'Cell Death Dis': 8.1,
    'Cell Death & Disease': 8.1,
    'Protein Eng. Des. Sel.': 2.5,
    'Protein Engineering, Design & Selection': 2.5,
    'Acta Crystallogr. Sect. D': 2.3,
    'Acs Chem. Biol.': 5.5,
    'ACS Chemical Biology': 5.5,
    'Structure': 4.4,
}

def get_journal_if(journal_name: str) -> float:
    """Lookup journal IF from name/abbreviation."""
    if not journal_name:
        return None
    # Try exact match first
    if journal_name in JOURNAL_IF_MAP:
        return JOURNAL_IF_MAP[journal_name]
    # Try normalized (lowercase, no extra spaces)
    normalized = journal_name.lower().replace('  ', ' ').strip()
    for k, v in JOURNAL_IF_MAP.items():
        if k.lower() == normalized:
            return v
    return None


EVAL_DATA_DIR.mkdir(exist_ok=True)

def _eval_file(uniprot_id: str) -> Path:
    """JSON file path for an evaluation."""
    return EVAL_DATA_DIR / f"{uniprot_id}.json"

def save_evaluation_report(uniprot_id: str, markdown_content: str, filename: str = None) -> bool:
    """Save an LLM-generated evaluation report to the evaluation_reports table.
    
    Called automatically after report generation.
    """
    try:
        if not filename:
            protein_part = ''
            try:
                conn = get_eval_db()
                row = conn.execute("SELECT protein_name FROM evaluations WHERE uniprot_id=?", (uniprot_id,)).fetchone()
                conn.close()
                if row and row[0]:
                    pn = row[0]
                    protein_part = '_' + re.sub(r'[^A-Za-z0-9]', '', pn[:20])
            except:
                pass
            filename = f"{uniprot_id}{protein_part}_结构可行性评估.md"
        
        h1 = re.search(r'^#\s+(.+)$', markdown_content, re.MULTILINE)
        title = h1.group(1).strip() if h1 else f"{uniprot_id} 结构可行性评估报告"
        
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        conn = get_eval_db()
        conn.execute("""
            INSERT OR REPLACE INTO evaluation_reports (uniprot_id, title, filename, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (uniprot_id, title, filename, markdown_content, now))
        conn.commit()
        conn.close()
        logging.info(f"[save_evaluation_report] saved report for {uniprot_id}")
        return True
    except Exception as e:
        logging.error(f"[save_evaluation_report] error: {e}")
        return False


def save_evaluation(result: dict) -> bool:
    """Save evaluation result to SQLite DB (primary) and JSON file (backup)."""
    try:
        import json as _json
        uniprot_id = result.get('uniprot_id')
        if not uniprot_id:
            return False

        # --- Extract main fields ---
        uniprot = result.get('uniprot', {}) or {}
        gene_list = uniprot.get('gene_names', []) or result.get('gene_names', []) or []
        gene_names_str = ', '.join(gene_list) if isinstance(gene_list, list) else str(gene_list or '')

        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        scores_json = _json.dumps(result.get('scores', {}), ensure_ascii=False, default=str)

        # --- Write to SQLite ---
        conn = get_eval_db()
        conn.execute("""
            INSERT OR REPLACE INTO evaluations
            (uniprot_id, entry_name, protein_name, gene_names, organism, sequence_length,
             coverage, scores, report, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uniprot_id,
            uniprot.get('entry_name', '') or result.get('entry_name', ''),
            uniprot.get('protein_name', '') or result.get('protein_name', ''),
            gene_names_str,
            uniprot.get('organism', '') or result.get('organism', ''),
            uniprot.get('sequence_length') or result.get('sequence_length') or 0,
            result.get('coverage', 0) or 0,
            scores_json,
            result.get('report', ''),
            result.get('created_at', now),
            now,
        ))

        # Delete old PDB structures within the same transaction
        conn.execute("DELETE FROM evaluation_pdb_structures WHERE uniprot_id = ?", (uniprot_id,))

        pdb_list = result.get('pdb_structures', []) or []
        for item in pdb_list:
            if isinstance(item, str):
                pdb_id = item
                method = ''
                resolution = None
                title = ''
                deposition_date = ''
                release_date = ''
                ligand = ''
                journal_if = None
            else:
                pdb_id = item.get('pdb_id', '')
                method = item.get('method', '')
                resolution = item.get('resolution')
                title = item.get('title', '')
                deposition_date = item.get('deposition_date', '')
                release_date = item.get('release_date', '')
                ligand = item.get('ligand', '') or item.get('ligands', '') or ''
                journal = item.get('journal', '')
                journal_if = item.get('journal_if') or item.get('if')

            method_lower = method.lower()
            is_cryoem = 1 if ('cryo' in method_lower or 'electron microscopy' in method_lower) else 0
            is_xray   = 1 if 'x-ray' in method_lower or 'xray' in method_lower else 0
            is_nmr    = 1 if 'nmr' in method_lower else 0

            if journal_if is not None:
                if journal_if >= 20: if_tier = 'top'
                elif journal_if >= 10: if_tier = 'high'
                elif journal_if >= 5: if_tier = 'mid'
                else: if_tier = 'low'
            else:
                if_tier = 'unknown'

            conn.execute("""
                INSERT INTO evaluation_pdb_structures
                (uniprot_id, pdb_id, method, resolution, title, deposition_date,
                 release_date, ligand, journal, journal_if, is_cryoem, is_xray, is_nmr, if_tier, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (uniprot_id, pdb_id, method, resolution, title, deposition_date,
                  release_date, ligand, journal, journal_if, is_cryoem, is_xray, is_nmr, if_tier, now))

        # Save BLAST results
        blast_list = result.get('blast_results', []) or []
        for b in blast_list:
            pdb_id_bl = b.get('pdb_id') or None
            uniprot_ref = b.get('uniprot_id') or None
            if not pdb_id_bl and not uniprot_ref:
                continue

            # Calculate IF tier
            b_jif = b.get('journal_if') or 0
            if b_jif and b_jif > 0:
                if b_jif >= 20: b_if_tier = 'top'
                elif b_jif >= 10: b_if_tier = 'high'
                elif b_jif >= 5: b_if_tier = 'mid'
                else: b_if_tier = 'low'
            else:
                b_if_tier = 'unknown'

            conn.execute("""
                INSERT INTO evaluation_blast_results
                (uniprot_id, pdb_id, uniprot_ref, description, title, identity, evalue,
                 query_coverage, target_coverage, method, resolution, release_date, source, taxonomy_id,
                 journal, journal_if, if_tier, ligand, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uniprot_id,
                pdb_id_bl,
                uniprot_ref,
                b.get('description', ''),
                b.get('title', ''),
                b.get('identity'),
                b.get('evalue'),
                b.get('query_coverage'),
                b.get('target_coverage', b.get('query_coverage')),
                b.get('method', ''),
                b.get('resolution'),
                b.get('release_date', ''),
                b.get('source', ''),
                b.get('taxonomy_id'),
                b.get('journal', ''),
                b.get('journal_if'),
                b_if_tier,
                b.get('ligand', ''),
                now,
            ))

        conn.commit()
        conn.close()

        # --- Also write JSON as backup ---
        file_path = _eval_file(uniprot_id)
        with open(file_path, 'w', encoding='utf-8') as f:
            _json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        logging.info(f"[save_evaluation] saved {uniprot_id} ({len(pdb_list)} structures) to DB + JSON")
        return True
    except Exception as e:
        logging.error(f"Failed to save evaluation: {e}")
        return False


def load_evaluation(uniprot_id: str) -> dict:
    """Load a single evaluation by UniProt ID from SQLite; fallback to JSON."""
    try:
        import json as _json

        # Try SQLite first
        conn = get_eval_db()
        row = conn.execute(
            "SELECT * FROM evaluations WHERE uniprot_id = ?", (uniprot_id,)
        ).fetchone()
        conn.close()

        if row:
            rd = dict(row)
            # Reconstruct pdb_structures list from DB
            conn2 = get_eval_db()
            pdb_rows = conn2.execute(
                "SELECT * FROM evaluation_pdb_structures WHERE uniprot_id = ? ORDER BY pdb_id",
                (uniprot_id,)
            ).fetchall()

            pdb_structures = []
            for pr in pdb_rows:
                pd = dict(pr)
                pdb_structures.append({
                    'pdb_id': pd['pdb_id'],
                    'method': pd['method'] or '',
                    'resolution': pd['resolution'],
                    'title': pd['title'] or '',
                    'deposition_date': pd['deposition_date'] or '',
                    'release_date': pd['release_date'] or '',
                    'ligand': pd['ligand'] or '',
                    'ligand_names': pd.get('ligand_names') or '',
                    'journal': pd.get('journal') or '',
                    'journal_if': pd['journal_if'],
                    'if_tier': pd.get('if_tier') or 'unknown',
                })

            # Load BLAST homolog results from DB
            blast_results = []
            blast_rows = conn2.execute(
                "SELECT * FROM evaluation_blast_results WHERE uniprot_id = ? ORDER BY identity DESC",
                (uniprot_id,)
            ).fetchall()
            for br in blast_rows:
                bd = dict(br)
                blast_results.append({
                    'pdb_id': bd['pdb_id'] or '',
                    'uniprot_id': bd['uniprot_ref'] or '',
                    'description': bd['description'] or '',
                    'title': bd.get('title') or bd.get('description') or '',
                    'identity': bd['identity'],
                    'evalue': bd['evalue'],
                    'query_coverage': bd['query_coverage'],
                    'target_coverage': bd.get('target_coverage') or bd.get('query_coverage') or 0,
                    'method': bd.get('method', ''),
                    'resolution': bd.get('resolution'),
                    'release_date': bd.get('release_date', ''),
                    'source': bd['source'] or 'BLAST',
                    'taxonomy_id': bd['taxonomy_id'],
                    'journal': bd.get('journal', ''),
                    'journal_if': bd.get('journal_if'),
                    'if_tier': bd.get('if_tier') or 'unknown',
                    'ligand': bd.get('ligand') or bd.get('ligands') or '',
                    'is_homolog': True,
                })
            conn2.close()

            # Enrich BLAST results with full PDB structure info
            blast_results = _enrich_blast_results(blast_results)

            gene_list = rd['gene_names'].split(', ') if rd.get('gene_names') else []
            uniprot_block = {
                'uniprot_id': rd['uniprot_id'],
                'entry_name': rd.get('entry_name', ''),
                'protein_name': rd.get('protein_name', ''),
                'gene_names': gene_list,
                'organism': rd.get('organism', ''),
                'sequence_length': rd.get('sequence_length') or 0,
            }
            raw_scores = _json.loads(rd['scores'] or '{}')
            # Normalize score keys: legacy lowercase → title-case
            scores_normalized = {}
            for k, v in raw_scores.items():
                k_lower = k.lower()
                if k_lower in ('cryoem', 'cryo-em', 'cryo em'):
                    scores_normalized['Cryo-EM'] = v
                elif k_lower in ('xray', 'x-ray', 'x ray'):
                    scores_normalized['X-ray'] = v
                elif k_lower == 'nmr':
                    scores_normalized['NMR'] = v
                else:
                    scores_normalized[k] = v

            # Filter BLAST results: remove PDBs already in direct structures
            existing_pdb_ids = set(s.get('pdb_id', '').upper() for s in pdb_structures)
            filtered_blast = [b for b in blast_results if b.get('pdb_id', '').upper() not in existing_pdb_ids]
            blast_results = filtered_blast

            return {
                'uniprot': uniprot_block,
                'uniprot_id': rd['uniprot_id'],
                'entry_name': rd.get('entry_name', ''),
                'protein_name': rd.get('protein_name', ''),
                'gene_names': gene_list,
                'organism': rd.get('organism', ''),
                'sequence_length': rd.get('sequence_length') or 0,
                'pdb_structures': pdb_structures,
                'blast_results': blast_results,
                'coverage': rd.get('coverage') or 0,
                'scores': scores_normalized,
                'report': rd.get('report') or '',
                'created_at': rd.get('created_at') or '',
            }

        # Fallback to JSON file
        file_path = _eval_file(uniprot_id)
        if file_path.exists():
            with open(file_path, encoding='utf-8') as f:
                data = _json.load(f)
                logging.info(f"[load_evaluation] {uniprot_id} loaded from JSON (fallback)")
                return data

        return None
    except Exception as e:
        logging.error(f"[load_evaluation] error loading {uniprot_id}: {e}")
        # Fallback to JSON
        try:
            import json as _json2
            file_path = _eval_file(uniprot_id)
            if file_path.exists():
                with open(file_path, encoding='utf-8') as f:
                    return _json2.load(f)
        except Exception:
            pass
        return None


def _normalize_scores(raw: dict) -> dict:
    """Normalize legacy lowercase score keys to title-case."""
    if not raw:
        return {}
    normalized = {}
    for k, v in raw.items():
        k_lower = k.lower()
        if k_lower in ('cryoem', 'cryo-em', 'cryo em'):
            normalized['Cryo-EM'] = v
        elif k_lower in ('xray', 'x-ray', 'x ray'):
            normalized['X-ray'] = v
        elif k_lower == 'nmr':
            normalized['NMR'] = v
        else:
            normalized[k] = v
    return normalized

def list_evaluations(search: str = "") -> list:
    """List all saved evaluations from SQLite, with optional search filter."""
    import json as _json
    try:
        conn = get_eval_db()
        if search:
            q = f"%{search}%"
            rows = conn.execute("""
                SELECT e.*, COUNT(p.pdb_id) as pdb_count
                FROM evaluations e
                LEFT JOIN evaluation_pdb_structures p ON e.uniprot_id = p.uniprot_id
                WHERE e.uniprot_id LIKE ? OR e.protein_name LIKE ? OR e.gene_names LIKE ? OR e.organism LIKE ?
                GROUP BY e.uniprot_id
                ORDER BY e.created_at DESC
            """, (q, q, q, q)).fetchall()
        else:
            rows = conn.execute("""
                SELECT e.*, COUNT(p.pdb_id) as pdb_count
                FROM evaluations e
                LEFT JOIN evaluation_pdb_structures p ON e.uniprot_id = p.uniprot_id
                GROUP BY e.uniprot_id
                ORDER BY e.created_at DESC
            """).fetchall()
        conn.close()

        results = []
        for row in rows:
            rd = dict(row)
            gene_str = rd.get('gene_names') or ''
            gene_list = gene_str.split(', ') if gene_str else []
            results.append({
                'uniprot_id': rd['uniprot_id'],
                'protein_name': rd.get('protein_name') or '',
                'gene_name': gene_str,
                'organism': rd.get('organism') or '',
                'pdb_count': rd.get('pdb_count') or 0,
                'coverage': rd.get('coverage') or 0,
                'scores': _normalize_scores(_json.loads(rd.get('scores') or '{}') if rd.get('scores') else {}),
                'created': rd.get('created_at') or '',
            })

        logging.info(f"[list_evaluations] search='{search}' returning {len(results)} results")
        return results
    except Exception as e:
        logging.error(f"[list_evaluations] error: {e}")
        return []


# ─── Target Evaluation API (for AI agent to submit) ───────────────────────
http_session = None

def _get_session():
    global http_session
    if http_session is None:
        import requests
        s = requests.Session()
        s.trust_env = False
        http_session = s
    return http_session


# ─── NCBI BLAST via curl (synchronous, reliable) ───────────────────────────

def _ncbi_blast_search(sequence: str, max_wait: int = 300) -> list:
    """
    Run NCBI BLASTp search using sequence, return list of homolog PDB structures.
    Uses curl subprocess to avoid SSL issues.
    """
    import urllib.parse
    logger.info(f"[NCBI BLAST] Submitting job for sequence length {len(sequence)}")
    # Submit job
    query_params = urllib.parse.urlencode({
        'CMD': 'Put',
        'QUERY': sequence[:10000],
        'DATABASE': 'pdb',
        'PROGRAM': 'blastp',
        'EXPECT': '0.01',
        'HITLIST_SIZE': '50',
        'FILTER': 'L',
        'FORMAT_TYPE': 'XML'
    })
    cmd = [
        'curl', '-s', '--connect-timeout', '30', '--max-time', '90',
        '-X', 'POST', '-d', query_params,
        'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=95)
    if result.returncode != 0:
        logger.error(f"[NCBI BLAST] submission failed: {result.stderr}")
        return []
    rid_match = re.search(r'RID = (\w+)', result.stdout)
    if not rid_match:
        logger.error(f"[NCBI BLAST] No RID found in response: {result.stdout[:300]}")
        return []
    job_id = rid_match.group(1)
    logger.info(f"[NCBI BLAST] Job submitted, RID={job_id}")
    # Poll for completion
    start_time = time.time()
    check_interval = 10
    while time.time() - start_time < max_wait:
        cmd2 = [
            'curl', '-s', '--connect-timeout', '30', '--max-time', '60',
            f'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&FORMAT_OBJECT=Status&RID={job_id}'
        ]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=65)
        if 'Status=READY' in r2.stdout:
            logger.info(f"[NCBI BLAST] Job {job_id} ready")
            break
        elif 'Status=WAITING' in r2.stdout or 'Status=UNKNOWN' in r2.stdout:
            logger.info(f"[NCBI BLAST] still running... ({int(time.time() - start_time)}s)")
            time.sleep(check_interval)
        else:
            if 'ERROR' in r2.stdout[:300] or 'FAILED' in r2.stdout[:300]:
                logger.error(f"[NCBI BLAST] error response: {r2.stdout[:300]}")
                return []
            time.sleep(check_interval)
    else:
        logger.warning(f"[NCBI BLAST] timeout after {max_wait}s")
        return []
    # Fetch XML results
    cmd3 = [
        'curl', '-s', '--connect-timeout', '30', '--max-time', '120',
        f'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&FORMAT_TYPE=XML&RID={job_id}'
    ]
    r3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=125)
    xml = r3.stdout
    # Parse XML
    homologs = []
    try:
        hit_pattern = r'<Hit>.*?</Hit>'
        hits = re.findall(hit_pattern, xml, re.DOTALL)
        for hit in hits:
            hsp_pattern = r'<Hit_id>.*?<Hit_def>(.*?)</Hit_def>'
            m = re.search(hsp_pattern, hit, re.DOTALL)
            if not m:
                continue
            hit_def = m.group(1)
            pdb_m = re.search(r'pdb\|(\w+)\|', hit_def)
            if not pdb_m:
                continue
            pdb_id = pdb_m.group(1).upper()
            evalue_m = re.search(r'<Hsp_evalue>(.*?)</Hsp_evalue>', hit)
            evalue = float(evalue_m.group(1)) if evalue_m else 1.0
            # Get identity count and alignment length to calculate percentage
            identity_m = re.search(r'<Hsp_identity>(\d+)</Hsp_identity>', hit)
            identity_count = int(identity_m.group(1)) if identity_m else 0
            align_len_m = re.search(r'<Hsp_align-len>(\d+)</Hsp_align-len>', hit)
            align_len = int(align_len_m.group(1)) if align_len_m else 0
            # Calculate identity percentage
            identity = round((identity_count / align_len) * 100) if align_len > 0 else 0
            # Clamp identity to max 100%
            identity = min(identity, 100)
            align_m = re.search(r'<Hsp_query-from>(\d+)</Hsp_query-from>.*?<Hsp_query-to>(\d+)</Hsp_query-to>', hit, re.DOTALL)
            q_cov = (int(align_m.group(2)) - int(align_m.group(1)) + 1) if align_m else 0
            desc = hit_def.split('|')[-1].strip() if '|' in hit_def else hit_def
            homologs.append({
                'pdb_id': pdb_id,
                'description': desc[:200],
                'evalue': evalue,
                'identity': identity,
                'query_coverage': q_cov,
                'source': 'BLAST',
                'is_homolog': True
            })
    except Exception as e:
        logger.error(f"[NCBI BLAST] parse error: {e}")
    logger.info(f"[NCBI BLAST] Found {len(homologs)} homologs")
    return homologs


def evaluate_uniprot(uniprot_id: str, force_blast: bool = False) -> dict:
    """Evaluate a UniProt ID: fetch UniProt + PDB data, run BLAST if no structures, generate report."""
    session = _get_session()
    result = {
        'uniprot_id': uniprot_id,
        'success': False,
        'error': None,
        'uniprot': None,
        'pdb_structures': [],
        'blast_results': [],
        'coverage': 0,
        'report': None,
        'scores': {},
        'created_at': '',
    }
    from datetime import datetime
    result['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')

    try:
        url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}?format=json"
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        entry_name = data.get('uniProtkbId', '')
        protein_name = ''
        pd_rec = data.get('proteinDescription', {})
        if pd_rec.get('recommendedName'):
            protein_name = pd_rec['recommendedName'].get('fullName', {}).get('value', '')

        gene_names = []
        for gene in data.get('genes', []):
            if gene.get('geneName'):
                gene_names.append(gene['geneName'].get('value', ''))

        organism = ''
        org_data = data.get('organism', {})
        if org_data:
            organism = org_data.get('scientificName', '')

        sequence_length = 0
        seq_info = data.get('sequence', {})
        if seq_info:
            sequence_length = seq_info.get('length', 0)

        pdb_ids = []
        for ref in data.get('uniProtKBCrossReferences', []):
            if ref.get('database') == 'PDB':
                pdb_ids.append(ref.get('id', ''))
        pdb_ids = list(set(pdb_ids))

        keywords = []
        for kw in data.get('keywords', []):
            kw_obj = kw.get('keyword')
            if isinstance(kw_obj, dict):
                val = kw_obj.get('value')
                if val:
                    keywords.append(val)

        function = ''
        for comment in data.get('comments', []):
            if isinstance(comment, dict) and comment.get('type') == 'function':
                texts = comment.get('texts', [])
                if texts and isinstance(texts[0], dict):
                    function = texts[0].get('value', '') or ''
                break

        result['uniprot'] = {
            'uniprot_id': uniprot_id,
            'entry_name': entry_name,
            'protein_name': protein_name,
            'gene_names': gene_names,
            'organism': organism,
            'function': function,
            'sequence_length': sequence_length,
            'pdb_ids': pdb_ids,
            'keywords': keywords,
            'mass': seq_info.get('molWeight', 0)
        }

        # Fetch PDB structures (up to 50)
        structures = []
        for pdb_id in pdb_ids[:50]:
            try:
                rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                rcsb_resp = session.get(rcsb_url, timeout=15)
                if rcsb_resp.status_code != 200:
                    continue
                rcsb = rcsb_resp.json()

                struct = rcsb.get('struct', {})
                title = struct.get('title', '') if isinstance(struct, dict) else ''

                # Get method from exptl or rcsb_entry_info
                method = ''
                exptl = rcsb.get('exptl', [])
                if exptl and isinstance(exptl, list) and isinstance(exptl[0], dict):
                    method = exptl[0].get('method', '') or ''
                rcsb_info = rcsb.get('rcsb_entry_info', {})
                if not method and isinstance(rcsb_info, dict):
                    method = rcsb_info.get('experimental_method', '') or ''

                # Get resolution using resolution_combined (works for both X-ray and Cryo-EM)
                resolution = None
                if isinstance(rcsb_info, dict):
                    # resolution_combined works for both X-ray and Cryo-EM
                    res_combined = rcsb_info.get('resolution_combined', [None])
                    if res_combined and res_combined[0] is not None:
                        resolution = res_combined[0]
                    # Fallback for X-ray only: try diffrn_resolution_high
                    if not resolution:
                        diffrn = rcsb_info.get('diffrn_resolution_high', {})
                        if isinstance(diffrn, dict):
                            resolution = diffrn.get('value')
                    # Fallback: try reflns
                    if not resolution:
                        refl = rcsb.get('reflns', [])
                        if refl and isinstance(refl[0], dict):
                            resolution = refl[0].get('d_resolution_high')

                # Get dates from rcsb_accession_info and pdbx_database_status
                acc_info = rcsb.get('rcsb_accession_info', {})
                release_date = ''
                if isinstance(acc_info, dict):
                    release_date = acc_info.get('initial_release_date', '') or ''
                    if release_date:
                        release_date = release_date[:10]  # Get YYYY-MM-DD

                deposition_date = ''
                db_status = rcsb.get('pdbx_database_status', {})
                if isinstance(db_status, dict):
                    deposition_date = db_status.get('recvd_initial_deposition_date', '') or ''
                    if deposition_date:
                        deposition_date = deposition_date[:10]

                # Fetch structure-specific ligands from entry (not protein-level cofactors)
                ligand = ''
                try:
                    # Get entry to find non-polymer entity IDs
                    entry_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                    entry_resp = session.get(entry_url, timeout=10)
                    if entry_resp.status_code == 200:
                        entry_data = entry_resp.json()
                        container = entry_data.get('rcsb_entry_container_identifiers', {})
                        nonpoly_ids = container.get('non_polymer_entity_ids', [])
                        if nonpoly_ids:
                            # Fetch each nonpolymer entity to get ligand info
                            ligands = []
                            seen = set()
                            for entity_id in nonpoly_ids[:10]:  # Limit to 10
                                try:
                                    np_url = f"https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{pdb_id}/{entity_id}"
                                    np_resp = session.get(np_url, timeout=5)
                                    if np_resp.status_code == 200:
                                        np_data = np_resp.json()
                                        # Get comp_id from pdbx_entity_nonpoly
                                        entity_nonpoly = np_data.get('pdbx_entity_nonpoly', {})
                                        comp_id = entity_nonpoly.get('comp_id', '')
                                        if comp_id and comp_id not in seen and len(comp_id) <= 5:
                                            # Filter out common solvents/water/ions/buffers
                                            if comp_id not in ['HOH', 'DOD', 'SO4', 'CL', 'NA', 'K', 'MG', 'CA', 'ZN', 'FE', 'CU', 'MN', 'CO',
                                                              'GOL', 'PEG', 'EDO', '1PE', '2PE', '3PE', '4PE', 'MLI', 'ACT', 'NH4', 'NO3',
                                                              'EPE', 'HEP', 'MES', 'TRS', 'TRIS', 'MPO', 'PGE', 'PG4', 'DMS', 'DMSO',
                                                              'IPA', 'BU1', 'BU2', 'BU3', 'MPD', 'PG6', '1PG', '2PG', 'XPE']:
                                                seen.add(comp_id)
                                                ligands.append(comp_id)
                                except Exception:
                                    continue
                            if ligands:
                                ligand = '; '.join(ligands[:10])
                except Exception:
                    pass

                # Fetch journal/citation info from RCSB
                journal = ''
                doi = ''
                pubmed_id = ''
                journal_if = None
                try:
                    cit_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                    cit_resp = session.get(cit_url, timeout=10)
                    if cit_resp.status_code == 200:
                        cit_data = cit_resp.json()
                        citations = cit_data.get('citation', [])
                        primary = None
                        for c in citations:
                            if c.get('rcsb_is_primary') == 'Y':
                                primary = c
                                break
                        if primary is None and citations:
                            primary = citations[0]
                        if primary:
                            journal = primary.get('journal_abbrev', '') or primary.get('rcsb_journal_abbrev', '')
                            doi = primary.get('pdbx_database_id_DOI', '')
                            pubmed = primary.get('pdbx_database_id_PubMed', '')
                            pubmed_id = str(pubmed) if pubmed else ''
                            # Lookup IF from journal name
                            journal_if = get_journal_if(journal)
                except Exception:
                    pass

                structures.append({
                    'pdb_id': pdb_id,
                    'title': title,
                    'method': method,
                    'resolution': resolution,
                    'deposition_date': deposition_date,
                    'release_date': release_date,
                    'ligand': ligand,
                    'journal': journal,
                    'doi': doi,
                    'pubmed_id': pubmed_id,
                    'journal_if': journal_if
                })
            except Exception:
                continue

        result['pdb_structures'] = structures

        # Calculate coverage
        coverage = 0
        if sequence_length > 0 and structures:
            covered = set()
            for pdb_id in [s['pdb_id'] for s in structures]:
                try:
                    map_url = f"https://www.ebi.ac.uk/pdbe/api/mappings/all_isoforms/{pdb_id.lower()}"
                    map_resp = session.get(map_url, timeout=10)
                    if map_resp.status_code == 200:
                        map_data = map_resp.json()
                        unp_data = map_data.get(pdb_id.lower(), {}).get('UniProt', {})
                        for uid, info in unp_data.items():
                            if uid.upper() != uniprot_id.upper() and not uid.startswith(uniprot_id.upper()):
                                continue
                            for m in info.get('mappings', []):
                                s_pos = m.get('unp_start')
                                e_pos = m.get('unp_end')
                                if s_pos and e_pos:
                                    for p in range(s_pos, e_pos + 1):
                                        covered.add(p)
                except Exception:
                    continue
            coverage = min(len(covered) / sequence_length * 100, 100)
        result['coverage'] = round(coverage, 1)

        # BLAST search: real NCBI BLAST when force_blast=True or when coverage/structures are poor
        blast_results = []
        need_real_blast = force_blast or ((coverage < 50 or len(structures) < 5) and sequence_length > 0)
        if need_real_blast:
            # Try to get sequence for BLAST
            try:
                seq_url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.fasta"
                seq_resp = session.get(seq_url, timeout=30)
                if seq_resp.status_code == 200:
                    seq_lines = seq_resp.text.strip().split('\n')
                    sequence = ''.join(seq_lines[1:])
                    if sequence and len(sequence) > 10:
                        real_blast = _ncbi_blast_search(sequence)
                        if real_blast:
                            # Enrich with UniProt metadata
                            try:
                                tax_url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}?format=json"
                                tax_resp = session.get(tax_url, timeout=15)
                                tax_id = None
                                if tax_resp.status_code == 200:
                                    tax_id = tax_resp.json().get('organism', {}).get('taxonId')
                            except:
                                tax_id = None
                            for rb in real_blast:
                                rb['taxonomy_id'] = tax_id
                            blast_results = real_blast
                            logger.info(f"[evaluate_uniprot] NCBI BLAST found {len(blast_results)} homologs")
                        else:
                            logger.warning("[evaluate_uniprot] NCBI BLAST returned no results, falling back to taxonomy search")
                    else:
                        logger.warning(f"[evaluate_uniprot] Could not parse sequence for {uniprot_id}")
                else:
                    logger.warning(f"[evaluate_uniprot] Could not fetch sequence for {uniprot_id}")
            except Exception as e:
                logger.error(f"[evaluate_uniprot] BLAST preparation error: {e}")

        # Fallback: taxonomy-based search if no real BLAST results
        if not blast_results and sequence_length > 0:
            taxonomy_id = None
            org_data = data.get('organism', {})
            if org_data:
                taxonomy_id = org_data.get('taxonId')

            if taxonomy_id:
                try:
                    search_url = "https://rest.uniprot.org/uniprotkb/search"
                    params = {
                        'query': f'taxon_id:{taxonomy_id}',
                        'format': 'json',
                        'size': 20,
                        'fields': 'accession,gene_names,protein_name,organism_name'
                    }
                    search_resp = session.get(search_url, params=params, timeout=20)
                    if search_resp.status_code == 200:
                        search_data = search_resp.json()
                        for entry in search_data.get('results', []):
                            acc = entry.get('primaryAccession', '')
                            if acc == uniprot_id:
                                continue
                            gene_list = entry.get('genes', [])
                            gene_name = gene_list[0].get('geneName', {}).get('value', '') if gene_list else ''
                            prot_rec = entry.get('proteinName', {})
                            prot_name = prot_rec.get('fullName', {}).get('value', '') if isinstance(prot_rec, dict) else ''
                            org_rec = entry.get('organism', {})
                            org_name = org_rec.get('scientificName', '') if isinstance(org_rec, dict) else ''
                            blast_results.append({
                                'uniprot_id': acc,
                                'gene_name': gene_name,
                                'protein_name': (prot_name or '')[:100],
                                'organism': org_name
                            })
                except Exception:
                    pass

            if len(blast_results) < 10 and taxonomy_id:
                try:
                    pdb_search_url = "https://search.rcsb.org/rcsbsearch/v1/query"
                    pdb_query = {
                        "query": {"type": "group", "logical_operator": "and",
                            "nodes": [{"type": "taxonomy", "operator": "exact_match", "value": str(taxonomy_id)}]},
                        "return_type": "entry",
                        "request_options": {"page_size": 20, "results_content_type": ["experimental"]}
                    }
                    pdb_resp = session.post(pdb_search_url, json=pdb_query, timeout=20)
                    if pdb_resp.status_code == 200:
                        pdb_data = pdb_resp.json()
                        existing = set(r.get('pdb_id', '').lower() for r in blast_results)
                        for pdb_entry in pdb_data.get('result_set', {}).get('dbrefs', []):
                            pdb_id = pdb_entry.get('uid', '')
                            if pdb_id and pdb_id.lower() not in existing and pdb_id.upper() != uniprot_id.upper():
                                blast_results.append({
                                    'pdb_id': pdb_id,
                                    'gene_name': '',
                                    'protein_name': f'PDB Structure {pdb_id}',
                                    'organism': result['uniprot']['organism'] or 'Various',
                                    'source': 'PDB_taxonomy',
                                    'is_homolog': True
                                })
                                if len(blast_results) >= 20:
                                    break
                except Exception:
                    pass

        # Filter out PDBs that are already in direct structures; mark remaining as homologs
        existing_pdb_ids = set(s.get('pdb_id', '').upper() for s in structures)
        filtered_blast = []
        for b in blast_results:
            b_pdb = b.get('pdb_id', '').upper()
            if b_pdb and b_pdb not in existing_pdb_ids:
                b['is_homolog'] = True
                filtered_blast.append(b)

        # Enrich BLAST results with full PDB details
        logger.info(f"[evaluate_uniprot] Enriching {len(filtered_blast)} BLAST results with PDB details...")
        filtered_blast = _enrich_blast_results(filtered_blast)

        result['blast_results'] = filtered_blast[:20]

        # Scores first (needed for report)
        result['scores'] = _calculate_feasibility_scores(result)

        # Report
        result['report'] = _generate_evaluation_report(result)
        result['success'] = True

    except Exception as e:
        logging.error(f"Evaluation failed for {uniprot_id}: {e}")
        err_msg = str(e)
        err_msg = re.sub(r'\d{3} Client Error:.*?(?=\n|$)', 'API请求失败', err_msg)
        err_msg = re.sub(r'HTTPError.*?(?=\n|$)', '网络请求失败', err_msg)
        if '404' in err_msg or 'Not Found' in err_msg:
            err_msg = f"UniProt ID '{uniprot_id}' 未找到"
        elif '400' in err_msg or 'Bad Request' in err_msg:
            err_msg = f"UniProt ID '{uniprot_id}' 格式无效"
        result['error'] = err_msg

    return result


def _enrich_blast_results(blast_results: list, limit: int = None) -> list:
    """Fetch full PDB structure details for BLAST homologs that lack method/resolution info.

    Makes per-PDB calls to RCSB REST API v1 to get:
    method, resolution, title, release_date, journal, doi, pubmed_id, journal_if.
    Uses concurrent requests for faster loading.
    """
    if not blast_results:
        return blast_results

    # Find BLAST PDBs that need enrichment (no method/resolution)
    needs_enrichment = []
    for b in blast_results:
        if not b.get('method') and b.get('pdb_id'):
            needs_enrichment.append(b['pdb_id'].upper())

    if not needs_enrichment:
        return blast_results

    # Limit if specified (to avoid excessive API calls)
    if limit:
        needs_enrichment = needs_enrichment[:limit]
    logger.info(f"[enrich_blast] Enriching {len(needs_enrichment)} BLAST PDBs...")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    session = _get_session()

    def fetch_pdb_info(pid):
        """Fetch PDB info for a single PDB ID."""
        try:
            url = f"https://data.rcsb.org/rest/v1/core/entry/{pid}"
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"[enrich_blast] {pid} returned {resp.status_code}")
                return pid, None
            return pid, resp.json()
        except Exception as e:
            logger.error(f"[enrich_blast] Error fetching {pid}: {e}")
            return pid, None

    # Fetch all PDB info concurrently
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_pid = {executor.submit(fetch_pdb_info, pid): pid for pid in needs_enrichment}
        for future in as_completed(future_to_pid):
            pid, data = future.result()
            if data:
                results[pid] = data

    # Process results
    for pid, data in results.items():
        try:
            # Extract method
            method = ""
            exptl = data.get('exptl', [])
            if exptl:
                method = exptl[0].get('method', '') or ''

            # Extract resolution
            resolution = None
            rcsb_info = data.get('rcsb_entry_info', {})
            if isinstance(rcsb_info, dict):
                res_combined = rcsb_info.get('resolution_combined', [])
                if res_combined:
                    resolution = res_combined[0]

            # Extract title
            struct = data.get('struct', {})
            title = struct.get('title', '') if isinstance(struct, dict) else ''

            # Extract release_date (first revision = original release)
            audit = data.get('pdbx_audit_revision_history', [])
            if audit:
                rd = audit[0].get('revision_date', '')
                release_date = rd[:10] if rd else ''
            else:
                release_date = ''

            # Extract journal info from citation
            journal = ""
            doi = ""
            pubmed_id = ""
            citations = data.get('citation', [])
            primary_citation = None
            for c in citations:
                if c.get('rcsb_is_primary'):
                    primary_citation = c
                    break
            if not primary_citation and citations:
                primary_citation = citations[0]
            if primary_citation:
                journal = primary_citation.get('journal_abbrev', '') or ''
                doi = primary_citation.get('pdbx_database_id_DOI', '') or ''
                pubmed_id = str(primary_citation.get('pdbx_database_id_PubMed', '')) or ''

            # Journal IF
            journal_if = get_journal_if(journal) if journal else 0

            # Extract ligands from nonpolymer_bound_components
            nonpoly = data.get('rcsb_entry_info', {}).get('nonpolymer_bound_components', [])
            ligand = ", ".join(sorted(set(nonpoly))) if nonpoly else ""

            # Also try to get more detailed ligand info
            try:
                np_url = f"https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{pid}/1"
                np_resp = session.get(np_url, timeout=5)
                if np_resp.status_code == 200:
                    np_data = np_resp.json()
                    entity_nonpoly = np_data.get('pdbx_entity_nonpoly', {})
                    comp_id = entity_nonpoly.get('comp_id', '')
                    if comp_id and len(comp_id) <= 5:
                        if comp_id not in ['HOH', 'DOD', 'SO4', 'CL', 'NA', 'K', 'MG', 'CA', 'ZN', 'FE', 'CU', 'MN', 'CO',
                                          'GOL', 'PEG', 'EDO', '1PE', '2PE', '3PE', '4PE', 'MLI', 'ACT', 'NH4', 'NO3',
                                          'EPE', 'HEP', 'MES', 'TRS', 'TRIS', 'MPO', 'PGE', 'PG4', 'DMS', 'DMSO',
                                          'IPA', 'BU1', 'BU2', 'BU3', 'MPD', 'PG6', '1PG', '2PG', 'XPE']:
                            if ligand:
                                ligand = comp_id + "; " + ligand
                            else:
                                ligand = comp_id
            except Exception:
                pass

            # Calculate IF tier
            if_tier = 'unknown'
            if journal_if and journal_if > 0:
                if journal_if >= 20:
                    if_tier = 'top'
                elif journal_if >= 10:
                    if_tier = 'high'
                elif journal_if >= 5:
                    if_tier = 'mid'
                else:
                    if_tier = 'low'

            # Update the BLAST result in-place
            for b in blast_results:
                if b.get('pdb_id', '').upper() == pid:
                    b['method'] = method
                    b['resolution'] = resolution
                    b['title'] = title
                    b['release_date'] = release_date
                    b['journal'] = journal
                    b['doi'] = doi
                    b['pubmed_id'] = pubmed_id
                    b['journal_if'] = journal_if
                    b['if_tier'] = if_tier
                    b['ligand'] = ligand
                    b['ligands'] = ligand
                    b['is_homolog'] = True
                    logger.info(f"[enrich_blast] {pid}: method={method}, resolution={resolution}, if={journal_if}, ligands={ligand[:30] if ligand else 'None'}")
                    break

        except Exception as e:
            logger.error(f"[enrich_blast] Error processing {pid}: {e}")

    return blast_results




def _build_llm_report_prompt(uniprot_id: str, uniprot_data: dict, structures: list, blast_results: list, coverage: float, scores: dict) -> str:
    """Build a comprehensive prompt for LLM report generation."""
    # Prepare structure data
    xray = [s for s in structures if 'x-ray' in (s.get('method') or '').lower()]
    cryoem = [s for s in structures if 'cryo' in (s.get('method') or '').lower() or 'electron' in (s.get('method') or '').lower()]
    nmr = [s for s in structures if 'nmr' in (s.get('method') or '').lower()]
    blast_xray = [b for b in blast_results if 'x-ray' in (b.get('method') or '').lower()]
    blast_cryoem = [b for b in blast_results if 'cryo' in (b.get('method') or '').lower() or 'electron' in (b.get('method') or '').lower()]

    res_vals = [s.get('resolution') for s in structures if s.get('resolution') is not None]
    best_res = min(res_vals) if res_vals else None
    blast_res = [b.get('resolution') for b in blast_results if b.get('resolution') is not None]
    best_blast_res = min(blast_res) if blast_res else None

    # Collect all ligands
    all_ligands = []
    for s in structures:
        lig = s.get('ligand') or ''
        if lig:
            for l in lig.split(','):
                l = l.strip()
                if l: all_ligands.append(l)
    for b in blast_results:
        lig = b.get('ligand') or ''
        if lig:
            for l in lig.split(','):
                l = l.strip()
                if l: all_ligands.append(l)
    ligand_summary = sorted(set(all_ligands)) if all_ligands else []

    # Journal IF
    jifs = []
    for s in structures:
        j = s.get('journal_if')
        if j and j > 0: jifs.append(j)
    for b in blast_results:
        j = b.get('journal_if')
        if j and j > 0: jifs.append(j)
    avg_jif = sum(jifs)/len(jifs) if jifs else 0

    prompt = f"""## 蛋白质结构可行性评估报告生成任务

你是一位专业的结构生物学研究员。请根据以下数据，为蛋白质 **{uniprot_id}** ({uniprot_data.get('protein_name', 'N/A')}) 生成一份专业、详细的结构可行性评估报告。

### 蛋白基本信息
- **UniProt ID**: {uniprot_id}
- **蛋白名称**: {uniprot_data.get('protein_name', 'N/A')}
- **基因名**: {', '.join(uniprot_data.get('gene_names', []) or ['N/A'])}
- **物种**: {uniprot_data.get('organism', 'N/A')}
- **序列长度**: {uniprot_data.get('sequence_length', 0)} aa
- **功能描述**: {uniprot_data.get('function', 'N/A')[:200] if uniprot_data.get('function') else 'N/A'}

### 结构覆盖情况
- **覆盖度**: {coverage:.1f}%
- **直接关联PDB结构**: {len(structures)} 个
- **BLAST同源蛋白**: {len(blast_results)} 个

### 直接PDB结构详情
"""
    if structures:
        prompt += "| PDB ID | 方法 | 分辨率 | 期刊 IF | 配体 | 发布日期 | 标题 |\n|--------|------|--------|---------|------|----------|------|\n"
        for s in structures[:20]:
            res = f"{s.get('resolution', 'N/A'):.2f}" if s.get('resolution') else "N/A"
            jif = f"{s.get('journal_if', 'N/A'):.1f}" if s.get('journal_if') else "N/A"
            title = (s.get('title') or '-')[:50]
            prompt += f"| {s.get('pdb_id','N/A')} | {s.get('method','N/A')} | {res} Å | {jif} | {s.get('ligand','-')} | {s.get('release_date','N/A')} | {title} |\n"
    else:
        prompt += "*暂无直接关联的PDB结构*\n"

    prompt += f"""
### BLAST同源蛋白详情（{len(blast_results)} 个，按序列同一性排序）
"""
    if blast_results:
        prompt += "| PDB ID | 方法 | 分辨率 | 期刊 IF | 配体 | 发布日期 | 序列同一性 | 来源物种 |\n|--------|------|--------|---------|------|----------|-----------|---------|\n"
        for b in blast_results[:20]:
            res = f"{b.get('resolution', 'N/A'):.2f}" if b.get('resolution') else "N/A"
            jif = f"{b.get('journal_if', 'N/A'):.1f}" if b.get('journal_if') else "N/A"
            identity = b.get('identity', 'N/A')
            desc = b.get('description', '-')
            # Extract organism from description
            org_match = re.search(r'\[(.*?)\]', desc)
            org = org_match.group(1) if org_match else '-'
            prompt += f"| {b.get('pdb_id','N/A')} | {b.get('method','N/A')} | {res} Å | {jif} | {b.get('ligand','-')} | {b.get('release_date','N/A')} | {identity} | {org} |\n"
    else:
        prompt += "*无BLAST同源蛋白结果*\n"

    prompt += f"""
### 方法学统计
- X-ray: {len(xray)} 个直接结构, {len(blast_xray)} 个BLAST结构
- Cryo-EM: {len(cryoem)} 个直接结构, {len(blast_cryoem)} 个BLAST结构  
- NMR: {len(nmr)} 个直接结构

### 分辨率概况
- 直接结构最佳分辨率: {f'{best_res:.2f} Å' if best_res else 'N/A'}
- BLAST结构最佳分辨率: {f'{best_blast_res:.2f} Å' if best_blast_res else 'N/A'}
- 期刊平均IF: {avg_jif:.1f}

### 配体汇总
{', '.join(ligand_summary) if ligand_summary else '无明确配体信息'}

### 评分
{json.dumps(scores, ensure_ascii=False, indent=2) if scores else '无评分数据'}

## 报告要求

请生成一份完整的专业评估报告，包括：

1. **执行摘要**（3-5句话）：蛋白功能、可用结构数量和质量、可行性结论
2. **蛋白功能概述**：基于UniProt功能描述，简述蛋白功能和研究意义
3. **结构覆盖度分析**：直接结构和BLAST同源结构的区域覆盖情况
4. **同源蛋白结构分析**：
   - 分辨率分布统计（分档说明）
   - 高质量结构推荐（按分辨率和同一性筛选 Top 5）
   - 配体分析（常见配体及功能意义）
5. **可行性评估**：X-ray / Cryo-EM / NMR 三种方法的推荐度及理由
6. **实验建议**：推荐的表达系统、construct设计、Cryo-EM制样方案等
7. **关键参考文献**：引用高IF期刊的代表性结构（3-5篇）

**格式要求**：
- 使用 Markdown 格式
- 报告语言：中文为主，专业术语可保留英文
- 标题使用 # 一级标题
- 表格使用 | 语法
- 报告末尾注明"本报告由 LLM 基于结构数据自动生成"
- 保持专业性和可读性，避免流水账式罗列

请直接输出报告正文，不要有额外的解释说明。
"""
    return prompt


def _generate_llm_evaluation_report(uniprot_id: str) -> str:
    """Generate LLM-powered evaluation report and save to DB. Returns markdown content."""
    try:
        # Load data from DB
        conn = get_eval_db()
        
        # Get evaluation metadata
        row = conn.execute("SELECT * FROM evaluations WHERE uniprot_id=?", (uniprot_id,)).fetchone()
        if not row:
            conn.close()
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM evaluations LIMIT 0").description]
        eval_data = dict(zip(cols, row))
        
        # Get direct structures
        struct_rows = conn.execute(
            "SELECT * FROM evaluation_pdb_structures WHERE uniprot_id=? ORDER BY pdb_id", (uniprot_id,)
        ).fetchall()
        s_cols = [d[0] for d in conn.execute("SELECT * FROM evaluation_pdb_structures LIMIT 0").description]
        structures = [dict(zip(s_cols, r)) for r in struct_rows]
        
        # Get BLAST results
        blast_rows = conn.execute(
            "SELECT * FROM evaluation_blast_results WHERE uniprot_id=? ORDER BY identity DESC", (uniprot_id,)
        ).fetchall()
        b_cols = [d[0] for d in conn.execute("SELECT * FROM evaluation_blast_results LIMIT 0").description]
        blast_results = [dict(zip(b_cols, r)) for r in blast_rows]
        conn.close()
        
        # Build prompt
        import json
        uniprot_block = {
            'uniprot_id': uniprot_id,
            'protein_name': eval_data.get('protein_name', ''),
            'gene_names': eval_data.get('gene_names', '').split(', ') if eval_data.get('gene_names') else [],
            'organism': eval_data.get('organism', ''),
            'sequence_length': eval_data.get('sequence_length', 0),
            'function': ''
        }
        
        scores_raw = eval_data.get('scores', '{}')
        try:
            scores = json.loads(scores_raw) if scores_raw else {}
        except:
            scores = {}
        
        prompt = _build_llm_report_prompt(
            uniprot_id, uniprot_block, structures, blast_results,
            eval_data.get('coverage', 0), scores
        )
        
        # Call LLM API - try OpenAI first, then Claude
        report_content = None
        
        # Try MiniMax Moonshot (abab6.5s-chat supports 200k context)
        moonshot_key = os.getenv('MINIMAX_API_KEY')
        if moonshot_key and moonshot_key not in ('', 'your-key-here'):
            try:
                import openai
                client = openai.OpenAI(api_key=moonshot_key, base_url="https://api.minimax.chat/v1")
                response = client.chat.completions.create(
                    model="abab6.5s-chat",
                    messages=[
                        {"role": "system", "content": "你是一位专业的结构生物学研究员，擅长蛋白质结构可行性评估。请根据提供的数据生成专业、详细的评估报告。"},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=4096,
                    temperature=0.3
                )
                report_content = response.choices[0].message.content
                logging.info(f"[_generate_llm_report] MiniMax/abab6.5s-chat generated {len(report_content)} chars for {uniprot_id}")
            except Exception as e:
                logging.warning(f"[_generate_llm_report] MiniMax/abab6.5s-chat error: {e}")

        # Try OpenAI
        if not report_content:
            openai_key = os.getenv('OPENAI_API_KEY')
            if openai_key and openai_key not in ('your-key-here', '', 'sk-'):
                try:
                    import openai
                    client = openai.OpenAI(api_key=openai_key)
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "你是一位专业的结构生物学研究员，擅长蛋白质结构可行性评估。请根据提供的数据生成专业、详细的评估报告。"},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=4096,
                        temperature=0.3
                    )
                    report_content = response.choices[0].message.content
                    logging.info(f"[_generate_llm_report] OpenAI/gpt-4o-mini generated {len(report_content)} chars for {uniprot_id}")
                except Exception as e:
                    logging.warning(f"[_generate_llm_report] OpenAI error: {e}")

        # Try Anthropic
        if not report_content:
            anthropic_key = os.getenv('ANTHROPIC_API_KEY')
            if anthropic_key and anthropic_key not in ('', 'your-key-here'):
                try:
                    import anthropic
                    client = anthropic.Anthropic(api_key=anthropic_key)
                    response = client.messages.create(
                        model="claude-3-5-haiku-20241106",
                        max_tokens=4096,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    report_content = response.content[0].text
                    logging.info(f"[_generate_llm_report] Anthropic/claude-3-5-haiku generated {len(report_content)} chars for {uniprot_id}")
                except Exception as e:
                    logging.warning(f"[_generate_llm_report] Anthropic error: {e}")

        if not report_content:
            logging.warning(f"[_generate_llm_report] No LLM API key available for {uniprot_id}")
            return None
        
        # Save to evaluation_reports table
        save_evaluation_report(uniprot_id, report_content)
        
        return report_content
    except Exception as e:
        logging.error(f"[_generate_llm_report] error: {e}")
        return None


@app.route("/api/evaluation/report/generate/<uniprot_id>", methods=["POST"])
def api_evaluation_report_generate(uniprot_id: str):
    """Generate LLM evaluation report for a UniProt ID and save to DB.
    
    Called automatically after evaluation completes, or manually via POST.
    Returns the generated markdown content.
    """
    if not uniprot_id or not re.match(r'^[A-Z0-9]+$', uniprot_id, re.I):
        return jsonify({"error": "Invalid UniProt ID"}), 400
    
    try:
        # Check if evaluation exists
        conn = get_eval_db()
        row = conn.execute("SELECT uniprot_id FROM evaluations WHERE uniprot_id=?", (uniprot_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({"error": f"Evaluation for {uniprot_id} not found. Run /api/evaluate first."}), 404
        
        report = _generate_llm_evaluation_report(uniprot_id)
        if report is None:
            return jsonify({"error": "Report generation failed (check API keys)"}), 500
        
        return Response(report, mimetype="text/markdown; charset=utf-8")
    except Exception as e:
        logging.error(f"[api_evaluation_report_generate] error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/evaluation/report/<uniprot_id>", methods=["PUT"])
def api_evaluation_report_put(uniprot_id: str):
    'AI agent saves an LLM-generated evaluation report via this endpoint.'
    if not uniprot_id or not re.match(r'^[A-Z0-9]+$', uniprot_id, re.I):
        return jsonify({"error": "Invalid UniProt ID"}), 400
    try:
        report_content = request.get_data(as_text=True)
        if not report_content or len(report_content) < 20:
            return jsonify({"error": "Report content too short"}), 400
        title_match = re.search(r'^#\s+(.+)$', report_content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else f"{uniprot_id} structure feasibility evaluation"
        filename = f"{uniprot_id}_feasibility_report.md"
        save_evaluation_report(uniprot_id, report_content, filename)
        logging.info(f"[api_evaluation_report_put] saved {uniprot_id} ({len(report_content)} chars)")
        return jsonify({"success": True, "uniprot_id": uniprot_id, "filename": filename})
    except Exception as e:
        logging.error(f"[api_evaluation_report_put] error: {e}")
        return jsonify({"error": str(e)}), 500


def _generate_evaluation_report(data: dict) -> str:
    uniprot = data.get('uniprot', {})
    structures = data.get('pdb_structures', [])
    blast = data.get('blast_results', [])
    coverage = data.get('coverage', 0)
    scores = data.get('scores', {})

    lines = []
    lines.append(f"# 蛋白质结构可行性评估报告\n")
    lines.append(f"**UniProt ID**: {uniprot.get('uniprot_id', 'N/A')} | **{uniprot.get('protein_name', 'N/A')}**\n")
    lines.append(f"**基因名**: {', '.join(uniprot.get('gene_names', []) or ['N/A'])} | **物种**: {uniprot.get('organism', 'N/A')}\n")
    lines.append(f"**序列长度**: {uniprot.get('sequence_length', 0)} aa | **分子量**: {(lambda m: f'{m:.0f} Da' if m is not None else 'N/A')(uniprot.get('mass'))}\n")
    lines.append(f"**已有PDB结构**: {len(structures)} 个 | **覆盖度**: {coverage:.1f}%\n")

    if uniprot.get('function'):
        lines.append(f"\n## 功能描述\n{uniprot['function']}\n")

    if scores:
        lines.append("\n## 可行性评分\n")
        lines.append("| 方法 | 评分 | 评估 |\n")
        lines.append("|------|------|------|\n")
        for method, info in scores.items():
            score = info.get('score', 0)
            stars = '★' * max(1, min(5, round(score / 2)))
            lines.append(f"| {method} | {score}/10 {stars} | {info.get('assessment', 'N/A')} |\n")

    if structures:
        lines.append("\n## PDB 结构详情\n")
        cryoem = [s for s in structures if 'electron microscopy' in s.get('method', '').lower() or 'cryo' in s.get('method', '').lower()]
        xray = [s for s in structures if 'x-ray' in s.get('method', '').lower() or 'diffraction' in s.get('method', '').lower()]
        nmr = [s for s in structures if 'nmr' in s.get('method', '').lower()]
        lines.append(f"- Cryo-EM: {len(cryoem)} 个\n")
        lines.append(f"- X-ray: {len(xray)} 个\n")
        lines.append(f"- NMR: {len(nmr)} 个\n")
        lines.append("\n| PDB ID | 方法 | 分辨率 | 标题 |\n")
        lines.append("|--------|------|--------|------|\n")
        for s in structures[:20]:
            method = s.get('method', 'N/A')
            m_label = 'Cryo-EM' if 'cryo' in method.lower() else 'X-ray' if 'x-ray' in method.lower() else method
            res = f"{s['resolution']:.2f} Å" if s.get('resolution') else '-'
            title = (s.get('title') or '')[:60]
            lines.append(f"| {s['pdb_id']} | {m_label} | {res} | {title} |\n")
    else:
        lines.append("\n## PDB 结构详情\n")
        lines.append("*暂无已发表的PDB结构数据*\n")

    if blast:
        lines.append("\n## 同源蛋白 (BLAST搜索)\n")
        lines.append(f"找到 {len(blast)} 个相似蛋白:\n\n")
        # Real BLAST results have pdb_id; taxonomy fallback has uniprot_id
        has_pdb = any('pdb_id' in r and r.get('pdb_id') for r in blast)
        if has_pdb:
            lines.append("| PDB ID | 相似度 | E-value | 描述 |\n")
            lines.append("|--------|--------|---------|------|\n")
            for r in blast[:15]:
                pid = r.get('pdb_id', r.get('uniprot_id', 'N/A'))
                identity_raw = r.get('identity', 0)
                qcov = r.get('query_coverage', 0)
                identity = round((identity_raw / qcov) * 100) if qcov > 0 else identity_raw
                identity = min(identity, 100)
                evalue = r.get('evalue', None)
                evalue_str = f"{evalue:.1e}" if evalue is not None else '-'
                desc = r.get('title') or r.get('description', r.get('protein_name', ''))[:60]
                lines.append(f"| {pid} | {identity}% | {evalue_str} | {desc} |\n")
        else:
            lines.append("| UniProt ID | 基因名 | 蛋白质名称 |\n")
            lines.append("|------------|--------|------------|\n")
            for r in blast[:15]:
                lines.append(f"| {r.get('uniprot_id')} | {r.get('gene_name', 'N/A')} | {r.get('protein_name', 'N/A')} |\n")

    lines.append("\n## 实验建议\n")
    if coverage >= 80 and len(structures) >= 3:
        lines.append("✅ **高度可行** - 该蛋白已有良好的结构覆盖，建议基于现有结构开展工作。\n")
        if structures:
            best = min(structures, key=lambda s: s.get('resolution') or 999)
            lines.append(f"最佳结构: {best['pdb_id']} (分辨率: {best.get('resolution', 'N/A')} Å)\n")
    elif coverage >= 50 or len(structures) >= 1:
        lines.append("⚠️ **中等可行** - 有一定结构覆盖，建议补足缺失区域。\n")
        if blast:
            lines.append(f"可通过BLAST找到的 {len(blast)} 个同源结构进行建模指导。\n")
    else:
        lines.append("🔴 **挑战性较高** - 结构覆盖不足，建议: \n")
        lines.append("1. 表达纯化蛋白进行结构解析\n")
        lines.append("2. 使用AlphaFold等工具进行结构预测\n")
        lines.append("3. 优先选择结构保守的域进行表达\n")
        if blast:
            lines.append(f"4. 参考 {len(blast)} 个同源蛋白的结构信息\n")

    return ''.join(lines)

def _calculate_feasibility_scores(data: dict) -> dict:
    uniprot = data.get('uniprot', {})
    structures = data.get('pdb_structures', [])
    coverage = data.get('coverage', 0)
    seq_len = uniprot.get('sequence_length', 0)
    scores = {}

    xr_score = 5
    if seq_len < 500: xr_score += 2
    elif seq_len > 1000: xr_score -= 1
    if coverage >= 50: xr_score += 2
    if any('x-ray' in s.get('method', '').lower() for s in structures): xr_score += 1
    if any(s.get('resolution') and s['resolution'] < 2.5 for s in structures): xr_score += 1
    xr_score = max(1, min(10, xr_score))
    scores['X-ray'] = {'score': xr_score, 'assessment': '推荐' if xr_score >= 7 else '可行' if xr_score >= 5 else '困难'}

    mw = uniprot.get('mass', 0)
    em_score = 5
    if mw > 150000: em_score += 3
    elif mw > 50000: em_score += 1
    elif mw < 50000: em_score -= 2
    if any('electron microscopy' in s.get('method', '').lower() or 'cryo' in s.get('method', '').lower() for s in structures): em_score += 2
    if coverage >= 50: em_score += 1
    em_score = max(1, min(10, em_score))
    scores['Cryo-EM'] = {'score': em_score, 'assessment': '高度推荐' if em_score >= 8 else '推荐' if em_score >= 6 else '困难'}

    nmr_score = 5
    if seq_len < 300: nmr_score += 3
    elif seq_len > 500: nmr_score -= 2
    if any('nmr' in s.get('method', '').lower() for s in structures): nmr_score += 1
    nmr_score = max(1, min(10, nmr_score))
    scores['NMR'] = {'score': nmr_score, 'assessment': '推荐' if nmr_score >= 7 else '可行' if nmr_score >= 5 else '困难'}

    # Bonus: real BLAST homologs boost feasibility
    blast = data.get('blast_results', [])
    real_blast = [r for r in blast if r.get('source') == 'BLAST']
    if real_blast:
        max_identity = max((r.get('identity', 0) for r in real_blast), default=0)
        if max_identity >= 80:
            xr_score = min(10, xr_score + 3)
            em_score = min(10, em_score + 2)
        elif max_identity >= 50:
            xr_score = min(10, xr_score + 2)
            em_score = min(10, em_score + 1)
        elif max_identity >= 30:
            xr_score = min(10, xr_score + 1)
        scores['X-ray'] = {'score': xr_score, 'assessment': '推荐' if xr_score >= 7 else '可行' if xr_score >= 5 else '困难'}
        scores['Cryo-EM'] = {'score': em_score, 'assessment': '高度推荐' if em_score >= 8 else '推荐' if em_score >= 6 else '困难'}

    return scores

# ─── Flask routes ───────────────────────────────────────────────────────────

@app.route("/api/evaluate")
def api_evaluate():
    """Run an evaluation and save result. Called by AI agent."""
    uniprot_id = request.args.get("uniprot", "").strip()
    if not uniprot_id:
        return jsonify({"success": False, "error": "UniProt ID required"}), 400
    force_blast = request.args.get("force_blast", "").lower() in ("1", "true", "yes")
    result = evaluate_uniprot(uniprot_id, force_blast=force_blast)
    if result.get('success'):
        save_evaluation(result)
        # Trigger async LLM report generation in background thread
        def _generate_report_async():
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"http://localhost:5555/api/evaluation/report/generate/{uniprot_id}",
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    logging.info(f"[api_evaluate] LLM report ready for {uniprot_id}, status={resp.status}")
            except Exception as e:
                logging.info(f"[api_evaluate] LLM report gen unavailable for {uniprot_id} -- AI agent will provide via PUT /api/evaluation/report/{uniprot_id}")
        import threading
        t = threading.Thread(target=_generate_report_async, daemon=True)
        t.start()
    return jsonify(result)

@app.route("/api/evaluations", methods=["GET"])
def api_evaluations_list():
    """List all saved evaluations, with optional search."""
    search = request.args.get("q", "").strip()
    return jsonify(list_evaluations(search))

@app.route("/api/evaluations/<uniprot_id>", methods=["GET"])
def api_evaluation_get(uniprot_id):
    """Get a single saved evaluation."""
    eval_data = load_evaluation(uniprot_id)
    if eval_data is None:
        return jsonify({"error": "Evaluation not found"}), 404
    return jsonify(eval_data)

@app.route("/api/evaluations", methods=["POST"])
def api_evaluations_save():
    """Save an evaluation result (POST JSON body). Called by AI agent."""
    data = request.get_json()
    if not data or not data.get('uniprot_id'):
        return jsonify({"success": False, "error": "uniprot_id required in body"}), 400
    ok = save_evaluation(data)
    return jsonify({"success": ok})

@app.route("/api/evaluations/<uniprot_id>/structures")
def api_evaluation_structures(uniprot_id):
    """Get PDB structures for an evaluation from SQLite DB."""
    try:
        conn = get_eval_db()
        rows = conn.execute("""
            SELECT pdb_id, method, resolution, title, deposition_date, release_date,
                   ligand, journal_if, doi, pubmed_id, organism, authors, if_tier
            FROM evaluation_pdb_structures
            WHERE uniprot_id = ?
            ORDER BY pdb_id
        """, (uniprot_id,)).fetchall()
        conn.close()

        structures = []
        for row in rows:
            rd = dict(row)
            method = rd.get('method') or ''
            method_lower = method.lower()
            m_label = method
            if 'cryo' in method_lower or 'electron microscopy' in method_lower:
                m_label = 'Cryo-EM'
            elif 'x-ray' in method_lower or 'xray' in method_lower:
                m_label = 'X-ray'
            elif 'nmr' in method_lower:
                m_label = 'NMR'

            structures.append({
                'pdb_id': rd['pdb_id'],
                'method': m_label,
                'resolution': rd.get('resolution'),
                'resolution_high': rd.get('resolution'),
                'title': rd.get('title') or '',
                'deposition_date': rd.get('deposition_date') or '',
                'release_date': rd.get('release_date') or '',
                'ligand': rd.get('ligand') or '',
                'journal_if': rd.get('journal_if'),
                'if_tier': rd.get('if_tier') or 'unknown',
                'doi': rd.get('doi') or '',
                'pubmed_id': rd.get('pubmed_id') or '',
                'organism': rd.get('organism') or '',
                'authors': rd.get('authors') or '',
            })
        return jsonify(structures)
    except Exception as e:
        logging.error(f"[api_evaluation_structures] error: {e}")
        return jsonify([])


@app.route("/api/evaluation/reports/list")
def api_evaluation_reports_list():
    """List all evaluation MD reports from the evaluations folder, linked to UniProt IDs."""
    try:
        conn = get_eval_db()
        rows = conn.execute(
            "SELECT uniprot_id, title, filename, created_at FROM evaluation_reports ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        result = []
        for row in rows:
            rd = dict(row)
            result.append({
                "uniprot_id": rd.get('uniprot_id', ''),
                "name": rd.get('filename', ''),
                "title": rd.get('title', ''),
                "filename": rd.get('filename', ''),
                "created": rd.get('created_at', ''),
            })
        return jsonify(result)
    except Exception as e:
        logging.error(f"[api_evaluation_reports_list] error: {e}")
        return jsonify([])


@app.route("/api/evaluation/report")
def api_evaluation_report():
    """Get a specific evaluation MD report by UniProt ID or filename."""
    uniprot = request.args.get("uniprot", "").strip()
    filename = request.args.get("filename", "").strip()
    if not uniprot and not filename:
        return jsonify({"error": "uniprot or filename required"}), 400
    try:
        conn = get_eval_db()
        if uniprot:
            row = conn.execute(
                "SELECT content FROM evaluation_reports WHERE uniprot_id = ?", (uniprot,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT content FROM evaluation_reports WHERE filename = ?", (filename,)
            ).fetchone()
        conn.close()
        if row and row['content']:
            return Response(row['content'], mimetype="text/markdown; charset=utf-8")
        return jsonify({"error": "Evaluation report not found"}), 404
    except Exception as e:
        logging.error(f"[api_evaluation_report] error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Generate HTML + JS, then start ────────────────────────────────────────
if __name__ == "__main__":
    html_path = SCRIPT_DIR / "pdb_index.html"
    html = open(html_path).read() if html_path.exists() else None
    if not html:
        import urllib.request
        print("HTML file missing — please run /tmp/write_js.py first")
        exit(1)
    write_js()
    print(f"JS written: {(SCRIPT_DIR / 'pdb_app.js').stat().st_size} bytes")
    print("Open: http://localhost:5555")
    init_eval_db()  # Initialize evaluation DB tables on startup
    init_weekly_reports_db()  # Initialize weekly reports DB on startup
    app.run(host="0.0.0.0", port=5555, debug=False)
