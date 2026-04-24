#!/usr/bin/env python3
"""
PDB + UniProt Tracker Database
轻量级 SQLite 数据库，用于 PDB 结构追踪和靶点分析

所有路径可通过环境变量配置：
  PDB_DATA_DIR    - 数据根目录 (默认 ~/.pdb-tracker/)
  PDB_DB_DIR      - 数据库目录 (默认 $PDB_DATA_DIR/data/)
  PDB_DB_NAME     - 数据库文件名 (默认 pdb_tracker.db)
  PDB_RAW_DIR     - 原始数据目录 (默认 $PDB_DATA_DIR/raw/)
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== 配置 (支持环境变量覆盖) ==========
def _get_data_dir() -> Path:
    if os.getenv("PDB_DATA_DIR"):
        return Path(os.getenv("PDB_DATA_DIR"))
    return Path.home() / ".pdb-tracker"

DATA_DIR = _get_data_dir()
DB_DIR = Path(os.getenv("PDB_DB_DIR", str(DATA_DIR / "data")))
DB_PATH = DB_DIR / os.getenv("PDB_DB_NAME", "pdb_tracker.db")
RAW_DATA_DIR = Path(os.getenv("PDB_RAW_DIR", str(DATA_DIR / "raw")))

# Journal Impact Factors (2024-2025)
JOURNAL_IF = {
    'Nature': 64.8, 'Nat Commun': 17.7, 'Science': 56.9, 'Cell': 66.9,
    'Mol Cell': 19.3, 'Protein Cell': 21.1, 'Proc.Natl.Acad.Sci.USA': 11.1,
    'Nat Struct Mol Biol': 16.1, 'Nucleic Acids Res.': 19.2, 'J.Am.Chem.Soc.': 15.0,
    'Angew.Chem.Int.Ed.Engl.': 16.6, 'J.Med.Chem.': 7.3, 'Embo J.': 8.3,
    'Structure': 4.4, 'Sci Rep': 4.6, 'J.Biol.Chem.': 4.5, 'Biochemistry': 3.1,
    'Biochem.J.': 3.7, 'J.Struct.Biol.': 3.0, 'Int.J.Biol.Macromol.': 8.2,
    'Commun Biol': 5.1, 'Viruses': 4.7, 'Br.J.Pharmacol.': 7.3, 'Febs J.': 5.5,
    'Protein Sci.': 8.0, 'Acs Chem.Biol.': 5.5,
}

RCSB_SEARCH_API = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_API = "https://data.rcsb.org/rest/v1/core/entry/"
RCSB_GRAPHQL = "https://data.rcsb.org/graphql"

# 常见配体过滤名单（这些不计入"有意义配体"）
METAL_IONS = {'MG', 'ZN', 'NA', 'CL', 'K', 'CA', 'FE', 'CU', 'MN', 'CO', 'NI', 'CD', 'HG', 'PB', 'BA', 'SR', 'AL', 'GA', 'MN', 'MO', 'W', 'V', 'CR', 'TI', 'ZR', 'NA', 'LI', 'CS'}
WATER = {'HOH', 'DOD', 'WAT', 'H2O', 'D2O'}
COMMON_BUFFERS = {'ACT', 'ACN', 'DMSO', 'GOL', 'EDO', 'MES', 'TRIS', 'HEPES', 'PBS', 'PIPES', 'BME', 'EDTA', 'EGTA', 'SPERMID', 'PUT', 'TMAO', 'GLC', 'MAN', 'NAG', 'FLC', 'CIT'}
SINGLE_AA = set('ACDEFGHIKLMNPQRSTVWY')  # 单字母氨基酸

def is_meaningful_ligand(comp_id: str) -> bool:
    """判断一个配体是否是有意义的（药物/辅因子/底物等），而非金属/水/缓冲液"""
    cid = comp_id.upper()
    if cid in METAL_IONS or cid in WATER or cid in COMMON_BUFFERS:
        return False
    if len(cid) == 1 and cid in SINGLE_AA:
        return False
    return True

# ========== Schema ==========
SCHEMA = """
-- PDB 结构主表
CREATE TABLE IF NOT EXISTS pdb_structures (
    pdb_id          TEXT PRIMARY KEY,
    method          TEXT NOT NULL,
    release_date    TEXT NOT NULL,
    resolution      REAL,
    resolution_high REAL,
    title           TEXT,
    doi             TEXT,
    journal         TEXT,
    journal_if      REAL,
    authors         TEXT,
    organisms       TEXT,
    ligands         TEXT,
    pubmed_id       TEXT,
    fetch_date      TEXT NOT NULL,
    week_id         TEXT,
    
    is_cryoem       INTEGER GENERATED ALWAYS AS (method LIKE '%ELECTRON MICROSCOPY%') STORED,
    is_xray         INTEGER GENERATED ALWAYS AS (method LIKE '%X-RAY%') STORED,
    if_tier         TEXT GENERATED ALWAYS AS (
        CASE 
            WHEN journal_if >= 30 THEN 'top'
            WHEN journal_if >= 10 THEN 'high'
            WHEN journal_if >= 5 THEN 'mid'
            WHEN journal_if > 0 THEN 'low'
            ELSE 'unknown'
        END
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_pdb_release ON pdb_structures(release_date);
CREATE INDEX IF NOT EXISTS idx_pdb_method ON pdb_structures(method);
CREATE INDEX IF NOT EXISTS idx_pdb_week ON pdb_structures(week_id);
CREATE INDEX IF NOT EXISTS idx_pdb_journal ON pdb_structures(journal);

-- PDB 链级详情（PDB ↔ UniProt 映射）
CREATE TABLE IF NOT EXISTS pdb_chains (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pdb_id          TEXT NOT NULL,
    asym_id         TEXT,
    entity_id       INTEGER,
    uniprot_accession TEXT,
    uniprot_id      TEXT,
    gene_name       TEXT,
    organism_tax_id  INTEGER,
    organism_name   TEXT,
    sequence        TEXT,
    start_residue   INTEGER,
    end_residue     INTEGER,
    
    FOREIGN KEY (pdb_id) REFERENCES pdb_structures(pdb_id) ON DELETE CASCADE,
    UNIQUE(pdb_id, asym_id)
);

CREATE INDEX IF NOT EXISTS idx_chain_uniprot ON pdb_chains(uniprot_accession);
CREATE INDEX IF NOT EXISTS idx_chain_pdb ON pdb_chains(pdb_id);

-- 周报聚合数据
CREATE TABLE IF NOT EXISTS weekly_snapshots (
    week_id         TEXT PRIMARY KEY,
    week_start      TEXT NOT NULL,
    week_end        TEXT NOT NULL,
    total_structures INTEGER,
    cryoem_count    INTEGER,
    xray_count      INTEGER,
    nmr_count       INTEGER,
    other_count     INTEGER,
    cryoem_res_dist TEXT,
    xray_res_dist   TEXT,
    cryoem_avg_res  REAL,
    xray_avg_res    REAL,
    top_journals    TEXT,
    if_dist         TEXT,
    raw_json_path   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshot_week ON weekly_snapshots(week_start);

-- 靶点追踪表
CREATE TABLE IF NOT EXISTS target_tracking (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uniprot_acc     TEXT NOT NULL UNIQUE,
    gene_name       TEXT,
    protein_name    TEXT,
    disease_area    TEXT,
    target_notes    TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- 靶点对应结构
CREATE TABLE IF NOT EXISTS target_structures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id       INTEGER NOT NULL,
    pdb_id          TEXT NOT NULL,
    method          TEXT,
    release_date    TEXT,
    resolution      REAL,
    journal         TEXT,
    journal_if      REAL,
    is_new          INTEGER DEFAULT 0,
    first_seen_at   TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (target_id) REFERENCES target_tracking(id) ON DELETE CASCADE,
    FOREIGN KEY (pdb_id) REFERENCES pdb_structures(pdb_id) ON DELETE CASCADE,
    UNIQUE(target_id, pdb_id)
);

CREATE INDEX IF NOT EXISTS idx_ts_target ON target_structures(target_id);
CREATE INDEX IF NOT EXISTS idx_ts_pdb ON target_structures(pdb_id);
CREATE INDEX IF NOT EXISTS idx_ts_new ON target_structures(is_new);

-- 文献摘要缓存
CREATE TABLE IF NOT EXISTS pubmed_abstracts (
    pmid            TEXT PRIMARY KEY,
    pdb_id          TEXT,
    doi             TEXT,
    title           TEXT,
    abstract        TEXT,
    authors         TEXT,
    journal         TEXT,
    pub_date        TEXT,
    fetch_date      TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (pdb_id) REFERENCES pdb_structures(pdb_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_abstract_pdb ON pubmed_abstracts(pdb_id);
CREATE INDEX IF NOT EXISTS idx_abstract_doi ON pubmed_abstracts(doi);
"""


# ========== 数据库初始化 ==========
def init_db():
    """初始化数据库"""
    WIKI_PATH.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"✅ 数据库已初始化: {DB_PATH}")


# ========== 工具函数 ==========
def get_if(journal: str) -> float:
    return JOURNAL_IF.get(journal, 0.0)


def week_id(date_str: str) -> str:
    """返回 YYYY-Www 格式的周ID"""
    dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
    return dt.strftime('%Y-W%W')


def to_float(v):
    try:
        return float(v)
    except:
        return None


def fetch_json(url: str, data=None) -> Optional[dict]:
    """Fetch JSON from URL"""
    headers = {"Content-Type": "application/json"}
    try:
        if data:
            req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers)
        else:
            req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return None


# ========== PDB 数据获取 ==========
def fetch_pdb_ids(start_date: str, end_date: str) -> List[str]:
    """从 RCSB Search API 获取日期范围内的 PDB IDs"""
    print(f"📡 查询 RCSB: {start_date} → {end_date}")
    data = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_accession_info.initial_release_date",
                "operator": "range",
                "value": {"from": start_date, "to": end_date}
            }
        },
        "request_options": {"paginate": {"start": 0, "rows": 10000}},
        "return_type": "entry"
    }
    result = fetch_json(RCSB_SEARCH_API, data=data)
    if not result:
        return []
    return [r['identifier'] for r in result.get('result_set', [])]


def fetch_pdb_ligands(pdb_id: str) -> tuple[List[str], List[str]]:
    """通过 GraphQL API 获取 PDB 配体信息，返回 (有意义配体列表, 所有配体列表)"""
    import subprocess
    query = {
        "query": f'{{ entry(entry_id: "{pdb_id}") {{ rcsb_id nonpolymer_entities {{ rcsb_id pdbx_entity_nonpoly {{ comp_id name }} rcsb_nonpolymer_entity {{ pdbx_description }} }} }} }}'
    }
    try:
        proc = subprocess.run(
            ['curl', '-s', '-X', 'POST', RCSB_GRAPHQL,
             '-H', 'Content-Type: application/json',
             '-d', json.dumps(query),
             '--max-time', '15'],
            capture_output=True, text=True, timeout=20
        )
        if proc.returncode != 0:
            return [], []
        data = json.loads(proc.stdout)
        if 'data' not in data or not data['data']:
            return [], []
        entry = data['data'].get('entry', {})
        nonpolys = entry.get('nonpolymer_entities', []) or []
        all_ligands = []
        meaningful_ligands = []
        for np in nonpolys:
            pdbx = np.get('pdbx_entity_nonpoly', {}) or {}
            rcsb_np = np.get('rcsb_nonpolymer_entity', {}) or {}
            comp_id = pdbx.get('comp_id', '') or ''
            name = (rcsb_np.get('pdbx_description') or pdbx.get('name') or '').strip()
            all_ligands.append(f"{comp_id}:{name}" if name else comp_id)
            if is_meaningful_ligand(comp_id):
                meaningful_ligands.append(f"{comp_id}:{name}" if name else comp_id)
        return meaningful_ligands, all_ligands
    except Exception:
        return [], []


def fetch_pdb_entry(pdb_id: str, with_ligands: bool = True) -> Optional[dict]:
    """获取单个 PDB 条目详情（含配体信息）"""
    data = fetch_json(f"{RCSB_DATA_API}{pdb_id}")
    if not data:
        return None
    
    res_info = data.get('rcsb_entry_info', {})
    resolution = res_info.get('resolution_combined', [None])[0]
    
    methods = [m.get('method') for m in data.get('exptl', [])]
    method = methods[0] if methods else 'Unknown'
    
    citation = data.get('rcsb_primary_citation', {})
    journal = citation.get('journal_abbrev', 'Unknown')
    doi = citation.get('pdbx_database_id_DOI', '')
    
    accession = data.get('rcsb_accession_info', {})
    release_date = accession.get('initial_release_date', '')[:10]
    
    entry = {
        'pdb_id': pdb_id,
        'method': method,
        'release_date': release_date,
        'resolution': resolution,
        'title': data.get('struct', {}).get('title', ''),
        'doi': doi,
        'journal': journal,
        'journal_if': get_if(journal),
        'fetch_date': datetime.now().strftime('%Y-%m-%d'),
        'week_id': week_id(release_date) if release_date else None,
        'ligands': '',
        'ligand_names': '',
        'ligand_info': '',
    }
    
    if with_ligands:
        meaningful, all_ligs = fetch_pdb_ligands(pdb_id)
        entry['ligand_names'] = '|'.join(meaningful) if meaningful else ''
        entry['ligand_info'] = '|'.join(all_ligs) if all_ligs else ''
        entry['ligands'] = '|'.join(meaningful) if meaningful else ''
    
    return entry


def fetch_all_entries(pdb_ids: List[str], concurrency: int = 10) -> List[dict]:
    """并发获取所有条目详情"""
    print(f"📥 获取 {len(pdb_ids)} 个条目详情...")
    entries = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(fetch_pdb_entry, pid): pid for pid in pdb_ids}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result:
                entries.append(result)
            if (i + 1) % 50 == 0:
                print(f"  进度: {i+1}/{len(pdb_ids)}")
    return entries


# ========== 数据库操作 ==========
def insert_structures(conn: sqlite3.Connection, entries: List[dict]):
    """插入结构记录（含配体信息）"""
    sql = """
    INSERT OR REPLACE INTO pdb_structures 
    (pdb_id, method, release_date, resolution, title, doi, journal, journal_if,
     ligands, ligand_names, ligand_info, fetch_date, week_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for e in entries:
        conn.execute(sql, (
            e['pdb_id'], e['method'], e['release_date'], e.get('resolution'),
            e.get('title'), e.get('doi'), e.get('journal'), e.get('journal_if'),
            e.get('ligands', ''), e.get('ligand_names', ''), e.get('ligand_info', ''),
            e['fetch_date'], e.get('week_id')
        ))
    conn.commit()
    print(f"✅ 写入 {len(entries)} 条结构记录")


def get_entries_for_range(conn: sqlite3.Connection, start: str, end: str) -> List[dict]:
    """从数据库获取指定日期范围的所有条目"""
    cursor = conn.execute("""
        SELECT pdb_id, method, release_date, resolution, title, doi, journal, journal_if, fetch_date, week_id
        FROM pdb_structures
        WHERE release_date BETWEEN ? AND ?
    """, (start, end))
    rows = cursor.fetchall()
    entries = []
    for r in rows:
        entries.append({
            'pdb_id': r[0],
            'method': r[1],
            'release_date': r[2],
            'resolution': r[3],
            'title': r[4],
            'doi': r[5],
            'journal': r[6],
            'journal_if': r[7],
            'fetch_date': r[8],
            'week_id': r[9]
        })
    return entries


def compute_snapshot(conn: sqlite3.Connection, week_start: str, week_end: str) -> dict:
    """计算周报聚合数据"""
    cursor = conn.execute("""
        SELECT method, resolution, journal, journal_if
        FROM pdb_structures
        WHERE release_date BETWEEN ? AND ?
    """, (week_start, week_end))
    
    rows = cursor.fetchall()
    
    cryoem = [(r[1], r[2], r[3]) for r in rows if r[0] and 'ELECTRON MICROSCOPY' in r[0]]
    xray = [(r[1], r[2], r[3]) for r in rows if r[0] and 'X-RAY' in r[0]]
    
    def avg_res(items):
        vals = [r[0] for r in items if r[0] is not None]
        return sum(vals) / len(vals) if vals else None
    
    def res_dist(items, bins):
        counts = {b: 0 for b in bins}
        for r in items:
            if r[0] is None:
                continue
            for bound in bins:
                if r[0] <= bound:
                    counts[bound] += 1
                    break
        return counts
    
    cryoem_bins = [2.5, 3.0, 3.5, 10.0]
    xray_bins = [1.5, 2.0, 2.5, 3.0]
    
    from collections import Counter
    journal_counts = Counter(r[2] for r in rows if r[2])
    
    snapshot = {
        'week_id': week_id(week_start),
        'week_start': week_start,
        'week_end': week_end,
        'total': len(rows),
        'cryoem_count': len(cryoem),
        'xray_count': len(xray),
        'cryoem_avg_res': avg_res(cryoem),
        'xray_avg_res': avg_res(xray),
        'top_journals': journal_counts.most_common(10),
    }
    
    return snapshot


def add_target(conn: sqlite3.Connection, uniprot_acc: str, gene_name: str = None, 
               protein_name: str = None, disease_area: str = None, notes: str = None):
    """添加追踪靶点"""
    conn.execute("""
        INSERT OR REPLACE INTO target_tracking 
        (uniprot_acc, gene_name, protein_name, disease_area, target_notes, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (uniprot_acc, gene_name, protein_name, disease_area, notes))
    conn.commit()
    print(f"✅ 靶点已添加: {uniprot_acc} ({gene_name or 'N/A'})")


def update_target_structures(conn: sqlite3.Connection, target_id: int, pdb_ids: List[str]):
    """更新靶点对应的PDB结构"""
    for pdb_id in pdb_ids:
        cursor = conn.execute("SELECT method, release_date, resolution, journal, journal_if FROM pdb_structures WHERE pdb_id = ?", (pdb_id,))
        row = cursor.fetchone()
        if row:
            conn.execute("""
                INSERT OR IGNORE INTO target_structures 
                (target_id, pdb_id, method, release_date, resolution, journal, journal_if)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (target_id, pdb_id, row[0], row[1], row[2], row[3], row[4]))
    conn.commit()


# ========== 查询函数 ==========
def query_resolution_trend(conn: sqlite3.Connection, months: int = 3) -> List[dict]:
    """查询过去 N 个月的分辨率趋势"""
    cursor = conn.execute("""
        SELECT week_id, week_start, cryoem_avg_res, xray_avg_res, cryoem_count, xray_count
        FROM weekly_snapshots
        WHERE week_start >= date('now', ?)
        ORDER BY week_start
    """, (f'-{months} months',))
    return [dict(zip(['week_id', 'week_start', 'cryoem_avg_res', 'xray_avg_res', 'cryoem_count', 'xray_count'], r)) 
            for r in cursor.fetchall()]


def query_target_new_structures(conn: sqlite3.Connection, uniprot_acc: str) -> List[dict]:
    """查询靶点的新结构"""
    cursor = conn.execute("""
        SELECT ts.pdb_id, p.method, p.release_date, p.resolution, p.journal, p.doi
        FROM target_structures ts
        JOIN pdb_structures p ON ts.pdb_id = p.pdb_id
        JOIN target_tracking t ON ts.target_id = t.id
        WHERE t.uniprot_acc = ? AND ts.is_new = 1
        ORDER BY p.release_date DESC
    """, (uniprot_acc,))
    cols = ['pdb_id', 'method', 'release_date', 'resolution', 'journal', 'doi']
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


# ========== 主函数 ==========
def main():
    import argparse
    parser = argparse.ArgumentParser(description='PDB Tracker Database')
    parser.add_argument('--init', action='store_true', help='初始化数据库')
    parser.add_argument('--fetch', metavar=('START', 'END'), nargs=2, help='抓取日期范围数据')
    parser.add_argument('--add-target', metavar='UNIPROT_ACC', help='添加追踪靶点')
    parser.add_argument('--list-targets', action='store_true', help='列出所有靶点')
    parser.add_argument('--query', choices=['trend', 'new'], help='执行查询')
    parser.add_argument('--backfill-ligands', action='store_true', help='回填所有历史结构的配体信息')
    args = parser.parse_args()
    
    if args.init:
        init_db()
        return
    
    # 确保数据库已初始化
    if not DB_PATH.exists():
        print("❌ 数据库未初始化，请先运行 --init")
        return
    
    conn = sqlite3.connect(DB_PATH)
    
    if args.fetch:
        start, end = args.fetch

        # Step 1: Query RCSB API for PDB IDs in date range
        pdb_ids = fetch_pdb_ids(start, end)
        print(f"📦 RCSB 返回 {len(pdb_ids)} 个结构")

        if not pdb_ids:
            print("⚠️ 没有找到新结构")
        else:
            # Step 2: Check which IDs are already in the database
            existing = set()
            placeholders = ','.join(['?'] * len(pdb_ids))
            cursor = conn.execute(
                f"SELECT pdb_id FROM pdb_structures WHERE pdb_id IN ({placeholders}) AND release_date BETWEEN ? AND ?",
                pdb_ids + [start, end]
            )
            for row in cursor.fetchall():
                existing.add(row[0])

            missing_ids = [pid for pid in pdb_ids if pid not in existing]
            print(f"📊 数据库已有: {len(existing)}, 缺失需获取: {len(missing_ids)}")

            if missing_ids:
                entries = fetch_all_entries(missing_ids)
                insert_structures(conn, entries)
                print(f"✅ 新增 {len(entries)} 条记录")
            else:
                print("✅ 数据已完整，无需 API 调用")
            
            # 获取本周所有条目（从数据库）
            entries = get_entries_for_range(conn, start, end)
            
            # 保存原始 JSON
            raw_path = RAW_DATA_DIR / f"pdb_weekly_raw_{end}.json"
            with open(raw_path, 'w') as f:
                json.dump({'entries': entries, 'week_start': start, 'week_end': end}, f, ensure_ascii=False)
            
            # 计算快照
            snapshot = compute_snapshot(conn, start, end)
            print(f"📊 快照: {snapshot}")
            
            conn.execute("""
                INSERT OR REPLACE INTO weekly_snapshots 
                (week_id, week_start, week_end, total_structures, cryoem_count, xray_count,
                 cryoem_avg_res, xray_avg_res, raw_json_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (snapshot['week_id'], start, end, snapshot['total'], snapshot['cryoem_count'],
                  snapshot['xray_count'], snapshot['cryoem_avg_res'], snapshot['xray_avg_res'], str(raw_path)))
            conn.commit()
    
    elif args.add_target:
        add_target(conn, args.add_target)
    
    elif args.list_targets:
        cursor = conn.execute("SELECT id, uniprot_acc, gene_name, protein_name, disease_area, is_active FROM target_tracking")
        print("\n🎯 追踪靶点列表:")
        print(f"{'ID':<4} {'UniProt':<12} {'Gene':<10} {'Protein':<30} {'Disease':<15} {'Active'}")
        print("-" * 85)
        for r in cursor.fetchall():
            print(f"{r[0]:<4} {r[1]:<12} {r[2] or 'N/A':<10} {(r[3] or '')[:28]:<30} {(r[4] or '')[:13]:<15} {'✓' if r[5] else '✗'}")
    
    elif args.query == 'trend':
        results = query_resolution_trend(conn, 3)
        print("\n📈 过去3个月分辨率趋势:")
        for r in results:
            print(f"  {r['week_start']}: Cryo-EM avg={r['cryoem_avg_res']:.2f}Å ({r['cryoem_count']}), X-ray avg={r['xray_avg_res']:.2f}Å ({r['xray_count']})")

    elif args.backfill_ligands:
        print("🔄 回填配体信息...")
        cursor = conn.execute("SELECT pdb_id FROM pdb_structures WHERE ligands IS NULL OR ligands = '' OR ligand_names IS NULL OR ligand_names = ''")
        pdb_ids = [r[0] for r in cursor.fetchall()]
        print(f"📋 需回填配体的结构: {len(pdb_ids)} 个")
        
        updated = 0
        for i, pdb_id in enumerate(pdb_ids):
            meaningful, all_ligs = fetch_pdb_ligands(pdb_id)
            conn.execute(
                "UPDATE pdb_structures SET ligands=?, ligand_names=?, ligand_info=? WHERE pdb_id=?",
                ('|'.join(meaningful) if meaningful else '', '|'.join(meaningful) if meaningful else '', '|'.join(all_ligs) if all_ligs else '', pdb_id)
            )
            updated += 1
            if (i + 1) % 50 == 0:
                conn.commit()
                print(f"  进度: {i+1}/{len(pdb_ids)}")
        conn.commit()
        print(f"✅ 完成，回填了 {updated} 个结构的配体信息")

    conn.close()


if __name__ == "__main__":
    main()
