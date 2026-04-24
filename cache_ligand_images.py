#!/usr/bin/env python3
"""
Fetch and cache PubChem ligand images locally.
Stores base64 encoded images in the database.
"""
import sqlite3
import subprocess
import re
import time
import base64

DB_PATH = "/Users/lijing/Documents/my note/LLM Wiki/data/pdb_tracker.db"

def fetch_pubchem_image(ligand_name):
    """Fetch ligand image from PubChem and return base64"""
    # First get CID
    result = subprocess.run(
        f'curl -sk --connect-timeout 10 --max-time 30 "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ligand_name}/cids/JSON" 2>/dev/null',
        shell=True, capture_output=True, text=True, timeout=35
    )
    
    if result.returncode != 0 or not result.stdout:
        return None
    
    try:
        import json
        data = json.loads(result.stdout)
        if not data.get('IdentifierList', {}).get('CID'):
            return None
        cid = data['IdentifierList']['CID'][0]
    except:
        return None
    
    # Download image
    img_result = subprocess.run(
        f'curl -sk --connect-timeout 10 --max-time 30 "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG?image_size=300x300" 2>/dev/null',
        shell=True, capture_output=True, timeout=35
    )
    
    if img_result.returncode == 0 and img_result.stdout and len(img_result.stdout) > 100:
        # Check if it's actually a PNG
        if img_result.stdout[:4] == b'\x89PNG':
            return base64.b64encode(img_result.stdout).decode('utf-8')
    
    return None

def get_unique_ligands():
    """Get all unique ligand IDs from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT ligand_info FROM pdb_structures WHERE ligand_info IS NOT NULL AND ligand_info != ''")
    ligands = set()
    for row in cursor:
        ligand_str = row[0]
        for ligand in ligand_str.split(';'):
            ligand = ligand.strip()
            if ligand:
                # Remove |name suffix if present
                comp_id = ligand.split('|')[0].strip()
                if comp_id:
                    ligands.add(comp_id)
    conn.close()
    return ligands

def cache_all_images():
    """Fetch and cache images for all unique ligands"""
    ligands = get_unique_ligands()
    print(f"Found {len(ligands)} unique ligands")
    
    # Store cached images in memory
    cached = {}
    
    for i, ligand in enumerate(ligands):
        if (i + 1) % 10 == 0:
            print(f"Progress: {i+1}/{len(ligands)}")
        
        img_data = fetch_pubchem_image(ligand)
        if img_data:
            cached[ligand] = img_data
            print(f"  ✓ {ligand}")
        else:
            print(f"  ✗ {ligand}")
        
        time.sleep(0.3)  # Rate limit
    
    print(f"\nCached {len(cached)} images")
    return cached

def update_database(cached_images):
    """Update database with cached images"""
    conn = sqlite3.connect(DB_PATH)
    
    # Build update for each PDB entry
    cursor = conn.execute("SELECT pdb_id, ligand_info FROM pdb_structures WHERE ligand_info IS NOT NULL AND ligand_info != ''")
    
    for pdb_id, ligand_info in cursor:
        if not ligand_info:
            continue
        
        # Parse ligands
        ligands = ligand_info.split(';')
        img_parts = []
        name_parts = []
        
        for ligand in ligands:
            ligand = ligand.strip()
            if not ligand:
                continue
            
            parts = ligand.split('|')
            comp_id = parts[0].strip()
            
            # Get cached image
            img = cached_images.get(comp_id, '')
            img_parts.append(img)
            
            # Get name if available
            name = parts[1].strip() if len(parts) > 1 else ''
            name_parts.append(name)
        
        # Store as semicolon-separated base64 (empty string for no image)
        conn.execute(
            "UPDATE pdb_structures SET ligand_images = ?, ligand_names = ? WHERE pdb_id = ?",
            (';'.join(img_parts), ';'.join(name_parts), pdb_id)
        )
    
    conn.commit()
    conn.close()
    print("Database updated")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch', action='store_true', help='Fetch images')
    args = parser.parse_args()
    
    if args.fetch:
        cached = cache_all_images()
        update_database(cached)
    else:
        parser.print_help()
