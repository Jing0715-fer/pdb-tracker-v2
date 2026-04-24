#!/usr/bin/env python3
"""
Fetch missing resolution data from RCSB by downloading mmCIF files
For NMR and Cryo-EM entries that don't have resolution in our DB
"""
import sqlite3
import subprocess
import time
import re

DB_PATH = "/Users/lijing/Documents/my note/LLM Wiki/data/pdb_tracker.db"

def curl_download(url, retries=3):
    """Download file via curl (SSL bypass)"""
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ['curl', '-sk', '--connect-timeout', '15', url],
                capture_output=True, text=True, timeout=20
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except:
            if attempt < retries - 1:
                time.sleep(2)
    return None

def extract_em_resolution(cif_content):
    """Extract EM resolution from mmCIF content"""
    # Look for _em_3d_reconstruction.resolution
    match = re.search(r'_em_3d_reconstruction\.resolution\s+(\d+\.?\d*)', cif_content)
    if match:
        return float(match.group(1))
    
    # Fallback: look for any resolution field in EM section
    match = re.search(r'_em[^.]*resolution[^.]*\s+(\d+\.?\d*)', cif_content, re.IGNORECASE)
    if match:
        return float(match.group(1))
    
    return None

def fetch_missing_resolutions():
    """Fetch missing resolutions for PDB entries"""
    conn = sqlite3.connect(DB_PATH)
    
    # Get entries with missing resolution
    cursor = conn.execute("""
        SELECT pdb_id, method 
        FROM pdb_structures 
        WHERE resolution IS NULL OR resolution = '' OR resolution = 0
    """)
    missing = cursor.fetchall()
    
    print(f"Found {len(missing)} entries with missing resolution")
    print("=" * 50)
    
    updated = 0
    failed = []
    
    for pdb_id, method in missing:
        print(f"\n[{updated+1}/{len(missing)}] {pdb_id} ({method})")
        
        # For NMR, there's typically no resolution
        if method and 'NMR' in method.upper():
            # Set a placeholder for NMR (-1 indicates N/A)
            conn.execute("UPDATE pdb_structures SET resolution = -1 WHERE pdb_id = ?", (pdb_id,))
            print(f"  ℹ️  NMR - no resolution applicable (set to -1)")
            updated += 1
            continue
        
        # Download mmCIF file
        url = f"https://files.rcsb.org/download/{pdb_id.upper()}.cif"
        cif_content = curl_download(url)
        
        if not cif_content or 'ERROR' in cif_content[:100]:
            print(f"  ❌ Failed to download mmCIF")
            failed.append(pdb_id)
            continue
        
        # Extract EM resolution
        res = extract_em_resolution(cif_content)
        
        if res and res > 0:
            conn.execute("UPDATE pdb_structures SET resolution = ? WHERE pdb_id = ?", (res, pdb_id))
            print(f"  ✅ Resolution: {res} Å")
            updated += 1
        else:
            print(f"  ❌ No resolution found in mmCIF")
            failed.append(pdb_id)
        
        time.sleep(0.3)
    
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 50)
    print(f"Updated: {updated} entries")
    if failed:
        print(f"Failed: {len(failed)} - {', '.join(failed[:10])}")
        if len(failed) > 10:
            print(f"   ... and {len(failed) - 10} more")
    
    return updated, failed

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fetch missing resolution from RCSB mmCIF')
    parser.add_argument('--fetch', action='store_true', help='Fetch missing resolutions')
    args = parser.parse_args()
    
    if args.fetch:
        fetch_missing_resolutions()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
