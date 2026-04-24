# PDB Tracker 文件说明

## 核心文件（必需）

### 1. pdb_web_ui.py (157KB)
**主Web应用程序**
- Flask Web服务器
- RESTful API端点
- 前端页面路由
- SQLite数据库操作
- BLAST结果解析和富化
- 评估报告生成

**依赖**: flask, requests, python-dotenv
**启动方式**: `python pdb_web_ui.py`

---

### 2. evaluation_engine.py (26KB)
**蛋白质结构评估引擎**
- 蛋白质序列分析
- 结构可行性评分算法
- 支持X-ray/Cryo-EM/NMR三种方法
- 序列覆盖率计算
- 评估报告生成

**用途**: 核心评估逻辑，计算蛋白结构解析可行性

---

### 3. pdb_tracker_db.py (24KB)
**数据库操作模块**
- SQLite数据库初始化
- 表结构定义
- CRUD操作封装
- 数据结构定义

**数据库表**:
- `pdb_structures` - PDB结构基本信息
- `target_structures` - 目标结构追踪
- `target_tracking` - 追踪状态
- `pubmed_abstracts` - PubMed摘要缓存
- `pdb_chains` - PDB链信息

---

## 工具脚本（可选）

### 4. blast_batch.py (3.5KB)
**BLAST批量搜索工具**
- 批量处理UniProt ID列表
- 调用NCBI BLAST API
- 结果解析和保存

**用途**: 批量获取蛋白同源结构
**使用场景**: 需要批量搜索多个蛋白时

---

### 5. fetch_journal_if.py (16KB)
**期刊影响因子获取工具**
- 从Journal Citation Reports获取IF
- 期刊名称匹配和标准化
- 影响因子缓存
- CSV/JSON格式输出

**用途**: 获取期刊影响因子数据
**使用场景**: 更新期刊IF数据库时

---

### 6. fetch_ligands.py (4KB)
**配体信息获取工具**
- 从RCSB PDB获取配体信息
- 配体名称解析
- 缓存配体图片

**用途**: 获取PDB结构中的配体信息
**使用场景**: 分析蛋白-配体复合物时

---

### 7. fetch_missing_res.py (3.8KB)
**缺失残基信息获取工具**
- 检测PDB结构中的缺失残基
- 序列覆盖率分析
- 完整性评估

**用途**: 评估PDB结构的完整性
**使用场景**: 结构质量评估时

---

### 8. pdb_api_server.py (10KB)
**PDB API代理服务器**
- RCSB PDB REST API封装
- 数据缓存和代理
- 批量查询接口

**用途**: 提供统一的PDB数据访问接口
**状态**: 早期版本，部分功能已合并到pdb_web_ui.py

---

### 9. sync_journal_if.py (8.6KB)
**期刊影响因子同步工具**
- 与本地数据库同步
- 增量更新
- 数据清洗

**用途**: 同步期刊IF到本地数据库
**使用场景**: 定期更新期刊数据时

---

### 10. cache_ligand_images.py (4.4KB)
**配体图片缓存工具**
- 下载配体2D结构图
- 本地缓存管理
- RCSB配体数据库接口

**用途**: 缓存配体图片加速显示
**使用场景**: 需要离线查看配体结构时

---

## 前端文件

### 11. web_scripts/pdb_app.js (54KB)
**前端JavaScript应用**
- 数据表格渲染
- 搜索和过滤
- PDB结构预览
- BLAST结果展示
- 分子查看器集成

**注意**: 此文件由pdb_web_ui.py动态生成，修改会被覆盖

---

### 12. web_scripts/pdb_index.html (34KB)
**前端HTML模板**
- Web UI页面结构
- CSS样式定义
- 组件布局
- 模态框和工具提示

---

## 文件分类总结

| 类别 | 文件 | 重要性 |
|------|------|--------|
| **核心** | pdb_web_ui.py | ⭐⭐⭐ 必需 |
| **核心** | evaluation_engine.py | ⭐⭐⭐ 必需 |
| **核心** | pdb_tracker_db.py | ⭐⭐⭐ 必需 |
| **前端** | web_scripts/pdb_app.js | ⭐⭐⭐ 必需 |
| **前端** | web_scripts/pdb_index.html | ⭐⭐⭐ 必需 |
| 工具 | blast_batch.py | ⭐⭐ 推荐保留 |
| 工具 | fetch_journal_if.py | ⭐⭐ 推荐保留 |
| 工具 | fetch_ligands.py | ⭐ 可选 |
| 工具 | fetch_missing_res.py | ⭐ 可选 |
| 工具 | sync_journal_if.py | ⭐ 可选 |
| 工具 | pdb_api_server.py | ⭐ 可选/废弃 |
| 工具 | cache_ligand_images.py | ⭐ 可选 |

---

## 最小化建议

### 如果只需要Web功能:
保留: pdb_web_ui.py, evaluation_engine.py, pdb_tracker_db.py + web_scripts/

### 如果需要完整功能:
保留: 所有核心文件 + blast_batch.py + fetch_journal_if.py + fetch_ligands.py

### 可以删除的文件:
- cache_ligand_images.py (配体图片可在线获取)
- pdb_api_server.py (功能已合并到主程序)
- sync_journal_if.py (如果不需要定期同步)
