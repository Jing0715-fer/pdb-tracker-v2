#!/usr/bin/env python3
"""
Backfill entity data for PDB structures in evaluation_pdb_structures.
These PDBs are not in pdb_structures so the main backfill misses them.
"""

import sqlite3
import json
import time
import urllib.request
import urllib.error
import sys
import os

DB_PATH = '/Users/lijing/Documents/my_note/LLM-Wiki/data/pdb_tracker.db'
PDB_MOLECULES_URL = 'https://www.ebi.ac.uk/pdbe/api/pdb/entry/molecules/{pdb_id}'
DRY_RUN = '--dry-run' in sys.argv

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_tables():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdb_entities (
            pdb_id          TEXT NOT NULL,
            entity_id       INTEGER NOT NULL,
            asym_id         TEXT,
            molecule_type   TEXT,
            chain           TEXT,
            description     TEXT,
            organism        TEXT,
            gene_name       TEXT,
            sequence        TEXT,
            length          INTEGER,
            is_ligand       INTEGER GENERATED ALWAYS AS (
                molecule_type NOT LIKE '%polypeptide%' AND 
                molecule_type NOT LIKE '%DNA%' AND 
                molecule_type NOT LIKE '%RNA%'
            ) STORED,
            FOREIGN KEY (pdb_id) REFERENCES pdb_structures(pdb_id) ON DELETE CASCADE,
            UNIQUE(pdb_id, entity_id, asym_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_pdb ON pdb_entities(pdb_id)")
    conn.close()

def fetch_pdbe_molecules(pdb_id: str, retries=3) -> dict | None:
    url = PDB_MOLECULES_URL.format(pdb_id=pdb_id.lower())
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 503 and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            print(f"  HTTP {e.code} for {pdb_id}: {e.reason}", file=sys.stderr)
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"  Error for {pdb_id}: {e}", file=sys.stderr)
            return None
    return None

def get_eval_pdbs():
    """Get all PDB IDs from evaluation_pdb_structures."""
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT pdb_id FROM evaluation_pdb_structures ORDER BY pdb_id").fetchall()
    conn.close()
    return [r[0] for r in rows]

def already_has_entities(pdb_id: str) -> bool:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM pdb_entities WHERE pdb_id = ?", (pdb_id,)).fetchone()[0]
    conn.close()
    return count > 0

def insert_entities(pdb_id: str, molecules: list):
    conn = get_conn()
    inserted = 0
    for mol in molecules:
        entity_id = mol.get('entity_id')
        for chain_info in mol.get('chains', []):
            asym_id = chain_info.get('asym_id', '')
            chain = chain_info.get('struct_asym_id', {}).get('name', asym_id)
            conn.execute("""
                INSERT OR IGNORE INTO pdb_entities 
                (pdb_id, entity_id, asym_id, molecule_type, chain, description, organism, gene_name, sequence, length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pdb_id,
                entity_id,
                asym_id,
                mol.get('molecule_type', ''),
                chain,
                mol.get('description', ''),
                mol.get('organism_name', ''),
                mol.get('gene_name', ''),
                mol.get('sequence', ''),
                mol.get('length', 0),
            ))
            inserted += 1
    conn.commit()
    conn.close()
    return inserted

def main():
    init_tables()
    pdbs = get_eval_pdbs()
    print(f"Found {len(pdbs)} PDBs in evaluation_pdb_structures")
    
    total_new = 0
    total_skip = 0
    
    for i, pdb_id in enumerate(pdbs):
        if already_has_entities(pdb_id):
            print(f"[{i+1}/{len(pdbs)}] {pdb_id}: already has entity data, skipping")
            total_skip += 1
            continue
        
        if DRY_RUN:
            print(f"[{i+1}/{len(pdbs)}] {pdb_id}: DRY RUN - would fetch")
            continue
        
        print(f"[{i+1}/{len(pdbs)}] {pdb_id}: fetching...", end=" ", flush=True)
        molecules = fetch_pdbe_molecules(pdb_id)
        
        if molecules is None:
            print("failed")
            time.sleep(0.5)
            continue
        
        # Parse molecules - PDBe molecules API returns {pdb_id: [molecules]}
        parsed = []
        # Get the first (and only) key which is the pdb_id
        mol_list = list(molecules.values())[0] if isinstance(molecules, dict) else molecules
        for mol in mol_list:
            # chains info
            chains = []
            for chain_key in ['in_chains', 'in_struct_asyms']:
                in_chains = mol.get(chain_key, [])
                for c in in_chains:
                    chains.append({
                        'asym_id': c,
                        'struct_asym_id': {'name': c},
                    })
            
            # gene_name can be a list
            gene = mol.get('gene_name', [])
            gene_str = ','.join(gene) if isinstance(gene, list) else str(gene or '')
            
            # molecule_name / description
            mol_names = mol.get('molecule_name', mol.get('description', ''))
            if isinstance(mol_names, list):
                mol_name = mol_names[0] if mol_names else ''
            else:
                mol_name = str(mol_names)
            
            parsed.append({
                'entity_id': mol.get('entity_id'),
                'molecule_type': mol.get('molecule_type', ''),
                'description': mol_name,
                'organism_name': mol.get('source', [{}])[0].get('organism_scientific_name', '') if mol.get('source') else '',
                'gene_name': gene_str,
                'sequence': mol.get('sequence', ''),
                'length': mol.get('length', 0),
                'chains': chains,
            })
        
        inserted = insert_entities(pdb_id, parsed)
        print(f"inserted {inserted} rows")
        total_new += inserted
        time.sleep(0.3)  # be nice to PDBe API
    
    print(f"\nDone. New rows: {total_new}, Skipped (existing): {total_skip}")

if __name__ == '__main__':
    main()
