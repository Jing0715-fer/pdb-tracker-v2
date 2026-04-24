#!/usr/bin/env python3
"""
PDB Tracker API Server
Serves the PDB viewer HTML and provides REST API for database queries.
"""
import sqlite3
import json
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

DB_PATH = os.path.dirname(os.path.abspath(__file__)) + "/pdb_tracker.db"
HTML_PATH = os.path.dirname(os.path.abspath(__file__)) + "/pdb_viewer.html"
PORT = 8765

class PDBHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/" or path == "/index.html":
            self.serve_html()
        elif path == "/api/stats":
            self.serve_stats()
        elif path == "/api/structures":
            self.serve_structures(parsed)
        elif path == "/api/journals":
            self.serve_journals()
        elif path == "/api/trend":
            self.serve_trend()
        else:
            super().do_GET()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/api/fetch-missing-resolution":
            self.fetch_missing_resolution()
        elif path == "/api/ligand-cache":
            self.serve_ligand_cache()
        else:
            self.send_error(404, "Not Found")
    
    def fetch_missing_resolution(self):
        """Fetch missing resolution from RCSB mmCIF files"""
        import subprocess
        import re
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("""
            SELECT pdb_id, method 
            FROM pdb_structures 
            WHERE (resolution IS NULL OR resolution = '' OR resolution = 0) AND method NOT LIKE '%NMR%'
        """)
        missing = cursor.fetchall()
        
        updated = 0
        for pdb_id, method in missing:
            try:
                # Download mmCIF
                result = subprocess.run(
                    ['curl', '-sk', '--connect-timeout', '10', f'https://files.rcsb.org/download/{pdb_id.upper()}.cif'],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0 and result.stdout:
                    # Extract EM resolution
                    match = re.search(r'_em_3d_reconstruction\.resolution\s+(\d+\.?\d*)', result.stdout)
                    if match:
                        res = float(match.group(1))
                        conn.execute("UPDATE pdb_structures SET resolution = ? WHERE pdb_id = ?", (res, pdb_id))
                        updated += 1
            except:
                pass
        
        # Mark NMR as -1 (N/A)
        conn.execute("UPDATE pdb_structures SET resolution = -1 WHERE (resolution IS NULL OR resolution = '' OR resolution = 0) AND method LIKE '%NMR%'")
        conn.commit()
        conn.close()
        
        self.send_json({"updated": updated, "message": f"Updated {updated} entries"})
    
    def serve_html(self):
        try:
            with open(HTML_PATH, 'r') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(content.encode())
        except FileNotFoundError:
            self.send_error(404, "HTML file not found")
    
    def serve_stats(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN method LIKE '%ELECTRON MICROSCOPY%' THEN 1 ELSE 0 END) as cryoem,
                SUM(CASE WHEN method LIKE '%X-RAY%' THEN 1 ELSE 0 END) as xray,
                SUM(CASE WHEN method LIKE '%NMR%' THEN 1 ELSE 0 END) as nmr,
                AVG(CASE WHEN resolution IS NOT NULL THEN resolution END) as avg_res,
                AVG(CASE WHEN method LIKE '%ELECTRON MICROSCOPY%' AND resolution IS NOT NULL THEN resolution END) as cryoem_avg,
                AVG(CASE WHEN method LIKE '%X-RAY%' AND resolution IS NOT NULL THEN resolution END) as xray_avg,
                SUM(CASE WHEN ligand_info IS NOT NULL AND ligand_info != '' THEN 1 ELSE 0 END) as has_ligand
            FROM pdb_structures
        """)
        row = cursor.fetchone()
        conn.close()
        
        stats = {
            "total": row[0] or 0,
            "cryoem": row[1] or 0,
            "xray": row[2] or 0,
            "nmr": row[3] or 0,
            "avg_res": round(row[4], 2) if row[4] else None,
            "cryoem_avg_res": round(row[5], 2) if row[5] else None,
            "xray_avg_res": round(row[6], 2) if row[6] else None,
            "has_ligand": row[7] or 0
        }
        
        self.send_json(stats)
    
    def serve_structures(self, parsed):
        params = parse_qs(parsed.query)
        limit = int(params.get('limit', [50])[0])
        offset = int(params.get('offset', [0])[0])
        method = params.get('method', [None])[0]
        if_tier = params.get('if_tier', [None])[0]
        search = params.get('search', [None])[0]
        sort = params.get('sort', ['release_date'])[0]
        order = params.get('order', ['DESC'])[0]
        
        conn = sqlite3.connect(DB_PATH)
        
        # Build query
        where_clauses = []
        if method == 'cryoem':
            where_clauses.append("method LIKE '%ELECTRON MICROSCOPY%'")
        elif method == 'xray':
            where_clauses.append("method LIKE '%X-RAY%'")
        elif method == 'nmr':
            where_clauses.append("method LIKE '%NMR%'")
        
        if if_tier:
            where_clauses.append(f"if_tier = '{if_tier}'")
        
        if search:
            where_clauses.append(f"(pdb_id LIKE '%{search}%' OR title LIKE '%{search}%' OR journal LIKE '%{search}%')")
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        # Get total count
        cursor = conn.execute(f"SELECT COUNT(*) FROM pdb_structures WHERE {where_sql}")
        total = cursor.fetchone()[0]
        
        # Get data
        cursor = conn.execute(f"""
            SELECT pdb_id, method, release_date, resolution, title, doi, journal, journal_if, if_tier, ligand_info, ligand_images, ligand_names
            FROM pdb_structures
            WHERE {where_sql}
            ORDER BY {sort} {order}
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        columns = ['pdb_id', 'method', 'release_date', 'resolution', 'title', 'doi', 'journal', 'journal_if', 'if_tier', 'ligand_info', 'ligand_images', 'ligand_names']
        rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
        conn.close()
        
        self.send_json({"total": total, "data": rows, "limit": limit, "offset": offset})
    
    def serve_journals(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("""
            SELECT journal, COUNT(*) as cnt, AVG(journal_if) as avg_if
            FROM pdb_structures
            WHERE journal IS NOT NULL AND journal != ''
            GROUP BY journal
            ORDER BY cnt DESC
            LIMIT 20
        """)
        rows = [{"journal": r[0], "count": r[1], "avg_if": round(r[2], 1) if r[2] else 0} for r in cursor.fetchall()]
        conn.close()
        self.send_json(rows)
    
    def serve_trend(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("""
            SELECT 
                week_id,
                COUNT(*) as total,
                SUM(CASE WHEN method LIKE '%ELECTRON MICROSCOPY%' THEN 1 ELSE 0 END) as cryoem,
                SUM(CASE WHEN method LIKE '%X-RAY%' THEN 1 ELSE 0 END) as xray,
                AVG(CASE WHEN resolution IS NOT NULL THEN resolution END) as avg_res
            FROM pdb_structures
            WHERE week_id IS NOT NULL
            GROUP BY week_id
            ORDER BY week_id DESC
            LIMIT 12
        """)
        columns = ['week_id', 'total', 'cryoem', 'xray', 'avg_res']
        rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
        conn.close()
        self.send_json(rows)
    
    def serve_ligand_cache(self):
        """Serve all ligand images as a dict {comp_id: base64_image}"""
        conn = sqlite3.connect(DB_PATH)
        # Build cache from all entries
        cache = {}
        cursor = conn.execute("SELECT ligand_info, ligand_images FROM pdb_structures WHERE ligand_images IS NOT NULL AND ligand_images != ''")
        for ligand_info, ligand_images in cursor:
            if not ligand_info or not ligand_images:
                continue
            ligands = ligand_info.split(';')
            images = ligand_images.split(';')
            for i, ligand in enumerate(ligands):
                ligand = ligand.strip()
                if ligand and i < len(images) and images[i]:
                    comp_id = ligand.split('|')[0].strip()
                    if comp_id:
                        cache[comp_id] = images[i]
        conn.close()
        self.send_json(cache)
    
    def send_json(self, data):
        content = json.dumps(data, ensure_ascii=False)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content.encode())
    
    def log_message(self, format, *args):
        pass  # Suppress logging

def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    server = HTTPServer(('localhost', PORT), PDBHandler)
    print(f"🚀 PDB Tracker API Server running at http://localhost:{PORT}")
    print(f"   HTML: http://localhost:{PORT}/")
    print(f"   API:  http://localhost:{PORT}/api/structures")
    print(f"\nPress Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
