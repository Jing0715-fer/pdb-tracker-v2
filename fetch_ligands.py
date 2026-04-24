#!/usr/bin/env python3
"""
Fetch ligand/drug information from RCSB mmCIF files.
Stores both comp_id and full name for tooltip display.
"""
import sqlite3
import subprocess
import re
import time

DB_PATH = "/Users/lijing/Documents/my note/LLM Wiki/data/pdb_tracker.db"

METAL_IONS = {'MG', 'ZN', 'NA', 'CL', 'K', 'CA', 'FE', 'CU', 'MN', 'CO', 'NI', 'CD', 'HG', 'PB', 'BA', 'SR', 'AL', 'GA', 'LI', 'CS', 'RB', 'TL', 'BI', 'SN', 'PT', 'PD', 'AU', 'AG', 'RU', 'RH', 'IR', 'OS', 'MO', 'W', 'V', 'CR'}
WATER = {'HOH', 'DOD', 'WAT', 'H2O', 'D2O'}
COMMON = {'ACT', 'ACN', 'DMSO', 'DMF', 'GOL', 'EDO', 'PEG', 'PG4', 'MPD', 'CIT', 'MES', 'HEPES', 'TRIS', 'BME', 'NAG', 'MAN', 'GAL', 'FUC', 'AMP', 'ADP', 'ATP', 'GMP', 'GDP', 'CMP', 'CDP', 'UDP', 'UTP', 'SO4', 'SO3', 'PO4', 'NO3', 'NO2', 'NH4', 'ACO', 'FMT', 'TMA', 'GOA', 'GLO', 'P6G', '1PE', '2PE', 'C8E', 'LMT', 'UMQ', 'PGE', 'MRD', 'TBU', 'DTT', 'TEO'}
SINGLE_LETTER = set('ACDEFGHIKLMNPQRSTVWY')

def should_filter(comp_id):
    if not comp_id:
        return True
    upper = comp_id.upper()
    if upper in METAL_IONS or upper in WATER or upper in COMMON:
        return True
    if len(comp_id) == 1 and upper in SINGLE_LETTER:
        return True
    return False

def get_ligands(pdb_id):
    """Extract filtered ligand information from mmCIF"""
    try:
        result = subprocess.run(
            f'curl -sk --connect-timeout 10 --max-time 30 "https://files.rcsb.org/download/{pdb_id.upper()}.cif" 2>/dev/null',
            shell=True, capture_output=True, text=True, timeout=35
        )
        data = result.stdout
    except:
        return []
    
    if not data or len(data) < 100:
        return []
    
    ligands = []
    lines = data.split('\n')
    in_section = False
    for line in lines:
        if '_pdbx_entity_nonpoly.entity_id' in line:
            in_section = True
            continue
        if in_section:
            if line.startswith('#') or (line.startswith('_') and 'entity_nonpoly' not in line):
                break
            m = re.match(r"\s*(\d+)\s+'([^']+)'\s+(\S+)", line)
            if m:
                comp_id = m.group(3)
                name = m.group(2).strip()
                if not should_filter(comp_id):
                    # Store as "comp_id|name" format
                    ligands.append(f"{comp_id}|{name}")
    return list(set(ligands))[:5]

def fetch_ligands_for_all():
    """Fetch ligands for all PDB entries"""
    conn = sqlite3.connect(DB_PATH)
    
    # Clear existing ligand_info
    conn.execute("UPDATE pdb_structures SET ligand_info = ''")
    
    cursor = conn.execute("SELECT pdb_id FROM pdb_structures")
    all_pdbs = [row[0] for row in cursor.fetchall()]
    
    print(f"Fetching ligands for {len(all_pdbs)} PDB entries...", flush=True)
    
    has_ligand = 0
    
    for i, pdb_id in enumerate(all_pdbs):
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(all_pdbs)}, has_ligand: {has_ligand}", flush=True)
        
        ligands = get_ligands(pdb_id)
        
        if ligands:
            has_ligand += 1
            ligand_str = '; '.join(ligands[:5])
            conn.execute(
                "UPDATE pdb_structures SET ligand_info = ? WHERE pdb_id = ?",
                (ligand_str, pdb_id)
            )
        else:
            conn.execute(
                "UPDATE pdb_structures SET ligand_info = '' WHERE pdb_id = ?",
                (pdb_id,)
            )
        
        time.sleep(0.1)
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Completed!", flush=True)
    print(f"   Entries with ligands: {has_ligand}", flush=True)
    
    return has_ligand

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Fetch ligand info from RCSB mmCIF')
    parser.add_argument('--fetch', action='store_true', help='Fetch ligands for all entries')
    args = parser.parse_args()
    
    if args.fetch:
        fetch_ligands_for_all()
    else:
        parser.print_help()
