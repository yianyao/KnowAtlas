"""局域网访问（TODO P2 · P1）：Host/Origin 白名单按绑定地址派生。

背景：`web/api.py` 原来把白名单写死成 `127.0.0.1:port` / `localhost:port`，
所以 `serve --host 0.0.0.0` 之后手机带 `Host: 192.168.x.x:8420` 会被
`FORBIDDEN_HOST` 403（用户侧表现是「手机打不开」）。

口径（2026-10-29 用户裁决：**只做白名单，不动 /api/session 的写模式**）：
- loopback 恒放行；
- 只有当 `general.server_host` 不是 loopback 时，才追加**本机网卡地址**
  （枚举本机地址而不是放整个内网段——Host 校验挡的是 DNS rebinding，
  攻击者只能带自己的域名来打，没必要把 192.168.0.0/16 全放进来）；
- Origin 白名单与 Host 同源推导（仅 http）。

⚠️ 已知取舍（用户明示接受）：`/api/session` 仍对任何来访者种写 Cookie，
所以挂 `0.0.0.0` 时同网段设备**能写**。要收紧再做 `web.allow_lan_writes`。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from knowatlas.web.api import allowed_hosts, allowed_origins, lan_urls, local_addresses
from knowatlas.web.app import create_app

LAN_IP = "192.168.77.31"   # 假地址：绝不能出现在真实枚举结果里
PORT = 8420


def _client(cfg, dl, registries):
    os.environ.setdefault(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), "lan-test-token")
    return TestClient(create_app(cfg, dl, *registries))


# ------------------------------------------------------------------ 纯函数


def test_local_addresses_always_include_loopback() -> None:
    addrs = local_addresses()
    assert "127.0.0.1" in addrs
    assert LAN_IP not in addrs, "枚举只能来自本机网卡，不能凭空出现别的地址"


def test_loopback_bind_keeps_minimal_whitelist(cfg) -> None:
    """默认 `server_host=127.0.0.1`：白名单就是两条 loopback，不加任何网卡地址。"""
    cfg.raw.setdefault("general", {})["server_host"] = "127.0.0.1"
    hosts = allowed_hosts(cfg)
    assert hosts == {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    assert allowed_origins(cfg) == {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}


def test_lan_bind_adds_every_local_address(cfg) -> None:
    cfg.raw.setdefault("general", {})["server_host"] = "0.0.0.0"
    hosts = allowed_hosts(cfg)
    assert {f"127.0.0.1:{PORT}", f"localhost:{PORT}"} <= hosts
    for addr in local_addresses():
        assert f"{addr}:{PORT}" in hosts, f"绑定 0.0.0.0 后本机地址 {addr} 必须放行"
    # Origin 与 Host 同源（只 http）
    assert f"http://127.0.0.1:{PORT}" in allowed_origins(cfg)


def test_lan_urls_skip_loopback_and_keep_port(cfg) -> None:
    urls = lan_urls(PORT)
    assert all(u.startswith("http://") and u.endswith(f":{PORT}") for u in urls)
    assert not any("127.0.0.1" in u or "localhost" in u for u in urls)


# ------------------------------------------------------------------ 中间件行为


def test_loopback_bind_rejects_lan_host(cfg, dl, registries) -> None:
    """没绑局域网时，带内网 IP Host 的请求仍被拒（默认姿态不放松）。"""
    cfg.raw.setdefault("general", {})["server_host"] = "127.0.0.1"
    c = _client(cfg, dl, registries)
    r = c.get("/api/tree", headers={"Host": f"{LAN_IP}:{PORT}"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_HOST"


def test_lan_bind_accepts_lan_host(cfg, dl, registries) -> None:
    """绑 0.0.0.0 后，手机带的 `Host: <内网IP>:8420` 放行（这正是「手机打不开」的修复点）。"""
    cfg.raw.setdefault("general", {})["server_host"] = "0.0.0.0"
    lan_addr = next((a for a in local_addresses() if a != "127.0.0.1"), None)
    if not lan_addr:
        pytest.skip("本机没有非 loopback 网卡（离线环境）")
    c = _client(cfg, dl, registries)
    ok = c.get("/api/tree", headers={"Host": f"{lan_addr}:{PORT}"})
    assert ok.status_code == 200, ok.text
    # 陌生 Host 仍然被拒 —— 白名单不是关掉校验
    bad = c.get("/api/tree", headers={"Host": f"evil.example.com:{PORT}"})
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "FORBIDDEN_HOST"


def test_foreign_origin_still_rejected_on_lan(cfg, dl, registries) -> None:
    """CSRF 侧不放宽：Host 合法但 Origin 是外站 → 403。"""
    cfg.raw.setdefault("general", {})["server_host"] = "0.0.0.0"
    lan_addr = next((a for a in local_addresses() if a != "127.0.0.1"), None)
    if not lan_addr:
        pytest.skip("本机没有非 loopback 网卡（离线环境）")
    c = _client(cfg, dl, registries)
    bad = c.get("/api/tree", headers={"Host": f"{lan_addr}:{PORT}",
                                      "Origin": "https://evil.example.com"})
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "FORBIDDEN_ORIGIN"
    good = c.get("/api/tree", headers={"Host": f"{lan_addr}:{PORT}",
                                       "Origin": f"http://{lan_addr}:{PORT}"})
    assert good.status_code == 200, good.text