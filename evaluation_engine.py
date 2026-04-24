#!/usr/bin/env python3
"""
Evaluation Engine - 靶点结构可行性评估引擎

负责：
1. 获取 UniProt 数据
2. 获取 PDB 结构数据
3. 判断是否需要 BLAST 搜索（PDB < 5 或 覆盖度 < 50%）
4. 执行真正的 NCBI BLAST 同源搜索
5. 计算可行性评分
6. 生成评估报告
"""

import re
import time
import json
import urllib.parse
import subprocess
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== API 客户端 ====================

class UniProtClient:
    """UniProt API 客户端"""
    
    def __init__(self):
        self.base_url = "https://rest.uniprot.org/uniprotkb"
    
    def get_sequence(self, uniprot_id: str) -> Optional[str]:
        """获取蛋白序列 - 使用 curl"""
        try:
            cmd = [
                'curl', '-s', '--connect-timeout', '30', '--max-time', '60',
                '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                f'{self.base_url}/{uniprot_id}.fasta'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')
                return ''.join(lines[1:])
        except Exception as e:
            logger.warning(f"Failed to get sequence for {uniprot_id}: {e}")
        return None
    
    def get_data(self, uniprot_id: str) -> Dict:
        """获取 UniProt 数据 - 使用 curl"""
        try:
            cmd = [
                'curl', '-s', '--connect-timeout', '30', '--max-time', '60',
                '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                f'{self.base_url}/{uniprot_id}?format=json'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
            if result.returncode == 0 and result.stdout:
                import json
                return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Failed to get UniProt data for {uniprot_id}: {e}")
        return {}


class PDBClient:
    """PDB API 客户端"""
    
    def __init__(self):
        self.session = None
    
    def _get_session(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
        return self.session
    
    def get_structures(self, pdb_ids: List[str]) -> List[Dict]:
        """批量获取 PDB 结构信息"""
        structures = []
        for pdb_id in pdb_ids:
            try:
                info = self.get_structure_info(pdb_id)
                if info:
                    structures.append(info)
            except:
                pass
        return structures
    
    def get_structure_info(self, pdb_id: str) -> Optional[Dict]:
        """获取单个 PDB 结构信息"""
        try:
            session = self._get_session()
            
            # 获取基本结构信息
            url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            
            # 获取实验方法
            exp_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}/exptl"
            exp_resp = session.get(exp_url, timeout=15)
            method = "Unknown"
            if exp_resp.status_code == 200:
                exp_data = exp_resp.json()
                if exp_data:
                    method = exp_data[0].get('experimentalMethod', 'Unknown')
            
            # 获取分辨率
            res_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}/refinement"
            resolution = None
            res_resp = session.get(res_url, timeout=15)
            if res_resp.status_code == 200:
                res_data = res_resp.json()
                if res_data:
                    resolution = res_data.get('refinement.resolution', [None])[0]
            
            # 获取配体
            ligands = self._get_ligands(pdb_id)
            
            return {
                'pdb_id': pdb_id,
                'title': data.get('struct', {}).get('title', ''),
                'method': method,
                'resolution': resolution,
                'ligands': ligands,
            }
        except Exception as e:
            logger.warning(f"Failed to get PDB info for {pdb_id}: {e}")
            return None
    
    def _get_ligands(self, pdb_id: str) -> List[str]:
        """获取配体信息"""
        ligands = []
        try:
            session = self._get_session()
            url = f"https://data.rcsb.org/rest/v1/core/nonpolymer-entity/{pdb_id}"
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for entity in data:
                    comp_id = entity.get('nonpolymer_comp', {}).get('comp_id', '')
                    if comp_id:
                        ligands.append(comp_id)
        except:
            pass
        return ligands


class BLASTClient:
    """NCBI BLAST 同源搜索客户端"""
    
    def __init__(self):
        self.session = None
    
    def _get_session(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
        return self.session
    
    def search(self, uniprot_id: str, sequence: str, max_wait: int = 300) -> Dict[str, Any]:
        """
        执行 NCBI BLAST 搜索
        
        Args:
            uniprot_id: UniProt ID
            sequence: 蛋白序列
            max_wait: 最大等待时间（秒）
        
        Returns:
            BLAST 结果，包含同源 PDB 结构
        """
        logger.info(f"Starting NCBI BLAST for {uniprot_id} (sequence length: {len(sequence)})")
        
        # 1. 提交 BLAST 任务
        job_id = self._submit_job(sequence)
        if not job_id:
            return {'success': False, 'error': 'Failed to submit BLAST job'}
        
        logger.info(f"BLAST job submitted: {job_id}")
        
        # 2. 等待结果
        status = self._wait_for_results(job_id, max_wait)
        if not status:
            return {'success': False, 'error': 'BLAST search timeout'}
        
        # 3. 获取结果
        results = self._get_results(job_id)
        
        # 4. 解析结果
        parsed = self._parse_results(results, uniprot_id)
        
        logger.info(f"BLAST completed: found {len(parsed)} homolog structures")
        
        return {
            'success': True,
            'results': parsed,
            'job_id': job_id
        }
    
    def _submit_job(self, sequence: str) -> Optional[str]:
        """提交 BLAST 任务"""
        query_params = urllib.parse.urlencode({
            'CMD': 'Put',
            'QUERY': sequence[:10000],  # 限制序列长度
            'DATABASE': 'pdb',
            'PROGRAM': 'blastp',
            'EXPECT': '0.01',
            'HITLIST_SIZE': '50',
            'FILTER': 'L',
            'FORMAT_TYPE': 'XML'
        })
        
        try:
            cmd = [
                'curl', '-s', '--connect-timeout', '30', '--max-time', '90',
                '-X', 'POST',
                '-d', query_params,
                'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=95)
            
            if result.returncode != 0:
                logger.error(f"BLAST submission failed: {result.stderr}")
                return None
            
            # 解析 RID
            match = re.search(r'RID = (\w+)', result.stdout)
            if match:
                return match.group(1)
            
            # 检查错误
            error_match = re.search(r'ERROR|FAILED', result.stdout)
            if error_match:
                logger.error(f"BLAST submission error: {result.stdout[:500]}")
                return None
            
            return None
            
        except Exception as e:
            logger.error(f"BLAST submission exception: {e}")
            return None
    
    def _wait_for_results(self, job_id: str, max_wait: int) -> bool:
        """等待 BLAST 结果"""
        start_time = time.time()
        check_interval = 10  # 每10秒检查一次
        
        while time.time() - start_time < max_wait:
            try:
                cmd = [
                    'curl', '-s', '--connect-timeout', '30', '--max-time', '60',
                    f'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&FORMAT_OBJECT=Status&RID={job_id}'
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
                
                if 'Status=READY' in result.stdout:
                    logger.info(f"BLAST job {job_id} is ready")
                    return True
                elif 'Status=WAITING' in result.stdout or 'Status=UNKNOWN' in result.stdout:
                    logger.info(f"BLAST still running... ({int(time.time() - start_time)}s)")
                    time.sleep(check_interval)
                else:
                    # 检查是否有错误
                    if 'ERROR' in result.stdout[:500] or 'FAILED' in result.stdout[:500]:
                        logger.error(f"BLAST error: {result.stdout[:500]}")
                        return False
                    time.sleep(check_interval)
                
            except Exception as e:
                logger.warning(f"Error waiting for BLAST: {e}")
                time.sleep(check_interval)
        
        logger.warning(f"BLAST wait timeout after {max_wait}s")
        return False
    
    def _get_results(self, job_id: str) -> str:
        """获取 BLAST XML 结果"""
        cmd = [
            'curl', '-s', '--connect-timeout', '30', '--max-time', '120',
            f'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&FORMAT_TYPE=XML&RID={job_id}'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=125)
        return result.stdout
    
    def _parse_results(self, xml_results: str, query_id: str) -> List[Dict]:
        """解析 BLAST XML 结果"""
        homologs = []
        
        try:
            # 使用正则提取关键信息
            # 提取每个 Hit
            hit_pattern = r'<Hit>.*?</Hit>'
            hits = re.findall(hit_pattern, xml_results, re.DOTALL)
            
            for hit in hits:
                # 提取 PDB ID
                hsp_pattern = r'<Hit_id>.*?<Hit_def>(.*?)</Hit_def>'
                match = re.search(hsp_pattern, hit, re.DOTALL)
                if not match:
                    continue
                
                hit_def = match.group(1)
                
                # 从 Hit_def 中提取 PDB ID (格式: "pdb|PDB_ID|description")
                pdb_match = re.search(r'pdb\|(\w+)\|', hit_def)
                if not pdb_match:
                    continue
                
                pdb_id = pdb_match.group(1).upper()
                
                # 提取 E-value
                evalue_pattern = r'<Hsp_evalue>(.*?)</Hsp_evalue>'
                evalue_match = re.search(evalue_pattern, hit)
                evalue = float(evalue_match.group(1)) if evalue_match else 1.0
                
                # 提取 identity
                identity_pattern = r'<Hsp_identity>(\d+)</Hsp_identity>'
                identity_match = re.search(identity_pattern, hit)
                identity = int(identity_match.group(1)) if identity_match else 0
                
                # 提取 query 覆盖度
                align_pattern = r'<Hsp_query-from>(\d+)</Hsp_query-from>.*?<Hsp_query-to>(\d+)</Hsp_query-to>'
                align_match = re.search(align_pattern, hit, re.DOTALL)
                if align_match:
                    q_from = int(align_match.group(1))
                    q_to = int(align_match.group(2))
                    query_coverage = (q_to - q_from + 1)
                else:
                    query_coverage = 0
                
                # 提取描述
                desc = hit_def.split('|')[-1].strip() if '|' in hit_def else hit_def
                
                homologs.append({
                    'pdb_id': pdb_id,
                    'description': desc[:200],
                    'evalue': evalue,
                    'identity': identity,
                    'query_coverage': query_coverage,
                    'source': 'BLAST',
                    'is_homolog': True
                })
                
        except Exception as e:
            logger.error(f"Error parsing BLAST results: {e}")
        
        return homologs


# ==================== 评估引擎 ====================

class EvaluationEngine:
    """靶点结构可行性评估引擎"""
    
    def __init__(self):
        self.uniprot_client = UniProtClient()
        self.pdb_client = PDBClient()
        self.blast_client = BLASTClient()
    
    def evaluate(self, uniprot_id: str, force_blast: bool = False) -> Dict[str, Any]:
        """
        执行完整的靶点评估
        
        Args:
            uniprot_id: UniProt ID
            force_blast: 是否强制执行 BLAST（不管 PDB 数量）
        
        Returns:
            评估结果字典
        """
        logger.info(f"Starting evaluation for {uniprot_id}")
        
        result = {
            'uniprot_id': uniprot_id,
            'success': False,
            'error': None,
            'uniprot': None,
            'pdb_structures': [],
            'blast_results': [],
            'coverage': 0,
            'scores': {},
            'report': None,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        
        try:
            # Step 1: 获取 UniProt 数据
            logger.info(f"[1/5] Fetching UniProt data for {uniprot_id}...")
            uniprot_data = self.uniprot_client.get_data(uniprot_id)
            if not uniprot_data:
                result['error'] = f"Failed to fetch UniProt data for {uniprot_id}"
                return result
            
            result['uniprot'] = self._parse_uniprot(uniprot_data)
            
            # Step 2: 获取 PDB 结构
            logger.info(f"[2/5] Fetching PDB structures...")
            pdb_ids = result['uniprot'].get('pdb_ids', [])
            structures = []
            if pdb_ids:
                structures = self.pdb_client.get_structures(pdb_ids)
                # 添加源标记
                for s in structures:
                    s['source'] = 'Target'
                    s['is_homolog'] = False
            
            result['pdb_structures'] = structures
            logger.info(f"Found {len(structures)} target PDB structures")
            
            # Step 3: 计算覆盖度
            logger.info(f"[3/5] Calculating coverage...")
            coverage = self._calculate_coverage(result['uniprot'], structures)
            result['coverage'] = coverage
            logger.info(f"Coverage: {coverage}%")
            
            # Step 4: 判断是否需要 BLAST
            need_blast = force_blast or len(structures) < 5 or coverage < 50
            
            if need_blast:
                logger.info(f"[4/5] Low coverage/structures detected, running BLAST...")
                logger.info(f"  PDB count: {len(structures)} (threshold: 5)")
                logger.info(f"  Coverage: {coverage}% (threshold: 50%)")
                
                sequence = self.uniprot_client.get_sequence(uniprot_id)
                if sequence:
                    blast_result = self.blast_client.search(uniprot_id, sequence)
                    if blast_result.get('success'):
                        result['blast_results'] = blast_result.get('results', [])
                        logger.info(f"BLAST found {len(result['blast_results'])} homolog structures")
                    else:
                        logger.warning(f"BLAST failed: {blast_result.get('error')}")
                else:
                    logger.warning(f"Could not get sequence for BLAST")
            else:
                logger.info(f"[4/5] Skipping BLAST (sufficient structures: {len(structures)}, coverage: {coverage}%)")
            
            # Step 5: 计算评分
            logger.info(f"[5/5] Calculating scores...")
            result['scores'] = self._calculate_scores(structures, result['blast_results'], coverage)
            
            # 生成报告
            result['report'] = self._generate_report(result)
            result['success'] = True
            
            logger.info(f"Evaluation completed for {uniprot_id}")
            
        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            result['error'] = str(e)
        
        return result
    
    def _parse_uniprot(self, data: Dict) -> Dict:
        """解析 UniProt 数据"""
        entry_name = data.get('uniProtkbId', '')
        protein_name = ''
        pd_rec = data.get('proteinDescription', {})
        if pd_rec.get('recommendedName'):
            protein_name = pd_rec['recommendedName'].get('fullName', {}).get('value', '')
        
        gene_names = []
        for gene in data.get('genes', []):
            if gene.get('geneName'):
                gene_names.append(gene['geneName'].get('value', ''))
        
        organism = ''
        org_data = data.get('organism', {})
        if org_data:
            organism = org_data.get('scientificName', '')
        
        sequence_length = 0
        seq_info = data.get('sequence', {})
        if seq_info:
            sequence_length = seq_info.get('length', 0)
        
        pdb_ids = []
        for ref in data.get('uniProtKBCrossReferences', []):
            if ref.get('database') == 'PDB':
                pdb_ids.append(ref.get('id', ''))
        pdb_ids = list(set(pdb_ids))
        
        return {
            'uniprot_id': data.get('primaryAccession', ''),
            'entry_name': entry_name,
            'protein_name': protein_name,
            'gene_names': gene_names,
            'organism': organism,
            'sequence_length': sequence_length,
            'pdb_ids': pdb_ids,
        }
    
    def _calculate_coverage(self, uniprot_data: Dict, structures: List[Dict]) -> float:
        """计算结构覆盖度"""
        seq_length = uniprot_data.get('sequence_length', 0)
        if seq_length == 0 or not structures:
            return 0.0
        
        # 这里简化处理，实际应该计算每个结构覆盖的残基范围
        # 假设每个结构平均覆盖 200 个残基
        avg_coverage_per_structure = 200
        total_covered = len(structures) * avg_coverage_per_structure
        
        # 考虑重复覆盖，简单估算
        coverage = min(100, (total_covered / seq_length) * 100 * 2)
        
        return round(coverage, 1)
    
    def _calculate_scores(self, structures: List[Dict], blast_results: List[Dict], coverage: float) -> Dict:
        """计算可行性评分"""
        scores = {}
        
        # 基于结构数量和覆盖度
        if len(structures) >= 10 and coverage >= 80:
            base_score = 9
        elif len(structures) >= 5 and coverage >= 50:
            base_score = 7
        elif len(structures) >= 2 or coverage >= 30:
            base_score = 5
        else:
            base_score = 3
        
        # 如果有 BLAST 同源结构，加分
        if blast_results:
            homolog_score = min(2, len(blast_results) * 0.2)
            base_score = min(10, base_score + homolog_score)
        
        # Cryo-EM 评分（通常更高质量）
        cryo_em_count = sum(1 for s in structures if 'cryo' in s.get('method', '').lower())
        if cryo_em_count > 0:
            scores['Cryo-EM'] = {
                'score': min(10, base_score + 1),
                'assessment': '推荐' if base_score >= 7 else '可考虑'
            }
        
        # X-ray 评分
        xray_count = sum(1 for s in structures if 'x-ray' in s.get('method', '').lower() or 'xray' in s.get('method', '').lower())
        if xray_count > 0:
            scores['X-ray'] = {
                'score': base_score,
                'assessment': '可行' if base_score >= 5 else '困难'
            }
        
        # NMR 评分（通常较低）
        nmr_count = sum(1 for s in structures if 'nmr' in s.get('method', '').lower())
        if nmr_count > 0:
            scores['NMR'] = {
                'score': max(3, base_score - 2),
                'assessment': '困难'
            }
        
        # 如果没有目标结构但有 BLAST 同源结构
        if not structures and blast_results:
            scores['Homology'] = {
                'score': 6,
                'assessment': '可考虑同源建模',
                'homolog_count': len(blast_results)
            }
        
        return scores
    
    def _generate_report(self, result: Dict) -> str:
        """生成评估报告"""
        uniprot = result.get('uniprot', {})
        structures = result.get('pdb_structures', [])
        blast_results = result.get('blast_results', [])
        scores = result.get('scores', {})
        
        lines = []
        lines.append(f"# 蛋白质结构可行性评估报告")
        lines.append(f"**UniProt ID**: {uniprot.get('uniprot_id', '')} | **{uniprot.get('protein_name', '')}**")
        lines.append(f"**基因名**: {', '.join(uniprot.get('gene_names', []))} | **物种**: {uniprot.get('organism', '')}")
        lines.append(f"**序列长度**: {uniprot.get('sequence_length', 0)} aa")
        lines.append(f"**已有PDB结构**: {len(structures)} 个 | **覆盖度**: {result.get('coverage', 0)}%")
        lines.append("")
        
        # 评分
        lines.append("## 可行性评分")
        for method, score_info in scores.items():
            score = score_info.get('score', 0)
            assessment = score_info.get('assessment', '')
            stars = '★' * (score // 2) + '☆' * (5 - score // 2)
            lines.append(f"| {method} | {score}/10 {stars} | {assessment} |")
        lines.append("")
        
        # PDB 结构详情
        lines.append("## PDB 结构详情")
        if structures:
            lines.append("| PDB ID | 方法 | 分辨率 | 配体 | 来源 |")
            lines.append("|--------|------|--------|------|------|")
            for s in structures[:20]:
                method = s.get('method', 'Unknown')
                res = s.get('resolution')
                ligands = ', '.join(s.get('ligands', [])[:3])
                source = s.get('source', 'Target')
                res_str = f"{res} Å" if res else "N/A"
                lines.append(f"| {s.get('pdb_id', '')} | {method} | {res_str} | {ligands} | {source} |")
        else:
            lines.append("*暂无目标蛋白的PDB结构*")
        lines.append("")
        
        # BLAST 同源结构
        if blast_results:
            lines.append("## BLAST 同源结构")
            lines.append(f"通过序列比对找到 {len(blast_results)} 个同源结构，可用于同源建模指导：")
            lines.append("")
            lines.append("| PDB ID | 相似度 | E-value | 描述 |")
            lines.append("|--------|--------|---------|------|")
            for h in blast_results[:15]:
                identity = h.get('identity', 0)
                evalue = h.get('evalue', 0)
                desc = h.get('description', '')[:50]
                lines.append(f"| {h.get('pdb_id', '')} | {identity}% | {evalue:.1e} | {desc} |")
            lines.append("")
            lines.append(f"> 💡 可通过这 {len(blast_results)} 个同源结构进行同源建模，获得目标蛋白的结构模型。")
            lines.append("")
        
        # 建议
        lines.append("## 实验建议")
        if len(structures) >= 5 and result.get('coverage', 0) >= 50:
            lines.append("✅ **推荐进行基于结构的药物设计（SBDD）**")
            lines.append("- 结构数据充足，可直接用于分子对接、虚拟筛选")
            lines.append("- 建议优先使用高分辨率（<3Å）的结构")
        elif blast_results:
            lines.append("⚠️ **建议同源建模**")
            lines.append("- 目标蛋白结构数据不足，但找到了同源结构")
            lines.append("- 建议使用最高相似度的同源结构进行建模")
            lines.append("- 建模后可进行分子对接和虚拟筛选")
        else:
            lines.append("🔴 **挑战性较高**")
            lines.append("- 结构数据严重不足，且未找到合适的同源结构")
            lines.append("- 建议先表达纯化蛋白获取晶体结构")
            lines.append("- 或使用 AlphaFold 等工具进行结构预测")
        
        return '\n'.join(lines)


# ==================== 主函数 ====================

def main():
    """命令行入口"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python evaluation_engine.py <uniprot_id>")
        print("Example: python evaluation_engine.py Q91UL0")
        sys.exit(1)
    
    uniprot_id = sys.argv[1]
    force_blast = '--force-blast' in sys.argv
    
    engine = EvaluationEngine()
    result = engine.evaluate(uniprot_id, force_blast=force_blast)
    
    # 输出 JSON 结果
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
