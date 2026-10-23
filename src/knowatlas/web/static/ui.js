/* 通用浮层套件（第七十五批）：toast 轻提示 + 模态框（alert/confirm/prompt）。
 * index/graph/thread 三页共用，替代浏览器原生 prompt/alert/confirm——
 * WebView2 壳下原生弹窗是 Chromium 浅色样式，与深色设计系统断裂（批次 75 决策：
 * 原生消息框不接业务路径，改令牌化模态框 + toast，端点与交互语义不变）。
 *
 * 语义对齐原生，便于逐点替换：
 *   ka.toast(msg, type)            轻提示，自动消失（type: success/error/warn/info）
 *   ka.alert(msg, title)           模态告知，Promise<void>
 *   ka.confirm(msg, title)         模态确认，Promise<boolean>（true=确认；Esc/取消=false）
 *   ka.prompt(msg, def, title)     模态输入，Promise<string|null>（null=取消；""=确认空值）
 */
(function () {
  "use strict";
  if (window.ka) return;  // 防重复注入

  // ---- toast ----
  var TOAST_ICON = { success: "✓", error: "✕", warn: "!", info: "i" };
  var TOAST_DUR = { success: 3200, error: 6000, warn: 5000, info: 4000 };
  var toastWrap = null;

  function toast(msg, type) {
    type = type || "info";
    if (!toastWrap) {
      toastWrap = document.createElement("div");
      toastWrap.id = "ka-toast-wrap";
      document.body.appendChild(toastWrap);
    }
    var el = document.createElement("div");
    el.className = "ka-toast ka-toast--" + type;
    el.setAttribute("role", "status");
    var ic = document.createElement("span");
    ic.className = "ka-toast-ic";
    ic.textContent = TOAST_ICON[type] || "i";
    var tx = document.createElement("span");
    tx.className = "ka-toast-tx";
    tx.textContent = msg == null ? "" : String(msg);
    el.appendChild(ic);
    el.appendChild(tx);
    var done = false;
    function remove() {
      if (done) return;
      done = true;
      el.classList.add("out");
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 180);
    }
    el.onclick = remove;
    toastWrap.appendChild(el);
    while (toastWrap.children.length > 5) toastWrap.removeChild(toastWrap.firstChild);
    setTimeout(remove, TOAST_DUR[type] || 4000);
  }

  // ---- 模态框（复用单个 <dialog>；head 期注入时等 DOMContentLoaded）----
  var dlg = null, pending = null;

  function buildDialog() {
    if (dlg) return;
    dlg = document.getElementById("ka-dialog");
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.id = "ka-dialog";
      dlg.innerHTML =
        '<div class="ka-title" id="ka-title"></div>' +
        '<div class="ka-msg" id="ka-msg"></div>' +
        '<input class="ka-input" id="ka-input" autocomplete="off">' +
        '<div class="ka-btns">' +
        '<button type="button" id="ka-cancel">取消</button>' +
        '<button type="button" id="ka-ok">确定</button>' +
        '</div>';
      document.body.appendChild(dlg);
    }
    dlg.addEventListener("close", function () {
      // Esc / 程序性关闭 = 取消（与原生 prompt/confirm 的取消语义一致）
      if (pending) finish(pending.mode === "prompt" ? null : false);
    });
    dlg.querySelector("#ka-ok").onclick = function () {
      finish(pending && pending.mode === "prompt" ? dlg.querySelector("#ka-input").value : true);
    };
    dlg.querySelector("#ka-cancel").onclick = function () { finish(false); };
    dlg.querySelector("#ka-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); dlg.querySelector("#ka-ok").click(); }
      e.stopPropagation();  // 防全局快捷键（如 Ctrl+K）在输入时误触
    });
  }

  function openDialog(opts) {
    return new Promise(function (resolve) {
      buildDialog();
      if (pending) finish(pending.mode === "prompt" ? null : false);  // 串行保护
      pending = { resolve: resolve, mode: opts.mode };
      var isPrompt = opts.mode === "prompt";
      var elTitle = dlg.querySelector("#ka-title");
      elTitle.textContent = opts.title || "";
      elTitle.hidden = !opts.title;
      dlg.querySelector("#ka-msg").textContent = opts.msg == null ? "" : String(opts.msg);
      var input = dlg.querySelector("#ka-input");
      input.hidden = !isPrompt;
      if (isPrompt) { input.value = opts.def == null ? "" : String(opts.def); }
      var cancel = dlg.querySelector("#ka-cancel");
      cancel.hidden = opts.mode === "alert";
      dlg.querySelector("#ka-ok").textContent = opts.okText || (opts.mode === "alert" ? "知道了" : "确定");
      dlg.showModal();
      if (isPrompt) { input.focus(); input.select(); }
      else dlg.querySelector("#ka-ok").focus();
    });
  }

  function finish(val) {
    if (!pending) return;
    var p = pending;
    pending = null;
    if (dlg.open) dlg.close();
    p.resolve(val);
  }

  window.ka = {
    toast: toast,
    alert: function (msg, title) { return openDialog({ mode: "alert", msg: msg, title: title }); },
    confirm: function (msg, title) { return openDialog({ mode: "confirm", msg: msg, title: title }); },
    prompt: function (msg, def, title) { return openDialog({ mode: "prompt", msg: msg, def: def, title: title }); }
  };
})();
