#!/usr/bin/env python3
"""
Fetch entity information from PDBe API and store in database.
Entity info includes chains, polymers, ligands, organisms.
"""

import sqlite3
import json
import time
import sys
from typing import Optional

DB_PATH = '/Users/lijing/Documents/my_note/LLM-Wiki/data/pdb_tracker.db'

PDBE_MOLECULES_URL = 'https://www.ebi.ac.uk/pdbe/api/pdb/entry/molecules/{pdb_id}'

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_entity_table():
    """Create pdb_entities table if it doesn't exist."""
    conn = get_connection()
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
    conn.commit()
    print("[OK] Table pdb_entities ready")
    return conn

def fetch_pdbe_entities(pdb_id: str) -> list:
    """Fetch entity info from PDBe API."""
    import urllib.request
    import urllib.error
    
    url = PDBE_MOLECULES_URL.format(pdb_id=pdb_id.upper())
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get(pdb_id.lower(), [])
    except urllib.error.HTTPError as e:
        print(f"  [WARN] HTTP {e.code} for {pdb_id}: {url}")
        return []
    except Exception as e:
        print(f"  [WARN] Failed to fetch {pdb_id}: {e}")
        return []

def save_entities(conn: sqlite3.Connection, pdb_id: str, entities: list):
    """Save entity info to database."""
    rows = []
    for ent in entities:
        entity_id = ent.get('entity_id')
        mol_type = ent.get('molecule_type', '')
        
        # Get chains for this entity
        in_chains = ent.get('in_chains', [])
        sequences = ent.get('pdb_sequence', '')
        
        # Get organism info
        sources = ent.get('source', [])
        organism = ''
        if sources:
            org = sources[0]
            organism = org.get('organism_scientific_name', '')
        
        # Get gene name
        genes = ent.get('gene_name', [])
        gene_name = genes[0] if genes else ''
        
        # Get description
        names = ent.get('molecule_name', [])
        description = names[0] if names else ent.get('synonym', '')
        
        length = ent.get('length', 0)
        
        # Insert each chain as separate row
        for i, chain in enumerate(in_chains):
            seq = sequences if sequences else ''
            rows.append((
                pdb_id.upper(),
                entity_id,
                chain,
                mol_type,
                chain,
                description,
                organism,
                gene_name,
                seq,
                length
            ))
    
    if rows:
        conn.executemany("""
            INSERT OR REPLACE INTO pdb_entities 
            (pdb_id, entity_id, asym_id, molecule_type, chain, description, organism, gene_name, sequence, length)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
    
    return len(rows)

def backfill_all_entities(days_back: int = 30):
    """Backfill entity info for recent structures."""
    conn = get_connection()
    
    # Get recent PDB IDs (last N days)
    cursor = conn.execute("""
        SELECT pdb_id FROM pdb_structures 
        ORDER BY fetch_date DESC 
        LIMIT 500
    """)
    pdb_ids = [row[0] for row in cursor.fetchall()]
    
    print(f"[INFO] Found {len(pdb_ids)} recent structures")
    
    success = 0
    failed = 0
    
    for pdb_id in pdb_ids:
        # Check if already have entities
        existing = conn.execute(
            "SELECT COUNT(*) FROM pdb_entities WHERE pdb_id = ?", (pdb_id,)
        ).fetchone()[0]
        
        if existing > 0:
            print(f"  [SKIP] {pdb_id} already has {existing} entity records")
            continue
        
        entities = fetch_pdbe_entities(pdb_id)
        if entities:
            count = save_entities(conn, pdb_id, entities)
            conn.commit()
            print(f"  [OK] {pdb_id}: {count} chains, {len(entities)} entities")
            success += 1
        else:
            print(f"  [FAIL] {pdb_id}: no data")
            failed += 1
        
        time.sleep(0.3)  # Be nice to the API
    
    print(f"\n[RESULT] Success: {success}, Failed: {failed}")

def fetch_single(pdb_id: str):
    """Fetch and save entities for a single PDB ID."""
    conn = get_connection()
    
    entities = fetch_pdbe_entities(pdb_id)
    if entities:
        count = save_entities(conn, pdb_id, entities)
        conn.commit()
        print(f"[OK] {pdb_id}: saved {count} chains")
        
        # Show what we saved
        rows = conn.execute(
            "SELECT entity_id, asym_id, molecule_type, chain, description FROM pdb_entities WHERE pdb_id = ?",
            (pdb_id.upper(),)
        ).fetchall()
        for r in rows:
            print(f"  Entity {r[0]}, Chain {r[1]}: {r[2]} - {r[3]} ({r[4][:40]}...)")
    else:
        print(f"[FAIL] {pdb_id}: no data returned")

if __name__ == '__main__':
    init_entity_table()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--backfill':
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            backfill_all_entities(days)
        else:
            pdb_id = sys.argv[1]
            fetch_single(pdb_id)
    else:
        print("Usage:")
        print("  python3 fetch_pdbe_entities.py 7SYD      # fetch single PDB")
        print("  python3 fetch_pdbe_entities.py --backfill [N]  # backfill recent N days (default 30)")
