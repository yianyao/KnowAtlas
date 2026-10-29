"""局域网访问（TODO P2 · P1）：Host/Origin 白名单按绑定地址派生 + 写权限按来源收紧。

背景：`web/api.py` 原来把白名单写死成 `127.0.0.1:port` / `localhost:port`，
所以 `serve --host 0.0.0.0` 之后手机带 `Host: 192.168.x.x:8420` 会被
`FORBIDDEN_HOST` 403（用户侧表现是「手机打不开」）。

口径：
- loopback 恒放行；
- 只有当 `general.server_host` 不是 loopback 时，才追加**本机网卡地址**
  （枚举本机地址而不是放整个内网段——Host 校验挡的是 DNS rebinding，
  攻击者只能带自己的域名来打，没必要把 192.168.0.0/16 全放进来）；
- Origin 白名单与 Host 同源推导（仅 http）。

写权限（工单 `变更工单-2026-10-29-局域网写权限收紧.md`，2026-10-29）：
`/api/session` 只给**本机来源**种写 Cookie；局域网来源默认不种（`write_allowed=false`），
写操作回 403 `FORBIDDEN_READONLY`。`[web] allow_lan_writes=true` 恢复旧行为；
带正确 `X-KnowAtlas-Token` 的写操作在任何来源都仍可通过。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowatlas.web.api import allowed_hosts, allowed_origins, lan_urls, local_addresses
from knowatlas.web.app import create_app

STATIC = Path(__file__).resolve().parents[1] / "src" / "knowatlas" / "web" / "static"

LAN_IP = "192.168.77.31"   # 假地址：绝不能出现在真实枚举结果里
PORT = 8420
TOKEN = "lan-test-token"


def _client(cfg, dl, registries, *, client_addr=None, base_url=None) -> TestClient:
    """`client_addr` = 连接对端地址（ASGI 的 request.client）——写权限按它判来源。"""
    os.environ.setdefault(str(cfg.get("web.token_env", "KNOWATLAS_WEB_TOKEN")), TOKEN)
    kwargs = {"headers": {"Host": f"127.0.0.1:{PORT}"}}
    if client_addr:
        kwargs["client"] = client_addr
    if base_url:
        kwargs["base_url"] = base_url
    return TestClient(create_app(cfg, dl, *registries), **kwargs)


def _lan_host(cfg) -> str:
    """绑定 0.0.0.0 后取一个真实本机地址当 Host（手机就是这么访问的）。"""
    cfg.raw.setdefault("general", {})["server_host"] = "0.0.0.0"
    addr = next((a for a in local_addresses() if a != "127.0.0.1"), None)
    if not addr:
        pytest.skip("本机没有非 loopback 网卡（离线环境）")
    return f"{addr}:{PORT}"


def _enable_lan_writes(cfg, on=True) -> None:
    cfg.raw.setdefault("web", {})["allow_lan_writes"] = on


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


# ------------------------------------------------- 写权限按来源收紧（2026-10-29 工单）


def test_session_sets_write_cookie_for_loopback_client(cfg, dl, registries) -> None:
    """本机（桌面壳 / 本机浏览器）：`/api/session` 照旧种 HttpOnly 写 Cookie，行为不变。"""
    c = _client(cfg, dl, registries, client_addr=("127.0.0.1", 51000))
    r = c.get("/api/session")
    assert r.status_code == 200
    assert r.json()["write_allowed"] is True
    assert "knowatlas_write=" in r.headers.get("set-cookie", "")
    # cookie 通道生效：不带令牌头也能过守卫（404 = 过了守卫，只是条目不存在）
    assert c.post("/api/entries/999999/reject", json={}).status_code == 404


def test_session_withholds_write_cookie_from_lan_client(cfg, dl, registries) -> None:
    """局域网来源默认不种写 Cookie（这就是本单修的洞：页面一开就能写）。"""
    host = _lan_host(cfg)
    c = _client(cfg, dl, registries, client_addr=(LAN_IP, 51001))
    r = c.get("/api/session", headers={"Host": host})
    assert r.status_code == 200, r.text
    assert r.json()["write_allowed"] is False
    assert "knowatlas_write=" not in r.headers.get("set-cookie", "")


def test_lan_write_without_credentials_is_readonly(cfg, dl, registries) -> None:
    """LAN 上无凭据写：403 `FORBIDDEN_READONLY`（不是「令牌填错」，文案给三条出路）。"""
    host = _lan_host(cfg)
    c = _client(cfg, dl, registries, client_addr=(LAN_IP, 51002))
    w = c.post("/api/entries/999999/reject", json={}, headers={"Host": host})
    assert w.status_code == 403, w.text
    err = w.json()["error"]
    assert err["code"] == "FORBIDDEN_READONLY"
    assert "局域网只读" in err["message"]
    assert "allow_lan_writes" in err["message"]


def test_lan_write_allowed_when_config_enables(cfg, dl, registries) -> None:
    """`[web] allow_lan_writes = true`：回落今日行为（种 Cookie、写通过守卫）。"""
    host = _lan_host(cfg)
    _enable_lan_writes(cfg, True)
    c = _client(cfg, dl, registries, client_addr=(LAN_IP, 51003))
    r = c.get("/api/session", headers={"Host": host})
    assert r.json()["write_allowed"] is True
    assert "knowatlas_write=" in r.headers.get("set-cookie", "")
    assert c.post("/api/entries/999999/reject", json={},
                  headers={"Host": host}).status_code == 404


def test_lan_write_with_explicit_token_still_passes(cfg, dl, registries) -> None:
    """令牌通道不因只读模式关闭：带对 `X-KnowAtlas-Token` 的写照样过守卫（脚本/bookmarklet）。"""
    host = _lan_host(cfg)
    c = _client(cfg, dl, registries, client_addr=(LAN_IP, 51004))
    w = c.post("/api/entries/999999/reject", json={},
               headers={"Host": host, "X-KnowAtlas-Token": TOKEN})
    assert w.status_code == 404, w.text
    bad = c.post("/api/entries/999999/reject", json={},
                 headers={"Host": host, "X-KnowAtlas-Token": "wrong-token"})
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "FORBIDDEN"      # 真填错了仍是原错误码


def test_allow_lan_writes_parses_strings_fail_closed(cfg, dl, registries) -> None:
    """环境变量覆盖会把布尔写成字符串（`config.py::_apply_env_overrides`）：
    `"false"` 必须仍算关——`bool("false")` 是 True，会把只读误开成可写（安全开关 fail-closed）。"""
    host = _lan_host(cfg)
    for raw in ("false", "0", "no", "off", "", "  ", "FALSE", "随便写"):
        _enable_lan_writes(cfg, raw)
        c = _client(cfg, dl, registries, client_addr=(LAN_IP, 51005))
        assert c.get("/api/session", headers={"Host": host}).json()["write_allowed"] is False, raw
    for raw in (True, "true", "1", "yes", "on", " TRUE "):
        _enable_lan_writes(cfg, raw)
        c = _client(cfg, dl, registries, client_addr=(LAN_IP, 51006))
        assert c.get("/api/session", headers={"Host": host}).json()["write_allowed"] is True, raw
# --------------------------------------------------- 前端静态探针（防回归）


def test_ui_prompt_cancel_resolves_null() -> None:
    """`ka.prompt` 取消必须 resolve **null**（ui.js 自己的约定：null=取消）。
    原先不分 mode 一律 `finish(false)`，调用方 `.trim()` 直接 TypeError——
    2026-10-29 局域网只读令牌弹窗实测暴露（headless Edge：`t.trim is not a function`）。"""
    flat = " ".join((STATIC / "ui.js").read_text(encoding="utf-8").split())
    assert ('dlg.querySelector("#ka-cancel").onclick = function () { '
            'finish(pending && pending.mode === "prompt" ? null : false); };') in flat
    assert "finish(false); };" not in flat, "cancel 又变回不分 mode 了"


def test_index_wires_readonly_badge_and_token_prompt() -> None:
    """只读徽标与「先要令牌再发请求」的短路必须留在页面上（否则 LAN 用户只看到裸 403）。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="readonly-badge"' in html
    assert "sessionInfo.write_allowed === false" in html
    assert 'typeof t !== "string"' in html, "取消/异常必须中止，不能拿非字符串去 trim"
    assert 'id="readonly-badge"' in (STATIC / "thread.html").read_text(encoding="utf-8")
