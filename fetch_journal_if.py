#!/usr/bin/env python3
"""
Journal Impact Factor Fetcher
从多个数据源获取期刊影响因子，构建完整期刊数据库
"""
import sqlite3
import json
import time
import urllib.request
import urllib.parse
from collections import defaultdict

DB_PATH = "/Users/lijing/Documents/my note/LLM Wiki/data/pdb_tracker.db"

# ========== OpenAlex API ==========
def fetch_openalex_journal(issn):
    """从 OpenAlex 获取期刊指标"""
    if not issn:
        return None
    
    url = f"https://api.openalex.org/journals?issn={issn}&per_page=1"
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data.get('results'):
                j = data['results'][0]
                return {
                    'journal': j.get('display_name'),
                    'issn': issn,
                    'sjr': j.get('metrics', {}).get('sjr'),
                    'sjr_best': j.get('metrics', {}).get('sjr_best'),
                    ' citescore': j.get('metrics', {}).get('cite_score'),
                    'h_index': j.get('h_index'),
                    'publisher': j.get('primaryublisher', {}).get('display_name') if j.get('primary_ublisher') else None,
                }
    except Exception as e:
        print(f"  OpenAlex error for {issn}: {e}")
    return None

# ========== Crossref API ==========
def fetch_crossref_journal(issn):
    """从 Crossref 获取期刊信息"""
    if not issn:
        return None
    
    url = f"https://api.crossref.org/journals/{issn}"
    try:
        req = urllib.request.Request(url, headers={
            'Accept': 'application/json',
            'User-Agent': 'PDB-Tracker/1.0 (mailto:user@example.com)'
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            j = data.get('message', {})
            return {
                'journal': j.get('title'),
                'issn': issn,
                'publisher': j.get('publisher'),
                'doi_prefix': j.get('DOI-prefix'),
            }
    except Exception as e:
        pass
    return None

# ========== ISSN to Journal mapping (common ISSNs) ==========
# 这是最可靠的期刊-ISSN映射表
ISSN_MAP = {
    'Nature': {'issn': '0028-0836', 'if_2024': 64.8, 'category': 'Multidisciplinary'},
    'Science': {'issn': '0036-8075', 'if_2024': 56.9, 'category': 'Multidisciplinary'},
    'Cell': {'issn': '0092-8674', 'if_2024': 66.9, 'category': 'Cell Biology'},
    'Nat Commun': {'issn': '2041-1723', 'if_2024': 17.7, 'category': 'Multidisciplinary'},
    'Mol Cell': {'issn': '1097-2765', 'if_2024': 19.3, 'category': 'Cell Biology'},
    'Protein Cell': {'issn': '1674-800X', 'if_2024': 21.1, 'category': 'Biochemistry'},
    'Proc.Natl.Acad.Sci.USA': {'issn': '0027-8424', 'if_2024': 11.1, 'category': 'Multidisciplinary'},
    'Nat Struct Mol Biol': {'issn': '1545-9993', 'if_2024': 16.1, 'category': 'Structural Biology'},
    'Nucleic Acids Res.': {'issn': '0305-1048', 'if_2024': 19.2, 'category': 'Biochemistry'},
    'J.Am.Chem.Soc.': {'issn': '0002-7863', 'if_2024': 15.0, 'category': 'Chemistry'},
    'Angew.Chem.Int.Ed.Engl.': {'issn': '1433-7851', 'if_2024': 16.6, 'category': 'Chemistry'},
    'J.Med.Chem.': {'issn': '0022-2623', 'if_2024': 7.3, 'category': 'Medicinal Chemistry'},
    'Embo J.': {'issn': '0261-4189', 'if_2024': 8.3, 'category': 'Cell Biology'},
    'Structure': {'issn': '0969-2126', 'if_2024': 4.4, 'category': 'Structural Biology'},
    'Sci Rep': {'issn': '2045-2322', 'if_2024': 4.6, 'category': 'Multidisciplinary'},
    'J.Biol.Chem.': {'issn': '0021-9258', 'if_2024': 4.5, 'category': 'Biochemistry'},
    'Biochemistry': {'issn': '0006-2960', 'if_2024': 3.1, 'category': 'Biochemistry'},
    'Biochem.J.': {'issn': '0264-6021', 'if_2024': 3.7, 'category': 'Biochemistry'},
    'J.Struct.Biol.': {'issn': '1047-8477', 'if_2024': 3.0, 'category': 'Structural Biology'},
    'Int.J.Biol.Macromol.': {'issn': '0141-8130', 'if_2024': 8.2, 'category': 'Biochemistry'},
    'Commun Biol': {'issn': '2397-334X', 'if_2024': 5.1, 'category': 'Biology'},
    'Viruses': {'issn': '1999-4915', 'if_2024': 4.7, 'category': 'Virology'},
    'Br.J.Pharmacol.': {'issn': '0007-1188', 'if_2024': 7.3, 'category': 'Pharmacology'},
    'Febs J.': {'issn': '1742-464X', 'if_2024': 5.5, 'category': 'Biochemistry'},
    'Protein Sci.': {'issn': '0961-8368', 'if_2024': 8.0, 'category': 'Biochemistry'},
    'Acs Chem.Biol.': {'issn': '1554-8929', 'if_2024': 5.5, 'category': 'Chemical Biology'},
    'Biorxiv': {'issn': '', 'if_2024': 0.1, 'category': 'Preprint'},
    'ChemRxiv': {'issn': '', 'if_2024': 0.1, 'category': 'Preprint'},
    'To Be Published': {'issn': '', 'if_2024': 0.0, 'category': 'Unpublished'},
    'To be published': {'issn': '', 'if_2024': 0.0, 'category': 'Unpublished'},
    
    # Additional common journals
    'Nature Medicine': {'issn': '1078-8956', 'if_2024': 58.7, 'category': 'Medicine'},
    'Nat Methods': {'issn': '1548-7091', 'if_2024': 48.0, 'category': 'Methods'},
    'Nat Biotechnol.': {'issn': '1087-0156', 'if_2024': 46.9, 'category': 'Biotechnology'},
    'Lancet': {'issn': '0140-6736', 'if_2024': 168.9, 'category': 'Medicine'},
    'N Engl J Med': {'issn': '0028-4793', 'if_2024': 158.5, 'category': 'Medicine'},
    'J Clin Invest': {'issn': '0021-9738', 'if_2024': 15.9, 'category': 'Medicine'},
    'PLoS Biol': {'issn': '1544-9173', 'if_2024': 9.8, 'category': 'Biology'},
    'PLoS One': {'issn': '1932-6203', 'if_2024': 3.7, 'category': 'Multidisciplinary'},
    'Elife': {'issn': '2050-084X', 'if_2024': 7.7, 'category': 'Biology'},
    'Mol Biol Evol': {'issn': '0737-4038', 'if_2024': 11.0, 'category': 'Evolution'},
    'J Neurosci': {'issn': '0270-6474', 'if_2024': 5.3, 'category': 'Neuroscience'},
    'Neuron': {'issn': '0896-6273', 'if_2024': 14.7, 'category': 'Neuroscience'},
    'Genome Res': {'issn': '1088-9051', 'if_2024': 7.0, 'category': 'Genomics'},
    'Genome Biol': {'issn': '1474-760X', 'if_2024': 12.3, 'category': 'Genomics'},
    'Blood': {'issn': '0006-4971', 'if_2024': 20.3, 'category': 'Hematology'},
    'Cancer Cell': {'issn': '1535-6108', 'if_2024': 50.3, 'category': 'Cancer'},
    'Nat Cancer': {'issn': '2667-167X', 'if_2024': 23.0, 'category': 'Cancer'},
    'Dev Cell': {'issn': '1534-5807', 'if_2024': 11.8, 'category': 'Developmental Biology'},
    'Curr Biol': {'issn': '0960-9822', 'if_2024': 8.1, 'category': 'Biology'},
    'Nat Cell Biol': {'issn': '1465-7392', 'if_2024': 21.3, 'category': 'Cell Biology'},
    'Mol Cell Proteomics': {'issn': '1535-9476', 'if_2024': 6.1, 'category': 'Proteomics'},
    'J Proteome Res': {'issn': '1535-3893', 'if_2024': 4.4, 'category': 'Proteomics'},
    'ACS Catal': {'issn': '2155-5435', 'if_2024': 12.8, 'category': 'Chemistry'},
    'Nat Chem Biol': {'issn': '1552-4450', 'if_2024': 14.5, 'category': 'Chemical Biology'},
    'JACS Au': {'issn': '2691-3756', 'if_2024': 8.6, 'category': 'Chemistry'},
    'Chem Sci': {'issn': '2041-6520', 'if_2024': 8.4, 'category': 'Chemistry'},
    'Nat Commun': {'issn': '2041-1723', 'if_2024': 17.7, 'category': 'Multidisciplinary'},
    'Commun Chem': {'issn': '2399-3669', 'if_2024': 6.5, 'category': 'Chemistry'},
    'Commun Biol': {'issn': '2397-334X', 'if_2024': 5.1, 'category': 'Biology'},
    'Cell Rep': {'issn': '2211-1247', 'if_2024': 8.8, 'category': 'Biology'},
    'Cell Syst': {'issn': '2405-4712', 'if_2024': 10.7, 'category': 'Systems Biology'},
    'mLife': {'issn': '', 'if_2024': 0.0, 'category': 'Microbiology'},
    'Acta Crystallogr D Struct Biol': {'issn': '2059-7983', 'if_2024': 2.3, 'category': 'Crystallography'},
    'J Mol Biol': {'issn': '0022-2836', 'if_2024': 4.7, 'category': 'Molecular Biology'},
    'Structure': {'issn': '0969-2126', 'if_2024': 4.4, 'category': 'Structural Biology'},
    'Proteins': {'issn': '0887-3585', 'if_2024': 3.0, 'category': 'Protein Science'},
    'J Chem Theory Comput': {'issn': '1549-9618', 'if_2024': 5.7, 'category': 'Computational Chemistry'},
    'J Chem Inf Model': {'issn': '1549-9596', 'if_2024': 4.5, 'category': 'Cheminformatics'},
    'Bioinformatics': {'issn': '1367-4803', 'if_2024': 5.8, 'category': 'Bioinformatics'},
    'Nucleic Acids Res': {'issn': '0305-1048', 'if_2024': 19.2, 'category': 'Biochemistry'},
    'J Biol Chem': {'issn': '0021-9258', 'if_2024': 4.5, 'category': 'Biochemistry'},
    'J. Biol. Chem.': {'issn': '0021-9258', 'if_2024': 4.5, 'category': 'Biochemistry'},
    'Proc Natl Acad Sci U S A': {'issn': '0027-8424', 'if_2024': 11.1, 'category': 'Multidisciplinary'},
    'Biochem Biophys Res Commun': {'issn': '0006-291X', 'if_2024': 3.5, 'category': 'Biochemistry'},
    'FEBS Lett': {'issn': '0014-5793', 'if_2024': 3.0, 'category': 'Biochemistry'},
    'Beilstein J Org Chem': {'issn': '2197-220X', 'if_2024': 2.8, 'category': 'Organic Chemistry'},
    'Chembiochem': {'issn': '1439-4227', 'if_2024': 2.4, 'category': 'Chemical Biology'},
    'Acta Biochim.Biophys.Sin.': {'issn': '0582-9879', 'if_2024': 2.9, 'category': 'Biochemistry'},
    'Oncogene': {'issn': '0950-9232', 'if_2024': 6.9, 'category': 'Oncology'},
    'Cancer Res': {'issn': '0008-5472', 'if_2024': 11.2, 'category': 'Cancer'},
    'J Exp Med': {'issn': '0022-1007', 'if_2024': 12.6, 'category': 'Medicine'},
    'EMBO J': {'issn': '0261-4189', 'if_2024': 8.3, 'category': 'Cell Biology'},
    'Nat Rev Mol Cell Biol': {'issn': '1471-0072', 'if_2024': 84.0, 'category': 'Reviews'},
    'Nat Rev Cancer': {'issn': '1474-175X', 'if_2024': 72.5, 'category': 'Reviews'},
    'Phys Rev Lett': {'issn': '0031-9007', 'if_2024': 8.6, 'category': 'Physics'},
    'Science': {'issn': '0036-8075', 'if_2024': 56.9, 'category': 'Multidisciplinary'},
}

# ========== 期刊别名标准化 ==========
JOURNAL_ALIASES = {
    'Nature': ['Nature', 'Nature (London)', 'Nature (Lond)', 'Nature / NPG'],
    'Science': ['Science', 'Science (New York, N.Y.)'],
    'Cell': ['Cell', 'Cell (Cambridge, Mass.)'],
    'Nat Commun': ['Nat Commun', 'Nature Communications', 'Nat. Commun.', 'Nat Commun'],
    'Mol Cell': ['Mol Cell', 'Molecular Cell'],
    'Protein Cell': ['Protein Cell', 'Protein & cell'],
    'Proc.Natl.Acad.Sci.USA': ['Proc.Natl.Acad.Sci.USA', 'Proc Natl Acad Sci U S A', 'PNAS'],
    'Nat Struct Mol Biol': ['Nat Struct Mol Biol', 'Nature Structural & Molecular Biology'],
    'Nucleic Acids Res.': ['Nucleic Acids Res.', 'Nucleic Acids Research', 'Nucleic Acids Res'],
    'J.Am.Chem.Soc.': ['J.Am.Chem.Soc.', 'J. Am. Chem. Soc.', 'JACS'],
    'Angew.Chem.Int.Ed.Engl.': ['Angew.Chem.Int.Ed.Engl.', 'Angew. Chem.', 'ANGEWANDTE CHEMIE-INTERNATIONAL EDITION'],
    'J.Med.Chem.': ['J.Med.Chem.', 'J. Med. Chem.', 'Journal of Medicinal Chemistry'],
    'Embo J.': ['Embo J.', 'EMBO J', 'The EMBO journal', 'Embo Journal'],
    'Structure': ['Structure', 'Structure (London)', 'Structure (New York, N.Y.)'],
    'Sci Rep': ['Sci Rep', 'Scientific Reports', 'Sci. Rep.'],
    'J.Biol.Chem.': ['J.Biol.Chem.', 'J. Biol. Chem.', 'Journal of Biological Chemistry', 'J Biol Chem'],
    'Biochemistry': ['Biochemistry', 'Biochemistry (Easton)', 'Biochemistry (Wash. DC)'],
    'Biochem.J.': ['Biochem.J.', 'Biochem. J.', 'The Biochemical Journal'],
    'J.Struct.Biol.': ['J.Struct.Biol.', 'J. Struct. Biol.', 'Journal of Structural Biology'],
    'Int.J.Biol.Macromol.': ['Int.J.Biol.Macromol.', 'Int. J. Biol. Macromol.', 'International Journal of Biological Macromolecules'],
    'Commun Biol': ['Commun Biol', 'Communications Biology'],
    'Viruses': ['Viruses', 'Viruses (Basel)'],
    'Br.J.Pharmacol.': ['Br.J.Pharmacol.', 'Br J Pharmacol', 'British Journal of Pharmacology'],
    'Febs J.': ['Febs J.', 'FEBS J', 'The FEBS journal'],
    'Protein Sci.': ['Protein Sci.', 'Protein Science', 'Protein Science (Cold Spring Harbor)'],
    'Acs Chem.Biol.': ['Acs Chem.Biol.', 'ACS Chem. Biol.', 'ACS Chemical Biology'],
    'Biorxiv': ['Biorxiv', 'bioRxiv', 'bioRxiv (Cold Spring Harbor Laboratory)'],
    'ChemRxiv': ['ChemRxiv', 'ChemRxiv (Cambridge University Press)'],
    'To Be Published': ['To Be Published', 'To be published', 'TBD'],
}

def normalize_journal_name(name):
    """标准化期刊名称"""
    if not name:
        return None
    
    name = name.strip()
    
    # 首先检查完全匹配
    if name in ISSN_MAP:
        return name
    
    # 检查别名
    for canonical, aliases in JOURNAL_ALIASES.items():
        if name in aliases or name.lower() in [a.lower() for a in aliases]:
            return canonical
    
    return name

def get_if(journal_name):
    """获取期刊影响因子"""
    canonical = normalize_journal_name(journal_name)
    if canonical and canonical in ISSN_MAP:
        return ISSN_MAP[canonical]['if_2024']
    return 0.0

def get_if_tier(if_val):
    """获取IF等级"""
    if if_val >= 30: return 'top'
    if if_val >= 10: return 'high'
    if if_val >= 5: return 'mid'
    if if_val > 0: return 'low'
    return 'unknown'

# ========== 主程序 ==========
def update_pdb_with_full_if():
    """更新PDB数据库中的IF信息"""
    conn = sqlite3.connect(DB_PATH)
    
    # 获取所有唯一的期刊名称
    cursor = conn.execute("SELECT DISTINCT journal FROM pdb_structures WHERE journal IS NOT NULL AND journal != ''")
    journals = [r[0] for r in cursor.fetchall()]
    
    print(f"Found {len(journals)} unique journals in database")
    
    # 统计
    updated = 0
    unmatched = []
    
    for j in journals:
        if j in ISSN_MAP:
            if_val = ISSN_MAP[j]['if_2024']
        else:
            if_val = 0.0
            unmatched.append(j)
        
        if_tier = get_if_tier(if_val)
        
        conn.execute("UPDATE pdb_structures SET journal_if = ? WHERE journal = ?", (if_val, j))
        updated += 1
    
    conn.commit()
    
    print(f"Updated {updated} journals")
    
    if unmatched:
        print(f"\nUnmatched journals ({len(unmatched)}):")
        for j in sorted(set(unmatched)):
            print(f"  - {j}")
    
    # 验证
    cursor = conn.execute("SELECT COUNT(*) FROM pdb_structures WHERE journal_if > 0")
    print(f"\nRecords with IF > 0: {cursor.fetchone()[0]}")
    
    cursor = conn.execute("SELECT COUNT(*) FROM pdb_structures WHERE journal_if = 0 OR journal_if IS NULL")
    print(f"Records with IF = 0 or NULL: {cursor.fetchone()[0]}")
    
    conn.close()

def export_journal_list():
    """导出完整的期刊IF列表"""
    journals = []
    for name, data in ISSN_MAP.items():
        journals.append({
            'journal': name,
            'issn': data.get('issn', ''),
            'if_2024': data.get('if_2024', 0),
            'category': data.get('category', '')
        })
    
    journals.sort(key=lambda x: -x['if_2024'])
    
    output_path = "/Users/lijing/Documents/my note/LLM Wiki/data/journal_if_list.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(journals, f, ensure_ascii=False, indent=2)
    
    print(f"\nExported {len(journals)} journals to {output_path}")
    
    # Also save as CSV
    csv_path = "/Users/lijing/Documents/my note/LLM Wiki/data/journal_if_list.csv"
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write("Journal,ISSN,IF_2024,Category\n")
        for j in journals:
            f.write(f'"{j["journal"]}","{j["issn"]}",{j["if_2024"]},"{j["category"]}"\n')
    
    print(f"Exported CSV to {csv_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='Update PDB database with IF values')
    parser.add_argument('--export', action='store_true', help='Export journal IF list')
    parser.add_argument('--stats', action='store_true', help='Show unmatched journals')
    args = parser.parse_args()
    
    if args.update:
        update_pdb_with_full_if()
    elif args.export:
        export_journal_list()
    else:
        update_pdb_with_full_if()
        export_journal_list()
