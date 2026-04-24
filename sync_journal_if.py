#!/usr/bin/env python3
"""
Journal IF Sync from OpenAlex - Using urllib with SSL context
从 OpenAlex API 定期同步期刊影响因子数据
"""
import sqlite3
import json
import time
import ssl
import urllib.request
import urllib.parse
from datetime import datetime

DB_PATH = "/Users/lijing/Documents/my note/LLM Wiki/data/pdb_tracker.db"
JOURNAL_LIST_PATH = "/Users/lijing/Documents/my note/LLM Wiki/data/journal_if_list.json"
OPENALEX_API = "https://api.openalex.org"

# SSL context that skips verification
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

ISSN_MAP = {
    '0028-0836': 'Nature',
    '0036-8075': 'Science',
    '0092-8674': 'Cell',
    '2041-1723': 'Nat Commun',
    '1097-2765': 'Mol Cell',
    '1674-800X': 'Protein Cell',
    '0027-8424': 'Proc Natl Acad Sci USA',
    '1545-9993': 'Nat Struct Mol Biol',
    '0305-1048': 'Nucleic Acids Res',
    '0002-7863': 'J Am Chem Soc',
    '1433-7851': 'Angew Chem Int Ed',
    '0022-2623': 'J Med Chem',
    '0261-4189': 'Embo J',
    '0969-2126': 'Structure',
    '2045-2322': 'Sci Rep',
    '0021-9258': 'J Biol Chem',
    '0006-2960': 'Biochemistry',
    '0264-6021': 'Biochem J',
    '1047-8477': 'J Struct Biol',
    '0141-8130': 'Int J Biol Macromol',
    '2397-334X': 'Commun Biol',
    '1999-4915': 'Viruses',
    '0006-4971': 'Blood',
    '1474-175X': 'Nat Rev Cancer',
    '1471-0072': 'Nat Rev Mol Cell Biol',
}

def fetch_url(url, retries=3):
    """Fetch URL with SSL bypass"""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'Accept': 'application/json',
                'User-Agent': 'PDB-Tracker/1.0'
            })
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"    Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None

def fetch_journal_by_issn(issn):
    url = f"{OPENALEX_API}/journals?filter=issn:{issn}&per_page=1"
    data = fetch_url(url)
    if data and data.get('results'):
        return data['results'][0]
    return None

def extract_metrics(journal):
    if not journal:
        return None
    summary = journal.get('summary_stats', {})
    return {
        'display_name': journal.get('display_name'),
        'issn_l': journal.get('issn_l'),
        'if_2yr': round(summary.get('2yr_mean_citedness', 0), 2),
        'h_index': summary.get('h_index', 0),
        'works_count': journal.get('works_count', 0),
    }

def sync_all_journals():
    existing_journals = {}
    try:
        with open(JOURNAL_LIST_PATH, 'r') as f:
            for j in json.load(f):
                existing_journals[j['journal']] = j
    except:
        pass
    
    updated = 0
    failed = []
    
    print(f"Syncing {len(ISSN_MAP)} journals from OpenAlex...")
    print("=" * 60)
    
    for issn, canonical_name in ISSN_MAP.items():
        print(f"\n[{updated+1}/{len(ISSN_MAP)}] {canonical_name} (ISSN: {issn})")
        
        data = fetch_journal_by_issn(issn)
        if not data:
            print(f"  ❌ Not found")
            failed.append(canonical_name)
            continue
        
        metrics = extract_metrics(data)
        if metrics and metrics['if_2yr'] > 0:
            print(f"  ✅ {metrics['display_name']} | IF={metrics['if_2yr']} | h={metrics['h_index']}")
            
            existing_journals[canonical_name] = {
                'journal': metrics['display_name'] or canonical_name,
                'issn': metrics['issn_l'] or issn,
                'if_2024': metrics['if_2yr'],
                'h_index': metrics['h_index'],
                'works_count': metrics['works_count'],
                'source': 'openalex',
                'last_updated': datetime.now().strftime('%Y-%m-%d')
            }
            updated += 1
        else:
            failed.append(canonical_name)
        
        time.sleep(0.5)
    
    journal_list = list(existing_journals.values())
    journal_list.sort(key=lambda x: -x.get('if_2024', 0))
    
    with open(JOURNAL_LIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(journal_list, f, ensure_ascii=False, indent=2)
    
    csv_path = JOURNAL_LIST_PATH.replace('.json', '.csv')
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('Journal,ISSN,IF_2024,h_index,Works Count,Last Updated\n')
        for j in journal_list:
            f.write(f"{j['journal']},{j.get('issn','')},{j.get('if_2024','')},{j.get('h_index','')},{j.get('works_count','')},{j.get('last_updated','')}\n")
    
    print("\n" + "=" * 60)
    print(f"✅ Synced: {updated} journals")
    if failed:
        print(f"❌ Failed: {len(failed)}")
    print(f"Saved to: {JOURNAL_LIST_PATH}")
    
    return updated, failed

def update_pdb_with_journal_if():
    conn = sqlite3.connect(DB_PATH)
    
    try:
        with open(JOURNAL_LIST_PATH, 'r') as f:
            journals = {j['journal']: j for j in json.load(f)}
    except Exception as e:
        print(f"Error loading journal list: {e}")
        conn.close()
        return
    
    updated = 0
    for name, data in journals.items():
        if_val = data.get('if_2024', 0)
        if if_val > 0:
            result = conn.execute("""
                UPDATE pdb_structures 
                SET journal_if = ?
                WHERE journal = ? AND (journal_if = 0 OR journal_if IS NULL)
            """, (if_val, name))
            updated += result.rowcount
    
    conn.execute("""
        UPDATE pdb_structures 
        SET if_tier = CASE 
            WHEN journal_if >= 30 THEN 'top'
            WHEN journal_if >= 10 THEN 'high'
            WHEN journal_if >= 5 THEN 'mid'
            WHEN journal_if > 0 THEN 'low'
            ELSE 'unknown'
        END
        WHERE if_tier IS NULL OR if_tier = ''
    """)
    conn.commit()
    
    cursor = conn.execute("SELECT COUNT(*) FROM pdb_structures WHERE journal_if > 0")
    with_if = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM pdb_structures")
    total = cursor.fetchone()[0]
    
    print(f"Updated {updated} PDB records ({with_if}/{total} have IF)")
    conn.close()

def show_stats():
    conn = sqlite3.connect(DB_PATH)
    
    print("\n📊 Journal IF Distribution:")
    cursor = conn.execute("""
        SELECT 
            SUM(CASE WHEN journal_if >= 30 THEN 1 ELSE 0 END),
            SUM(CASE WHEN journal_if >= 10 AND journal_if < 30 THEN 1 ELSE 0 END),
            SUM(CASE WHEN journal_if >= 5 AND journal_if < 10 THEN 1 ELSE 0 END),
            SUM(CASE WHEN journal_if > 0 AND journal_if < 5 THEN 1 ELSE 0 END),
            SUM(CASE WHEN journal_if = 0 OR journal_if IS NULL THEN 1 ELSE 0 END)
        FROM pdb_structures
    """)
    r = cursor.fetchone()
    print(f"  🔴 Top (≥30):    {r[0]}")
    print(f"  🟠 High (10-30): {r[1]}")
    print(f"  🟢 Mid (5-10):   {r[2]}")
    print(f"  ⚪ Low (<5):     {r[3]}")
    print(f"  ❓ Unknown:      {r[4]}")
    
    try:
        with open(JOURNAL_LIST_PATH, 'r') as f:
            jlist = json.load(f)
        print(f"\n📚 Journal list: {len(jlist)} entries")
        print("\nTop 10:")
        for j in jlist[:10]:
            print(f"  {j['journal']}: IF={j.get('if_2024', 'N/A')}")
    except:
        pass
    
    conn.close()

def search_journal(name):
    url = f"{OPENALEX_API}/journals?search={urllib.parse.quote(name)}&per_page=5"
    data = fetch_url(url)
    if data and data.get('results'):
        print(f"\n🔍 Results for '{name}':\n")
        for j in data['results'][:5]:
            m = extract_metrics(j)
            print(f"  {m['display_name']} | ISSN: {m['issn_l']} | IF: {m['if_2yr']}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Sync Journal IF from OpenAlex')
    parser.add_argument('--sync', action='store_true', help='Sync all journals')
    parser.add_argument('--search', type=str, help='Search journal')
    parser.add_argument('--update-db', action='store_true', help='Update PDB database')
    parser.add_argument('--stats', action='store_true', help='Show stats')
    args = parser.parse_args()
    
    if args.sync:
        sync_all_journals()
        update_pdb_with_journal_if()
    elif args.search:
        search_journal(args.search)
    elif args.update_db:
        update_pdb_with_journal_if()
    elif args.stats:
        show_stats()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
