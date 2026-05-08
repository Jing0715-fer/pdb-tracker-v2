#!/usr/bin/env python3
"""
Backfill entity data for all PDB structures in the database.
Fetches from PDBe API: assembly name, polymer entity count, chain count.
Updates pdb_structures table and pdb_entities table.
"""

import sqlite3
import json
import time
import urllib.request
import urllib.error
import sys
from collections import defaultdict

DB_PATH = '/Users/lijing/Documents/my_note/LLM-Wiki/data/pdb_tracker.db'
PDB_STUCTURES_URL = 'https://www.ebi.ac.uk/pdbe/api/pdb/entry/summary/{pdb_id}'
PDB_MOLECULES_URL = 'https://www.ebi.ac.uk/pdbe/api/pdb/entry/molecules/{pdb_id}'

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_tables():
    """Ensure pdb_entities table exists."""
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
    # Add missing columns to pdb_structures
    for col, dtype in [("assembly", "TEXT"), ("polymer_entities", "INTEGER"), ("chain_count", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE pdb_structures ADD COLUMN {col} {dtype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    return conn

def fetch_pdbe_summary(pdb_id: str) -> dict:
    """Fetch entry summary from PDBe (includes assembly, entity counts)."""
    url = PDB_STUCTURES_URL.format(pdb_id=pdb_id.lower())
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            entries = data.get(pdb_id.lower(), [])
            return entries[0] if entries else {}
    except Exception as e:
        print(f"    [WARN] Summary fetch failed for {pdb_id}: {e}")
        return {}

def fetch_pdbe_molecules(pdb_id: str) -> list:
    """Fetch molecule/chain data from PDBe."""
    url = PDB_MOLECULES_URL.format(pdb_id=pdb_id.lower())
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get(pdb_id.lower(), [])
    except Exception as e:
        print(f"    [WARN] Molecules fetch failed for {pdb_id}: {e}")
        return []

def backfill_entity_data(limit: int = None, offset: int = 0, dry_run: bool = False):
    """
    Backfill entity data for all PDBs in the database.
    
    For each PDB:
    1. Fetch summary from PDBe /summary endpoint (assembly, entity counts)
    2. Fetch molecules from PDBe /molecules endpoint (chains, polymers, ligands)
    3. Update pdb_structures with: assembly, polymer_entities, chain_count
    4. Save individual entities to pdb_entities table
    """
    conn = get_conn()
    
    # Get all PDB IDs
    if limit:
        cursor = conn.execute(
            "SELECT pdb_id FROM pdb_structures ORDER BY fetch_date DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
    else:
        cursor = conn.execute("SELECT pdb_id FROM pdb_structures ORDER BY fetch_date DESC")
    
    all_pdb_ids = [row[0] for row in cursor.fetchall()]
    total = len(all_pdb_ids)
    print(f"[INFO] Found {total} PDB structures to process")
    
    success = 0
    skipped = 0
    failed = 0
    
    for i, pdb_id in enumerate(all_pdb_ids):
        pdb_id = pdb_id.upper()
        if (i + 1) % 50 == 0:
            print(f"[PROGRESS] {i+1}/{total} ({pdb_id})")
        
        # Check if already fully populated
        row = conn.execute(
            "SELECT assembly, polymer_entities, chain_count FROM pdb_structures WHERE pdb_id = ?",
            (pdb_id,)
        ).fetchone()
        
        existing_assembly, existing_poly, existing_chain = row if row else (None, None, None)
        
        if existing_assembly and existing_poly is not None and existing_chain is not None:
            # Check if pdb_entities has data
            entity_count = conn.execute(
                "SELECT COUNT(*) FROM pdb_entities WHERE pdb_id = ?", (pdb_id,)
            ).fetchone()[0]
            if entity_count > 0:
                skipped += 1
                continue
        
        try:
            # Fetch from PDBe
            summary = fetch_pdbe_summary(pdb_id)
            molecules = fetch_pdbe_molecules(pdb_id)
            
            if not summary and not molecules:
                print(f"    [SKIP] No data for {pdb_id}")
                skipped += 1
                continue
            
            # --- Extract summary data ---
            # Assembly: preferred assembly name
            assembly_name = None
            assemblies = summary.get("assemblies", [])
            for a in assemblies:
                if a.get("preferred"):
                    assembly_name = a.get("name") or a.get("assembly_id")
                    break
            if not assembly_name and assemblies:
                assembly_name = assemblies[0].get("name") or assemblies[0].get("assembly_id")
            
            # Entity counts
            entity_counts = summary.get("number_of_entities", {})
            n_polypeptide = entity_counts.get("polypeptide", 0)
            n_dna = entity_counts.get("dna", 0)
            n_rna = entity_counts.get("rna", 0)
            polymer_entities = n_polypeptide + n_dna + n_rna
            
            # Chain count from molecules
            total_chains = sum(len(ent.get("in_chains", [])) for ent in molecules)
            
            # --- Update pdb_structures ---
            if dry_run:
                print(f"    [DRY] {pdb_id}: assembly={assembly_name}, polymers={polymer_entities}, chains={total_chains}")
            else:
                conn.execute("""
                    UPDATE pdb_structures
                    SET assembly = ?, polymer_entities = ?, chain_count = ?
                    WHERE pdb_id = ?
                """, (assembly_name, polymer_entities, total_chains, pdb_id))
            
            # --- Save individual entities to pdb_entities ---
            for ent in molecules:
                entity_id = ent.get("entity_id")
                mol_type = ent.get("molecule_type", "")
                names = ent.get("molecule_name", [])
                description = names[0] if names else ent.get("synonym", "")
                genes = ent.get("gene_name", [])
                gene_name = genes[0] if genes else ""
                sources = ent.get("source", [])
                organism = sources[0].get("organism_scientific_name", "") if sources else ""
                in_chains = ent.get("in_chains", [])
                length = ent.get("length", 0)
                sequences = ent.get("pdb_sequence", "")

                for j, chain in enumerate(in_chains):
                    seq = sequences if sequences else ""
                    if dry_run:
                        pass  # skip entity insert in dry run
                    else:
                        conn.execute("""
                            INSERT OR REPLACE INTO pdb_entities 
                            (pdb_id, entity_id, asym_id, molecule_type, chain, description, organism, gene_name, sequence, length)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (pdb_id, entity_id, chain, mol_type, chain, description, organism, gene_name, seq, length))
            
            if dry_run:
                pass
            else:
                conn.commit()
            
            success += 1
            if success % 100 == 0:
                print(f"  [COMMIT] batch commit at {success} records")
            
        except Exception as e:
            print(f"    [ERROR] {pdb_id}: {e}")
            failed += 1
            try:
                conn.rollback()
            except Exception:
                pass
        
        # Rate limit: small sleep every 5 PDBs
        if i % 5 == 4:
            time.sleep(0.3)
    
    print(f"\n[DONE] success={success}, skipped={skipped}, failed={failed}")
    return success, skipped, failed

def show_sample():
    """Show sample of current data status."""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM pdb_structures").fetchone()[0]
    with_data = conn.execute("""
        SELECT COUNT(*) FROM pdb_structures 
        WHERE assembly IS NOT NULL AND polymer_entities IS NOT NULL AND chain_count IS NOT NULL
    """).fetchone()[0]
    with_entities = conn.execute("SELECT COUNT(DISTINCT pdb_id) FROM pdb_entities").fetchone()[0]
    print(f"[STATUS] Total PDBs: {total}, with assembly/polymers/chains: {with_data}, with entity details: {with_entities}")
    
    # Show sample
    rows = conn.execute("""
        SELECT pdb_id, assembly, polymer_entities, chain_count, method 
        FROM pdb_structures 
        WHERE assembly IS NOT NULL 
        LIMIT 5
    """).fetchall()
    print("\n[SAMPLE] PDBs with data:")
    for r in rows:
        print(f"  {r[0]}: assembly={r[1]}, polymers={r[2]}, chains={r[3]}, method={r[4]}")

if __name__ == "__main__":
    dry_run = "--dry" in sys.argv
    show_sample = "--status" in sys.argv
    
    init_tables()
    
    if show_sample:
        show_sample()
    elif dry_run:
        print("[DRY RUN MODE]")
        backfill_entity_data(dry_run=True)
    else:
        print("[BACKFILL MODE] Fetching entity data for all PDBs...")
        backfill_entity_data()
        show_sample()