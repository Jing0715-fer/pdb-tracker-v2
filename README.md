# PDB Tracker

蛋白质结构追踪与评估系统 - 用于监控PDB数据库更新并评估蛋白质结构可行性。

## 功能特性

- **PDB数据库监控**: 自动跟踪RCSB PDB数据库的最新结构发布
- **蛋白质结构评估**: 基于序列分析评估蛋白质结构解析可行性
- **BLAST同源搜索**: 自动搜索同源蛋白结构
- **Web可视化界面**: 基于Flask的现代化Web UI
- **期刊影响因子**: 集成期刊IF数据评估结构质量
- **配体分析**: 识别和展示结构中的配体信息

## 项目结构

```
.
├── pdb_web_ui.py          # Flask Web应用程序主文件
├── web_scripts/           # Web前端资源
│   └── pdb_app.js         # 前端JavaScript
├── migrate_blast_data.py  # BLAST数据迁移工具
├── pdb_index.html         # 前端HTML模板
└── pdb_tracker.db         # SQLite数据库
```

## 环境变量配置

```bash
# 数据目录配置
export PDB_DATA_DIR="/path/to/data"           # 数据根目录 (默认 ~/.pdb-tracker/)
export PDB_DB_DIR="/path/to/db"               # 数据库目录
export PDB_DB_NAME="pdb_tracker.db"           # 数据库文件名
export PDB_WEEKLY_DIR="/path/to/reports"      # 周报目录
export PDB_WEB_SCRIPT_DIR="/path/to/scripts"  # Web脚本目录
export PDB_WEB_PORT=5555                       # Web服务端口
```

## 安装依赖

```bash
pip install flask requests python-dotenv
```

## 启动服务

```bash
python pdb_web_ui.py
```

服务启动后访问: http://localhost:5555

## 核心功能模块

### 1. PDB数据获取
- 支持从RCSB REST API获取结构详情
- 自动提取方法、分辨率、发表日期、期刊信息
- 并发请求优化性能

### 2. BLAST同源搜索
- 自动搜索同源蛋白结构
- 计算序列相似度(Identity)和覆盖率
- 从PDB数据库获取实际标题(非BLAST描述)

### 3. 结构评估报告
- 生成Markdown格式的评估报告
- 包含可行性评分(X-ray/Cryo-EM/NMR)
- 同源结构详细分析

### 4. 数据存储
- SQLite数据库存储所有数据
- 支持评估结果持久化
- 期刊影响因子缓存

## 数据库表结构

### evaluations
存储蛋白质评估基本信息

### evaluation_pdb_structures
存储PDB结构详细信息

### evaluation_blast_results
存储BLAST同源搜索结果

### evaluation_reports
存储评估报告(Markdown格式)

## API端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/evaluations` | GET | 列出所有评估 |
| `/api/evaluations/<id>` | GET | 获取单个评估详情 |
| `/api/evaluations` | POST | 保存评估结果 |
| `/api/evaluation/reports/list` | GET | 列出评估报告 |
| `/api/snapshots` | GET | 获取周快照数据 |
| `/api/entries` | GET | 获取PDB条目列表 |

## 技术栈

- **后端**: Python + Flask
- **前端**: Vanilla JavaScript (ES6)
- **数据库**: SQLite3
- **API**: RCSB PDB REST API v1/v2
- **外部服务**: NCBI BLAST

## 开发者

- 作者: lijing
- 创建日期: 2024
