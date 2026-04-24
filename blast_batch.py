#!/usr/bin/env python3
"""
Batch BLAST evaluation for multiple proteins.
Usage: python3 blast_batch.py [uniprot_id ...]
If no args, runs all uniprot_ids in the database that lack BLAST results.
"""
import sys
import time
import json
import logging
import sqlite3
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = '/Users/lijing/Documents/my_note/LLM-Wiki/data'
DB_PATH = f'{DATA_DIR}/pdb_tracker.db'
API_URL = 'http://localhost:5555/api/evaluate'

def get_pending():
    """Get uniprot_ids in DB that lack BLAST results."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT e.uniprot_id 
        FROM evaluations e
        LEFT JOIN evaluation_blast_results b ON e.uniprot_id = b.uniprot_id
        WHERE b.uniprot_id IS NULL
    """).fetchall()
    conn.close()
    return [r[0] for r in rows]

def run_evaluate(uniprot_id, force_blast=True, wait_sec=5):
    """Call the Flask API to run evaluation."""
    params = {'uniprot': uniprot_id}
    if force_blast:
        params['force_blast'] = 'true'
    try:
        resp = requests.get(API_URL, params=params, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        return result
    except Exception as e:
        logger.error(f"API error for {uniprot_id}: {e}")
        return None

def main():
    if len(sys.argv) > 1:
        uniprot_ids = sys.argv[1:]
    else:
        uniprot_ids = get_pending()
        logger.info(f"Auto-detected {len(uniprot_ids)} proteins need BLAST: {uniprot_ids}")

    results = []
    for i, uid in enumerate(uniprot_ids):
        logger.info(f"[{i+1}/{len(uniprot_ids)}] Evaluating {uid} with BLAST...")
        result = run_evaluate(uid, force_blast=True)
        if result:
            blast_count = len(result.get('blast_results', []))
            pdb_count = len(result.get('pdb_structures', []))
            scores = result.get('scores', {})
            xray = scores.get('X-ray', {}).get('score', '?')
            cryo = scores.get('Cryo-EM', {}).get('score', '?')
            top_blast = result['blast_results'][0] if blast_count > 0 else None
            identity = top_blast['identity'] if top_blast else 0
            top_pdb = top_blast['pdb_id'] if top_blast else '-'
            logger.info(f"  → PDB={pdb_count}, BLAST={blast_count}, top={top_pdb} (id={identity}), X-ray={xray}, Cryo-EM={cryo}")
            results.append({
                'uniprot_id': uid,
                'pdb_count': pdb_count,
                'blast_count': blast_count,
                'top_pdb': top_pdb,
                'identity': identity,
                'xray': xray,
                'cryoem': cryo,
                'success': result.get('success', False),
            })
        else:
            results.append({'uniprot_id': uid, 'success': False})
            logger.error(f"  → FAILED")
        
        # Be polite to NCBI
        time.sleep(3)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Batch complete: {len(results)} proteins")
    for r in results:
        if r['success']:
            logger.info(f"  {r['uniprot_id']}: PDB={r['pdb_count']}, BLAST={r['blast_count']}, top={r['top_pdb']}(id={r['identity']}), X-ray={r['xray']}, Cryo-EM={r['cryoem']}")
        else:
            logger.info(f"  {r['uniprot_id']}: FAILED")
    logger.info(f"{'='*60}\n")

if __name__ == '__main__':
    main()
