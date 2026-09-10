(function () {
    'use strict';

    var RM = window.ReqMan = window.ReqMan || {};

    function byId(id) { return document.getElementById(id); }
    function onReady(fn) {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
        else fn();
    }

    window.showLoader = function () {
        var el = byId('globalLoader');
        if (el) el.classList.add('active');
    };
    window.hideLoader = function () {
        var el = byId('globalLoader');
        if (el) el.classList.remove('active');
    };
    window.showToast = function (message, type, duration) {
        var container = byId('toastContainer');
        if (!container) { window.alert(message); return; }
        type = type || 'info';
        var toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
        var icons = { success: 'OK', error: '!', warning: '!', info: 'i' };
        var icon = document.createElement('span');
        icon.className = 'toast-mark';
        icon.textContent = icons[type] || icons.info;
        var text = document.createElement('span');
        text.textContent = message == null ? '' : String(message);
        toast.appendChild(icon);
        toast.appendChild(text);
        toast.classList.add('show');
        container.appendChild(toast);
        window.setTimeout(function () { if (toast.parentNode) toast.remove(); }, duration || 4000);
    };
    window.safeToast = function (message, type, duration) {
        try {
            if (typeof window.showToast === 'function' && byId('toastContainer')) window.showToast(message, type, duration);
            else window.alert(message);
        } catch (e) { window.alert(message); }
    };

    window.renderFlashes = function () {
        (window.__flashes || []).forEach(function (item) {
            var category = item[0];
            var message = item[1];
            var type = category === 'success' ? 'success' : category === 'error' ? 'error' : 'info';
            window.safeToast(message, type);
        });
    };

    window.QueryCard = (function () {
        var timers = {};
        function elapsed(start) {
            var seconds = Math.floor((Date.now() - start) / 1000);
            var minutes = Math.floor(seconds / 60);
            return minutes > 0 ? minutes + ' 分 ' + (seconds % 60) + ' 秒' : seconds + ' 秒';
        }
        function setState(id, cls, text) {
            window.clearInterval(timers[id]);
            var el = byId(id);
            if (!el) return;
            el.className = 'q-card ' + cls;
            el.textContent = text;
        }
        function run(id, text) {
            var el = byId(id);
            if (!el) return { done: function () {}, fail: function () {} };
            var start = Date.now();
            el.style.display = 'block';
            el.className = 'q-card q-running';
            el.innerHTML = '<div class="d-flex align-items-center gap-2"><div class="q-progress"><div class="q-bar"></div></div><span class="q-text"></span></div>';
            var label = el.querySelector('.q-text');
            if (label) label.textContent = (text || '查询进行中') + '，已用时 0 秒';
            window.clearInterval(timers[id]);
            timers[id] = window.setInterval(function () {
                if (label) label.textContent = (text || '查询进行中') + '，已用时 ' + elapsed(start);
            }, 1000);
            return {
                done: function (msg) { setState(id, 'q-done', '完成  ' + msg); },
                fail: function (msg) { setState(id, 'q-fail', '失败  ' + msg); }
            };
        }
        return { run: run };
    }());

    window.isBlank = function (value) {
        if (value === null || value === undefined) return true;
        return /^[\s\u00a0\u3000\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u202f\u205f\u2060\ufeff]*$/.test(String(value));
    };
    window.syncConfirmedSection = function (checkbox, sectionId) {
        var section = byId(sectionId);
        if (section && checkbox) section.classList.toggle('section-disabled', checkbox.checked);
    };
    window.watchTable = function (tableId, checkbox, sectionId) {
        var table = byId(tableId);
        if (!table || !checkbox) return;
        function hasValue() {
            return Array.prototype.some.call(table.querySelectorAll('input[type="text"]'), function (input) {
                return !window.isBlank(input.value);
            });
        }
        function syncFromTable() {
            if (hasValue()) checkbox.checked = false;
            window.syncConfirmedSection(checkbox, sectionId);
        }
        table.addEventListener('input', syncFromTable);
        var observer = new MutationObserver(syncFromTable);
        observer.observe(table, { childList: true, subtree: true });
        window.syncConfirmedSection(checkbox, sectionId);
    };

    window.Poller = (function () {
        function reenable(selector) {
            if (!selector) return;
            var button = document.querySelector(selector);
            if (button) button.disabled = false;
        }
        function poll(opts) {
            opts = opts || {};
            var deadline = Date.now() + (opts.deadlineMin || 30) * 60 * 1000;
            var timer = window.setInterval(function () {
                if (Date.now() > deadline) {
                    window.clearInterval(timer);
                    reenable(opts.buttonSelector);
                    if (opts.onTimeout) opts.onTimeout(opts.card);
                    else if (opts.card) opts.card.fail('等待超时，请重新查询');
                    return;
                }
                fetch(opts.statusUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                    .then(function (response) { return response.json(); })
                    .then(function (result) {
                        var status = (result && result.data) || {};
                        if (status.status === 'done') {
                            window.clearInterval(timer);
                            reenable(opts.buttonSelector);
                            if (opts.onDone) opts.onDone(status, opts.card);
                        } else if (status.status === 'error') {
                            window.clearInterval(timer);
                            reenable(opts.buttonSelector);
                            if (opts.onError) opts.onError(status.error, opts.card);
                            else if (opts.card) opts.card.fail(status.error || '查询失败');
                        }
                    })
                    .catch(function () {
                        if (opts.onPollError) opts.onPollError(opts.card);
                    });
            }, opts.intervalMs || 2000);
            return timer;
        }
        return { poll: poll };
    }());

    window.escapeHtml = function (value) {
        if (value === null || value === undefined) return null;
        return String(value).replace(/[&<>"']/g, function (character) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character];
        });
    };

    window.AppFilter = (function () {
        function parseDateHead(value) {
            if (!value) return null;
            var match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value).trim());
            return match ? new Date(+match[1], +match[2] - 1, +match[3]) : null;
        }
        function rangeStart(months) {
            var date = new Date();
            date.setHours(0, 0, 0, 0);
            date.setDate(date.getDate() - (months === 12 ? 365 : months * 30));
            return date;
        }
        function findTable(input) {
            var tableId = input.getAttribute('data-table');
            if (tableId) return byId(tableId);
            return input.closest('table') || (input.closest('.card') && input.closest('.card').querySelector('table'));
        }
        function filter(inputId) {
            var input = byId(inputId);
            if (!input) return;
            var table = findTable(input);
            if (!table) return;
            var controls = table.querySelectorAll('.filter-row input, .filter-row select');
            if (!controls.length) {
                controls = document.querySelectorAll('[data-filter-table="' + table.id + '"], [data-table="' + table.id + '"]');
            }
            table.querySelectorAll('tbody tr').forEach(function (row) {
                if (row.classList.contains('empty-state-row')) return;
                var visible = true;
                controls.forEach(function (control) {
                    if (!control.value) return;
                    var dateCol = control.getAttribute('data-date-col');
                    if (dateCol) {
                        var months = parseInt(control.value, 10);
                        if (months > 0) {
                            var cell = row.children[parseInt(dateCol, 10)];
                            var date = parseDateHead(cell ? cell.textContent : '');
                            if (!date || date < rangeStart(months)) visible = false;
                        }
                    } else {
                        var col = parseInt(control.getAttribute('data-col'), 10);
                        if (!isNaN(col)) {
                            var needle = control.value.toLowerCase();
                            var cellText = row.children[col] ? row.children[col].textContent.toLowerCase() : '';
                            if (cellText.indexOf(needle) < 0) visible = false;
                        }
                    }
                });
                row.style.display = visible ? '' : 'none';
            });
        }
        function clear(tableId) {
            var table = byId(tableId);
            if (!table) return;
            table.querySelectorAll('.filter-row input, .filter-row select, [data-filter-table="' + tableId + '"], [data-table="' + tableId + '"]').forEach(function (control) { control.value = ''; });
            table.querySelectorAll('tbody tr').forEach(function (row) { row.style.display = ''; });
        }
        function sort(table, column) {
            if (!table) return;
            var body = table.querySelector('tbody');
            if (!body) return;
            var rows = Array.prototype.slice.call(body.querySelectorAll('tr')).filter(function (row) { return !row.classList.contains('empty-state-row'); });
            var arrow = table.querySelector('th.sortable[data-col="' + column + '"] .sort-arrow');
            var direction = arrow && arrow.getAttribute('data-dir') === 'asc' ? 1 : -1;
            var next = direction === 1 ? 'desc' : 'asc';
            function cellText(row) {
                var text = row.children[column] ? row.children[column].textContent : '';
                text = text.trim().toLowerCase();
                return (text === '—' || text === '-') ? '' : text;   // 空值占位符不参与大小比较
            }
            rows.sort(function (a, b) {
                var left = cellText(a);
                var right = cellText(b);
                if (!left && right) return 1;    // 空值恒排最后（与排序方向无关）
                if (left && !right) return -1;
                if (left < right) return -direction;
                if (left > right) return direction;
                return 0;
            });
            rows.forEach(function (row) { body.appendChild(row); });
            table.querySelectorAll('th.sortable .sort-arrow').forEach(function (item) {
                item.textContent = '▲';
                item.setAttribute('data-dir', 'asc');
            });
            if (arrow) { arrow.textContent = next === 'asc' ? '▲' : '▼'; arrow.setAttribute('data-dir', next); }
        }
        return { filter: filter, sort: sort, clear: clear };
    }());

    // ===== 统一文件下载：fetch + Blob，保留服务端文件名，错误统一 toast，不跳页 =====
    window.downloadFile = function (url, options) {
        options = options || {};
        window.showLoader();
        fetch(url, {
            method: options.method || 'GET',
            body: options.body,
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (response) {
            var contentType = response.headers.get('Content-Type') || '';
            var disposition = response.headers.get('Content-Disposition') || '';
            var isAttachment = /(^|;)\s*attachment\s*(;|$)/i.test(disposition);
            if (!response.ok || contentType.indexOf('application/json') >= 0) {
                return response.text().then(function (body) {
                    var result = {};
                    try { result = JSON.parse(body); } catch (e) {}
                    throw new Error((result && result.message) || '下载失败，请重试');
                });
            }
            if (!isAttachment || contentType.indexOf('text/html') >= 0) {
                throw new Error('文件生成失败：服务器未返回下载附件');
            }
            var match = /filename\*=UTF-8''([^;]+)/i.exec(disposition) || /filename="?([^";]+)"?/i.exec(disposition);
            var filename = '';
            try { filename = match ? decodeURIComponent(match[1]) : ''; } catch (e) { filename = match ? match[1] : ''; }
            return response.blob().then(function (blob) { return { blob: blob, filename: filename }; });
        }).then(function (payload) {
            window.hideLoader();
            var link = document.createElement('a');
            link.href = URL.createObjectURL(payload.blob);
            if (payload.filename) link.download = payload.filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(function () { URL.revokeObjectURL(link.href); }, 3000);
        }).catch(function (error) {
            window.hideLoader();
            window.safeToast(error && error.message ? error.message : '下载失败，请重试', 'error', 8000);
        });
    };
    // 直链统一：a[data-download] 点击走 downloadFile（事件委托，局部刷新重建节点后依然生效）
    document.addEventListener('click', function (event) {
        if (!event.target || !event.target.closest) return;
        var link = event.target.closest('a[data-download]');
        if (!link) return;
        event.preventDefault();
        window.downloadFile(link.getAttribute('href'));
    });

    window.ListUI = (function () {
        var storageKey = 'reqmanListState';
        function saveState() {
            var state = { scrollTop: window.scrollY || 0, filters: {} };
            document.querySelectorAll('.filter-row input, .filter-row select, .filter-toolbar input, .filter-toolbar select').forEach(function (input) {
                if (input.id) state.filters[input.id] = input.value;
            });
            try { window.sessionStorage.setItem(storageKey, JSON.stringify(state)); } catch (e) {}
        }
        function restoreState() {
            try {
                var raw = window.sessionStorage.getItem(storageKey);
                if (!raw) return;
                var state = JSON.parse(raw);
                Object.keys(state.filters || {}).forEach(function (id) {
                    var input = byId(id);
                    if (input) input.value = state.filters[id];
                });
                document.querySelectorAll('.filter-row input, .filter-row select, .filter-toolbar input, .filter-toolbar select').forEach(function (input) {
                    if (input.value && input.id && window.AppFilter) window.AppFilter.filter(input.id);
                });
                if (state.scrollTop) window.scrollTo(0, state.scrollTop);
            } catch (e) {}
        }
        function openEditor(url) {
            var width = Math.min(1120, Math.max(720, (window.screen && window.screen.availWidth ? window.screen.availWidth - 80 : 960)));
            var height = Math.min(820, Math.max(620, (window.screen && window.screen.availHeight ? window.screen.availHeight - 120 : 720)));
            var features = 'popup=yes,width=' + width + ',height=' + height + ',resizable=yes,scrollbars=yes';
            window.open(url, '_blank', features);
        }
        function updateEmptyState() {
            document.querySelectorAll('table').forEach(function (table) {
                var body = table.querySelector('tbody');
                if (!body) return;
                var dataRows = body.querySelectorAll('tr:not(.empty-state-row)');
                var empty = body.querySelector('.empty-state-row');
                if (empty) empty.style.display = dataRows.length ? 'none' : '';
            });
        }
        function del(url, confirmMessage, rowId, button) {
            window.confirmModal({ title: '确认删除', body: confirmMessage || '确认删除？', danger: true, okText: '删除' }).then(function (ok) {
                if (!ok) return;
                window.showLoader();
                fetch(url, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                    .then(function (response) { return response.json(); })
                    .then(function (result) {
                        window.hideLoader();
                        if (result && result.success) {
                            window.showToast(result.message || '删除成功', 'success');
                            var row = button && button.closest ? button.closest('tr') : null;
                            if (!row && rowId) row = document.querySelector('tr[data-id="' + (window.CSS ? CSS.escape(rowId) : rowId) + '"]');
                            if (row) { row.remove(); updateEmptyState(); }
                            else { saveState(); window.location.reload(); }
                        } else window.showToast((result && result.message) || '删除失败', 'error');
                    })
                    .catch(function () { window.hideLoader(); window.showToast('删除失败，请重试', 'error'); });
            });
        }
        function delFrom(button) {
            del(button.getAttribute('data-url'), button.getAttribute('data-confirm') || '确认删除？', button.getAttribute('data-id'), button);
        }
        window.addEventListener('message', function (event) {
            var data = event.data;
            if (data && data.type && /Saved$/.test(data.type)) { saveState(); window.location.reload(); }
        });
        return { openEditor: openEditor, del: del, delFrom: delFrom, saveState: saveState, restoreState: restoreState };
    }());

    window.apiSubmit = function (form, url, options) {
        options = options || {};
        var button = options.button || (form && form.querySelector('button[type="submit"]'));
        if (button) button.disabled = true;
        if (window.clearFieldErrors) window.clearFieldErrors(form);
        window.showLoader();
        fetch(url, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (response) { return response.json(); })
            .then(function (result) {
                window.hideLoader();
                if (button) button.disabled = false;
                if (result && result.success) {
                    if (options.onSuccess) options.onSuccess(result);
                    else window.safeToast(result.message || '保存成功', 'success');
                } else {
                    if (result && result.field && window.markFieldError) window.markFieldError(form, result.field, result.message || '');
                    if (options.onError) options.onError(result);
                    else if (!result || !result.field) window.safeToast((result && result.message) || '保存失败', 'error');
                }
            })
            .catch(function () {
                window.hideLoader();
                if (button) button.disabled = false;
                if (options.onError) options.onError();
                else window.safeToast('提交失败，请重试', 'error');
            });
    };

    window.clearFieldErrors = function (form) {
        if (form) form.querySelectorAll('.is-invalid').forEach(function (item) { item.classList.remove('is-invalid'); });
    };
    window.markFieldError = function (form, field, message) {
        if (!form || !field) { window.safeToast(message || '保存失败', 'error'); return; }
        var element = form.querySelector('[name="' + field + '"], #' + field);
        if (!element) { window.safeToast(message || '保存失败', 'error'); return; }
        element.classList.add('is-invalid');
        try { element.focus(); } catch (e) {}
        window.safeToast(message || '请检查标红字段', 'error');
    };

    window.confirmModal = function (options) {
        options = options || {};
        return new Promise(function (resolve) {
            var modal = byId('globalConfirmModal');
            if (!modal || typeof window.bootstrap === 'undefined' || !window.bootstrap.Modal) {
                resolve(window.confirm(options.body || '确认？'));
                return;
            }
            var title = modal.querySelector('.modal-title');
            var body = modal.querySelector('.modal-body');
            var ok = modal.querySelector('[data-role="ok"]');
            var cancel = modal.querySelector('[data-role="cancel"]');
            if (!ok || !cancel) { resolve(window.confirm(options.body || '确认？')); return; }
            if (title) title.textContent = options.title || '请确认';
            if (body) body.textContent = options.body || '确认执行此操作？';
            ok.textContent = options.okText || '确认';
            ok.className = 'btn btn-sm ' + (options.danger ? 'btn-danger' : 'btn-primary');
            function cleanup() {
                ok.removeEventListener('click', onOk);
                cancel.removeEventListener('click', onCancel);
                modal.removeEventListener('hidden.bs.modal', onCancel);
            }
            function onOk() { cleanup(); resolve(true); bootstrap.Modal.getOrCreateInstance(modal).hide(); }
            function onCancel() { cleanup(); resolve(false); }
            ok.addEventListener('click', onOk);
            cancel.addEventListener('click', onCancel);
            modal.addEventListener('hidden.bs.modal', onCancel);
            bootstrap.Modal.getOrCreateInstance(modal).show();
        });
    };

    window.fileSelected = function (input, zoneId) {
        var zone = byId(zoneId);
        if (!zone) return;
        var file = input && input.files ? input.files[0] : null;
        var name = file ? file.name : '';
        var nameEl = zone.querySelector('.file-name');
        zone.classList.toggle('has-file', !!name);
        if (nameEl) { nameEl.textContent = name ? '已选择：' + name : ''; nameEl.style.display = name ? 'block' : 'none'; }
    };

    window.amroSession = { ready: false, state: 'none', message: '', account: null, loginAt: null, duration: 0 };
    var probeInFlight = null;
    var loginPollTimer = null;
    function formatLoginDuration(seconds) {
        seconds = Math.max(parseInt(seconds || 0, 10), 0);
        return Math.floor(seconds / 86400) + '天' + Math.floor((seconds % 86400) / 3600) + '小时' + Math.floor((seconds % 3600) / 60) + '分钟';
    }
    window.amroCheckNow = function () {
        if (probeInFlight) return probeInFlight;
        probeInFlight = fetch('/inventory/session', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (response) { return response.json(); })
            .then(function (result) {
                var data = (result && result.data) || {};
                window.amroSession = { ready: !!data.ready, state: data.state || 'none', message: data.message || '', account: data.account || null, loginAt: data.login_at || null, duration: data.login_duration_seconds || 0 };
                var badge = byId('amroStatus');
                var alertBox = byId('amroAlert');
                var duration = formatLoginDuration(data.login_duration_seconds);
                if (badge) {
                    if (data.ready) { badge.textContent = '已登录 · ' + (data.account || '未登记'); badge.className = 'badge rounded-pill bg-success'; }
                    else if (data.state === 'probe_error') { badge.textContent = 'AMRO · 暂不可用'; badge.className = 'badge rounded-pill bg-warning text-dark'; }
                    else if (data.state === 'expired') { badge.textContent = 'AMRO · 已失效'; badge.className = 'badge rounded-pill bg-danger'; }
                    else { badge.textContent = 'AMRO · 未登录'; badge.className = 'badge rounded-pill bg-danger'; }
                }
                if (alertBox) {
                    alertBox.className = data.ready ? 'topbar-alert topbar-info' : 'topbar-alert topbar-warn';
                    alertBox.textContent = data.ready ? (data.message || ('登录账号：' + (data.account || '未登记') + '已登录') + ' · 登录时长：' + duration) : (data.message || 'AMRO 未登录');
                    alertBox.style.display = 'block';
                }
                return window.amroSession;
            })
            .catch(function () { window.amroSession.state = 'probe_error'; return window.amroSession; })
            .finally(function () { probeInFlight = null; });
        return probeInFlight;
    };
    window.amroRequireLogin = function () {
        if (window.amroSession && window.amroSession.ready) return true;
        window.safeToast('请先完成 AMRO 登录后再查询', 'warning');
        return false;
    };

    function initNavigation() {
        var toggle = byId('mobileNavToggle');
        if (!toggle) return;
        function close() { document.body.classList.remove('nav-open'); toggle.setAttribute('aria-expanded', 'false'); }
        toggle.addEventListener('click', function () {
            var open = document.body.classList.toggle('nav-open');
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        document.addEventListener('click', function (event) {
            if (document.body.classList.contains('nav-open') && !event.target.closest('.side-nav') && !event.target.closest('#mobileNavToggle')) close();
        });
        document.querySelectorAll('.side-nav a').forEach(function (link) { link.addEventListener('click', close); });
    }
    function initGlobal() {
        window.renderFlashes();
        initNavigation();
        var status = byId('amroStatus');
        if (status) {
            status.addEventListener('click', window.amroCheckNow);
            status.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); window.amroCheckNow(); } });
        }
        var login = byId('amroQuickLogin');
        if (login) {
            login.addEventListener('click', function () {
                var baseline = { loginAt: window.amroSession.loginAt, account: window.amroSession.account };
                if (loginPollTimer) window.clearInterval(loginPollTimer);
                window.safeToast('登录脚本已启动，请在 AMRO 页面完成登录', 'info', 8000);
                window.location.href = 'ReqManLogin://' + window.location.host;
                var startedAt = Date.now();
                loginPollTimer = window.setInterval(function () {
                    window.amroCheckNow().then(function (state) {
                        var isNew = state.ready && (!baseline.loginAt || state.loginAt !== baseline.loginAt || state.account !== baseline.account);
                        if (isNew) { window.clearInterval(loginPollTimer); loginPollTimer = null; window.safeToast('AMRO 登录成功', 'success', 5000); }
                        else if (Date.now() - startedAt >= 300000) { window.clearInterval(loginPollTimer); loginPollTimer = null; window.safeToast('等待登录脚本超时，请确认已运行最新配置包', 'warning', 8000); }
                    });
                }, 2000);
            });
        }
        window.amroCheckNow();
        window.setInterval(window.amroCheckNow, 600000);
        window.ListUI.restoreState();
    }
    window.addEventListener('focus', function () { window.amroCheckNow(); });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) window.amroCheckNow(); });
    onReady(initGlobal);
}());
