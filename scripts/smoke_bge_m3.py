"""bge-m3 本机真机冒烟探针（Phase 7 批次 73 探针 A，方案 §9）。

验证「本机 embedding 模型」外部条件：下载/加载/向量维度/L2 归一化/
入库/embed/混合检索/知识集分组全链路。全程临时目录 + 环境变量启用
（KNOWATLAS_EMBEDDING_ENABLED），**不碰 config 真实配置**（硬闸门）。

用法（仓库根）：
    .venv\\Scripts\\python.exe scripts\\smoke_bge_m3.py

前置（2026-10-22 本机实际环境，探针实录）：
1. optional 依赖：uv pip install sentence-transformers -p .venv\\Scripts\\python.exe
   （torch 2.14.1+cpu；本机缺新版 MSVC 运行库 vcruntime140_threads.dll——
   torch 装完若报 WinError 1114/126，需补齐 vcruntime140/140_1/threads +
   msvcp140 系列到 .venv\\Lib\\site-packages\\torch\\lib\\，不动系统目录）。
2. 模型下载（~2.2GB，hf-mirror）：
   $env:HF_ENDPOINT='https://hf-mirror.com'
   python -c "from huggingface_hub import hf_hub_download,snapshot_download; \
     snapshot_download('BAAI/bge-m3', allow_patterns=['*.json','sentencepiece.bpe.model','1_Pooling/*']); \
     hf_hub_download('BAAI/bge-m3','pytorch_model.bin')"
   注意：bge-m3 仓库无 model.safetensors，权重是 pytorch_model.bin——
   allow_patterns 只写 model.safetensors 会静默零下载（本批踩坑实录）。
3. 首次下载后建议离线跑（Hub 直连不稳时 HEAD 检查会拖慢甚至拖死加载）：
   $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'
"""
import math
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.pop("KNOWATLAS_HOME", None)  # 测试自管路径，不受宿主污染（conftest 同款）
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from knowatlas.config import Config, load_config
from knowatlas.datalayer.db import DataLayer
from knowatlas.models import Entry
from knowatlas.pipeline.embed_index import embed_entries, group_hits, hybrid_search
from knowatlas.semantic.embed import LocalEmbedder, from_config

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ka_bge_smoke_"))
    (tmp / "data").mkdir()
    toml = tmp / "knowatlas.toml"
    toml.write_text(
        "[general]\ndb_path = 'data/knowledge.db'\nlog_level = 'WARNING'\n"
        "[embedding]\nenabled = false\nmodel_path = ''\n",
        encoding="utf-8",
    )

    # 1) 环境变量启用链路：toml 里 embedding.enabled=false + KNOWATLAS_EMBEDDING_ENABLED 覆盖
    os.environ["KNOWATLAS_EMBEDDING_ENABLED"] = "true"
    cfg = load_config(toml)
    check("env override embedding.enabled", cfg.get("embedding.enabled") in (True, "true"))
    emb = from_config(cfg)
    check("from_config -> LocalEmbedder", isinstance(emb, LocalEmbedder), type(emb).__name__)

    # 2) 编码：维度 1024 / L2 归一化 / 语义区分度
    t0 = time.time()
    vecs = emb.encode(["如何用 Python 读写 CSV 文件", "pandas 处理表格数据", "红烧肉的家常做法"])
    dt = time.time() - t0
    check("dim == 1024", all(len(v) == 1024 for v in vecs), f"load+encode {dt:.1f}s")
    norms = [math.sqrt(sum(x * x for x in v)) for v in vecs]
    check("L2 norm ~ 1", all(abs(n - 1.0) < 0.02 for n in norms), [round(n, 3) for n in norms])

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    s_same, s_diff = dot(vecs[0], vecs[1]), dot(vecs[0], vecs[2])
    check("semantic sanity", s_same > s_diff, f"csv~pandas={s_same:.3f} > csv~红烧肉={s_diff:.3f}")

    # 3) 入库 → 向量化 → 混合检索 → 知识集分组 全链路（临时库）
    os.environ.pop("KNOWATLAS_EMBEDDING_ENABLED", None)
    cfg2 = Config({"general": {"db_path": str(tmp / "data" / "knowledge.db"), "log_level": "WARNING"}}, toml)
    dl = DataLayer(cfg2.db_path)
    dl.init_schema()
    es = [
        Entry.build(source_type="manual", source_key=f"smoke:{i}", title=t,
                    locator=f"https://smoke.local/{i}", locator_canonical=None,
                    inline_content=c, native_path=None, meta={"source_type": "manual"})
        for i, (t, c) in enumerate([
            ("Python CSV 读写", "使用 csv 模块或 pandas 读取和写出 CSV 表格文件的方法。"),
            ("pandas 表格处理", "pandas DataFrame 数据清洗、筛选、透视表操作笔记。"),
            ("红烧肉做法", "五花肉焯水后炒糖色，小火炖四十分钟的家用菜谱。"),
        ], 1)
    ]
    dl.upsert_entries(es)
    res = embed_entries(dl, emb)
    check("embed_entries 3 ok", res.get("embedded") == 3 and res.get("no_text") == 0, res)
    r = hybrid_search(dl, emb, "python 处理 csv 表格", limit=5)
    check("hybrid_search hits", r is not None and len(r.get("hits", [])) > 0,
          None if r is None else {"mode": r.get("mode"), "vectors": r.get("vectors")})
    if r and r.get("hits"):
        hits = r["hits"]
        check("top hit relevant",
              any(("CSV" in h["title"] or "pandas" in h["title"]) for h in hits[:2]),
              hits[0]["title"])
        check("sim reason present",
              any(str(x).startswith("sim:") for h in hits for x in h.get("reasons", [])),
              hits[0].get("reasons"))
        g = group_hits(dl, [h["entry_id"] for h in hits])
        check("grouping semantic", isinstance(g, dict) and g.get("mode") == "semantic",
              {"mode": g.get("mode"), "groups": len(g.get("groups", [])),
               "singles": len(g.get("singles", []))})

    ok = all(results)
    print(f"\n== SMOKE {'PASS' if ok else 'FAIL'} ({sum(results)}/{len(results)}) ==", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
