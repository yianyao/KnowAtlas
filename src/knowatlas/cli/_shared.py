"""CLI 子命令注册与参数解析（完整方案 §7；argparse，不引 click）。"""



import os
from ..datalayer.db import DataLayer


_EXIT_OK, EXIT_BUSINESS, _EXIT_USAGE, _EXIT_SKIP = 0, 1, 2, 3  # SKIP 计退出码，不伪装通过


def _open(cfg) -> DataLayer:
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    return dl


def _apply_serve_overrides(cfg, host: str, port: int) -> None:
    """把 serve 实际监听的 host/port 回写进 cfg（R8，2026-10-24 对账修复）。

    为什么必须回写：安全中间件的 Host 白名单是按 ``cfg.general.server_port`` 生成的
    （web/api.py::install_security_middleware），而 ``serve --port 9000`` 只改 uvicorn
    的监听端口、不动 cfg —— 浏览器访问 http://127.0.0.1:9000 会带 Host: 127.0.0.1:9000，
    不在白名单内，直接被 FORBIDDEN_HOST 拒掉（表现为"换了端口就打不开"）。
    桌面壳 desktop/main.py 早就是同口径（create_app 之前覆盖 cfg 值），CLI 这条补齐。
    """
    general = cfg.raw.setdefault("general", {})
    general["server_host"] = host
    general["server_port"] = int(port)


def _warn_if_llm_unavailable(cfg, command: str) -> None:
    """R10：LLM 声明启用却读不到任何 key —— 语义层会静默降级，必须显式告知。

    真实踩坑（2026-10-24 样本验证）：key 配在用户级环境变量，进程早于 `setx` 启动
    读不到，`kpoints` 安安静静产出「整篇 4023 字 integral」点、split 文档归零，
    用户与 agent 都看不出"其实没连上 LLM"。降级本身可以接受，**沉默**不行。
    """
    if not bool(cfg.get("llm.enabled", False)):
        return
    names: list[str] = []
    for backend in cfg.get("llm.backends", []) or []:
        if isinstance(backend, dict):
            names.extend(str(backend.get("api_key_env", "")).split(","))
    ordered = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    if not ordered:
        ordered = ["KNOWATLAS_LLM_API_KEY"]
    if any(os.environ.get(name) for name in ordered):
        return
    print(f"WARN 语义层降级：{command} 需要 LLM，但 [llm] enabled=true 且这些环境变量全为空"
          f"（{'/'.join(ordered)}）——分类停在规则级、点抽取退化为「整篇照抄 integral」、"
          "split 文档归零。配好 key 后重跑即可。")
