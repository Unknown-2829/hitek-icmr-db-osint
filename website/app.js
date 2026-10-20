/**
 * HiTek + ICMR DB OSINT (v2) — Frontend Application Engine
 * Pure Vanilla JavaScript · Zero Dependencies · Fully Mobile Optimized
 * 
 * Features:
 * - Real-time input type detection (Phone vs Aadhaar UID)
 * - Animated sliding segmented pill controls
 * - Multi-hop symmetric BFS graph traversal chain rendering
 * - Non-destructive clipboard copy with visual feedback
 * - Stateful SQLite WAL engine health monitoring
 * - Interactive Docs code snippet copy & TOC scroll spy
 * - Ambient background particle network
 */

(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────────
    const API_BASE = (function () {
        if (window.APP_CONFIG && window.APP_CONFIG.API_BASE !== undefined) {
            var configured = String(window.APP_CONFIG.API_BASE).trim();
            if (configured === '') {
                return window.location.origin;
            }
            return configured.replace(/\/+$/, '');
        }
        if (window.location.protocol.startsWith('http') && window.location.port !== '5500') {
            return window.location.origin;
        }
        return 'http://localhost:8000';
    })();

    // ── Toast Notifications ────────────────────────────────────
    function showToast(message, type, duration) {
        type = type || 'info';
        duration = duration || 4000;
        var container = document.getElementById('toastContainer');
        if (!container) return null;

        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.style.setProperty('--dur', duration + 'ms');

        var iconId = 'i-info';
        if (type === 'success') iconId = 'i-check';
        else if (type === 'error') iconId = 'i-x';
        else if (type === 'warning') iconId = 'i-alert';

        toast.innerHTML =
            '<span class="toast-icon">' +
                '<svg class="icon icon-sm"><use href="#' + iconId + '"/></svg>' +
            '</span>' +
            '<span class="toast-msg">' + escHtml(message) + '</span>' +
            '<button class="toast-close" type="button" aria-label="Close notification">' +
                '<svg class="icon icon-sm"><use href="#i-x"/></svg>' +
            '</button>';

        var closeBtn = toast.querySelector('.toast-close');
        var timer;

        function dismiss() {
            clearTimeout(timer);
            toast.classList.add('toast-exit');
            toast.addEventListener('animationend', function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, { once: true });
        }

        if (closeBtn) closeBtn.addEventListener('click', dismiss);
        timer = setTimeout(dismiss, duration);
        container.appendChild(toast);

        return { dismiss: dismiss };
    }

    // ── DOM Element Cache ──────────────────────────────────────
    var searchInput = document.getElementById('searchInput');
    var searchBtn = document.getElementById('searchBtn');
    var typeBadge = document.getElementById('typeBadge');
    var skeleton = document.getElementById('skeleton');
    var errorMsg = document.getElementById('errorMsg');
    var resultsCard = document.getElementById('resultsCard');
    var resultsTitle = document.getElementById('resultsTitle');
    var resultsTime = document.getElementById('resultsTime');
    var resultsBadges = document.getElementById('resultsBadges');
    var resultsBody = document.getElementById('resultsBody');
    var resultsStats = document.getElementById('resultsStats');
    var bfsChainWrap = document.getElementById('bfsChainWrap');
    var bfsChainNodes = document.getElementById('bfsChainNodes');
    var bfsChainDepthBadge = document.getElementById('bfsChainDepthBadge');
    var engineChip = document.getElementById('engineChip');
    var engineText = document.getElementById('engineText');
    var responseTimeEl = document.getElementById('responseTime');
    var modeSeg = document.getElementById('modeSeg');
    var depthSeg = document.getElementById('depthSeg');
    var menuToggle = document.getElementById('menuToggle');
    var navLinks = document.getElementById('navLinks');

    // ── Search State ───────────────────────────────────────────
    var currentMode = 'auto'; // 'auto' | 'phone' | 'aadhaar'
    var currentDepth = 3;     // 1 | 2 | 3
    var activeController = null;

    // ── Segmented Control Indicator Positioning ────────────────
    function updateSegIndicator(segEl) {
        if (!segEl) return;
        var activeBtn = segEl.querySelector('.seg-btn.active');
        var indicator = segEl.querySelector('.seg-indicator');
        if (!activeBtn || !indicator) return;

        indicator.style.transform = 'translateX(' + activeBtn.offsetLeft + 'px)';
        indicator.style.width = activeBtn.offsetWidth + 'px';
    }

    function initSegmentedControls() {
        // Mode Selector
        if (modeSeg) {
            var modeButtons = modeSeg.querySelectorAll('.seg-btn');
            modeButtons.forEach(function (btn) {
                btn.addEventListener('click', function () {
                    modeButtons.forEach(function (b) {
                        b.classList.remove('active');
                        b.setAttribute('aria-selected', 'false');
                    });
                    btn.classList.add('active');
                    btn.setAttribute('aria-selected', 'true');
                    currentMode = btn.getAttribute('data-mode') || 'auto';
                    updateSegIndicator(modeSeg);

                    if (searchInput) {
                        if (currentMode === 'phone') {
                            searchInput.placeholder = 'Enter 10-digit mobile number…';
                            searchInput.setAttribute('aria-label', 'Enter 10-digit mobile number');
                        } else if (currentMode === 'aadhaar') {
                            searchInput.placeholder = 'Enter 12-digit Aadhaar UID…';
                            searchInput.setAttribute('aria-label', 'Enter 12-digit Aadhaar UID');
                        } else {
                            searchInput.placeholder = 'Enter mobile number or Aadhaar UID…';
                            searchInput.setAttribute('aria-label', 'Enter 10-digit mobile or 12-digit Aadhaar UID');
                        }
                        updateLiveTypeBadge();
                        searchInput.focus();
                    }
                });
            });
            updateSegIndicator(modeSeg);
        }

        // Depth Selector
        if (depthSeg) {
            var depthButtons = depthSeg.querySelectorAll('.seg-btn');
            depthButtons.forEach(function (btn) {
                btn.addEventListener('click', function () {
                    depthButtons.forEach(function (b) {
                        b.classList.remove('active');
                    });
                    btn.classList.add('active');
                    currentDepth = parseInt(btn.getAttribute('data-depth'), 10) || 3;
                    updateSegIndicator(depthSeg);
                });
            });
            updateSegIndicator(depthSeg);
        }

        window.addEventListener('resize', function () {
            updateSegIndicator(modeSeg);
            updateSegIndicator(depthSeg);
        });
    }

    // ── Real-Time Type Badge Detector ──────────────────────────
    function detectInputType(raw) {
        if (!raw) return { type: null, valid: false };
        var stripped = raw.trim();
        var hasPlus = stripped.startsWith('+');
        var digits = stripped.replace(/\D/g, '');

        if (!digits) return { type: null, valid: false };

        // Normalize phone prefixes
        var normDigits = digits;
        if (digits.length === 13 && digits.startsWith('091')) normDigits = digits.slice(3);
        else if (digits.length === 11 && digits.startsWith('0')) normDigits = digits.slice(1);
        else if (digits.length === 12 && digits.startsWith('91') && (hasPlus || /^91[\s\-\.]/.test(stripped))) normDigits = digits.slice(2);

        // 10-digit mobile check (Indian mobile starts with 6, 7, 8, 9)
        if (normDigits.length === 10 && '6789'.indexOf(normDigits[0]) !== -1) {
            return { type: 'phone', valid: true, value: normDigits };
        }

        // 12-digit Aadhaar UID check (cannot have +91 prefix)
        if (digits.length === 12 && !hasPlus) {
            return { type: 'aadhaar', valid: true, value: digits };
        }

        return { type: 'invalid', valid: false, value: digits };
    }

    function updateLiveTypeBadge() {
        if (!typeBadge || !searchInput) return;
        var raw = searchInput.value.trim();
        if (!raw) {
            typeBadge.className = 'type-badge';
            typeBadge.textContent = '';
            return;
        }

        var detected = detectInputType(raw);

        if (currentMode === 'phone') {
            if (detected.type === 'phone') {
                typeBadge.className = 'type-badge show phone';
                typeBadge.textContent = 'Phone (10D)';
            } else {
                typeBadge.className = 'type-badge show invalid';
                typeBadge.textContent = '10D Mobile Required';
            }
        } else if (currentMode === 'aadhaar') {
            if (detected.type === 'aadhaar') {
                typeBadge.className = 'type-badge show aadhaar';
                typeBadge.textContent = 'Aadhaar (12D)';
            } else {
                typeBadge.className = 'type-badge show invalid';
                typeBadge.textContent = '12D UID Required';
            }
        } else {
            // Auto Mode
            if (detected.type === 'phone') {
                typeBadge.className = 'type-badge show phone';
                typeBadge.textContent = 'Phone (10D)';
            } else if (detected.type === 'aadhaar') {
                typeBadge.className = 'type-badge show aadhaar';
                typeBadge.textContent = 'Aadhaar (12D)';
            } else {
                typeBadge.className = 'type-badge show invalid';
                typeBadge.textContent = '10D Phone / 12D UID';
            }
        }
    }

    // ── Quick Sample Chips ─────────────────────────────────────
    function initSampleChips() {
        document.querySelectorAll('.sample-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var sampleVal = chip.getAttribute('data-sample') || chip.textContent.trim();
                if (!searchInput) return;
                searchInput.value = sampleVal;

                var detected = detectInputType(sampleVal);
                var targetMode = (detected.type === 'aadhaar') ? 'aadhaar' : 'phone';

                if (modeSeg) {
                    var targetBtn = modeSeg.querySelector('.seg-btn[data-mode="' + targetMode + '"]');
                    if (targetBtn) {
                        modeSeg.querySelectorAll('.seg-btn').forEach(function (b) {
                            b.classList.remove('active');
                            b.setAttribute('aria-selected', 'false');
                        });
                        targetBtn.classList.add('active');
                        targetBtn.setAttribute('aria-selected', 'true');
                        currentMode = targetMode;
                        updateSegIndicator(modeSeg);
                    }
                }

                updateLiveTypeBadge();
                searchInput.focus();
                doSearch();
            });
        });
    }

    // ── Input Cleaning for Search Execution ─────────────────────
    function cleanQueryForSearch(raw, mode) {
        if (!raw) return null;
        var detected = detectInputType(raw);

        if (mode === 'phone') {
            if (detected.type === 'phone') return { value: detected.value, type: 'phone' };
            return null;
        }
        if (mode === 'aadhaar') {
            if (detected.type === 'aadhaar') return { value: detected.value, type: 'aadhaar' };
            return null;
        }

        // Auto mode
        if (detected.valid) {
            return { value: detected.value, type: detected.type };
        }
        return null;
    }

    // ── Search Execution ───────────────────────────────────────
    async function doSearch() {
        if (!searchInput) return;
        var raw = searchInput.value.trim();

        if (!raw) {
            showToast('Enter a phone number or Aadhaar UID.', 'warning', 3000);
            searchInput.focus();
            return;
        }

        var query = cleanQueryForSearch(raw, currentMode);
        if (!query) {
            hideAllResults();
            showErrorCard('Invalid format. Enter a valid 10-digit Indian mobile number (e.g. 9876543210) or a 12-digit Aadhaar UID.');
            showToast('Invalid number format.', 'error', 3500);
            return;
        }

        if (activeController) {
            activeController.abort();
        }
        activeController = new AbortController();

        hideAllResults();
        setLoadingState(true);

        var queryParam = 'q=' + encodeURIComponent(query.value);
        if (query.type === 'phone' && currentMode === 'phone') {
            queryParam = 'mobile=' + encodeURIComponent(query.value);
        } else if (query.type === 'aadhaar' && currentMode === 'aadhaar') {
            queryParam = 'aadhaar=' + encodeURIComponent(query.value);
        }

        var url = API_BASE + '/api/lookup?' + queryParam + '&depth=' + currentDepth;
        var startTime = performance.now();

        try {
            var response = await fetch(url, {
                signal: activeController.signal,
                headers: {
                    'Accept': 'application/json'
                }
            });

            var elapsed = Math.round(performance.now() - startTime);
            var data = await response.json();

            if (!response.ok) {
                var errDetail = (data && data.detail) ? data.detail : null;
                var errMsg = 'Lookup request failed (HTTP ' + response.status + ').';
                if (typeof errDetail === 'string') {
                    errMsg = errDetail;
                } else if (errDetail && errDetail.message) {
                    errMsg = errDetail.message;
                } else if (data && data.error && data.error.message) {
                    errMsg = data.error.message;
                }

                if (response.status === 401) {
                    errMsg = 'API Authentication required. Configure your API key.';
                } else if (response.status === 429) {
                    var retryAfter = response.headers.get('Retry-After') || '60';
                    errMsg = 'Rate limit exceeded. Please wait ' + retryAfter + ' seconds.';
                }

                showErrorCard(errMsg);
                showToast(errMsg, 'error', 4500);
                return;
            }

            // Successfully received response
            renderLookupResults(data, query.value, elapsed);

        } catch (err) {
            if (err.name === 'AbortError') return;
            var isConnErr = err.message.indexOf('Failed to fetch') !== -1 || err.message.indexOf('NetworkError') !== -1;
            var networkMsg = isConnErr
                ? 'Cannot connect to SQLite API at ' + API_BASE + '. Please verify that uvicorn is running.'
                : 'Lookup error: ' + err.message;
            showErrorCard(networkMsg);
            showToast(isConnErr ? 'API unreachable' : err.message, 'error', 5000);
        } finally {
            setLoadingState(false);
        }
    }

    function setLoadingState(isLoading) {
        if (!searchBtn) return;
        if (isLoading) {
            searchBtn.classList.add('loading');
            searchBtn.disabled = true;
            searchBtn.setAttribute('aria-busy', 'true');
            if (skeleton) skeleton.hidden = false;
        } else {
            searchBtn.classList.remove('loading');
            searchBtn.disabled = false;
            searchBtn.setAttribute('aria-busy', 'false');
            if (skeleton) skeleton.hidden = true;
        }
    }

    function hideAllResults() {
        if (skeleton) skeleton.hidden = true;
        if (errorMsg) errorMsg.hidden = true;
        if (resultsCard) {
            resultsCard.hidden = true;
            resultsCard.classList.remove('is-notfound');
        }
        if (bfsChainWrap) bfsChainWrap.hidden = true;
    }

    function showErrorCard(message) {
        if (!errorMsg) return;
        errorMsg.innerHTML =
            '<svg class="icon"><use href="#i-alert"/></svg>' +
            '<div>' + escHtml(message) + '</div>';
        errorMsg.hidden = false;
    }

    // ── Render Results ─────────────────────────────────────────
    function renderLookupResults(data, queryVal, clientElapsed) {
        hideAllResults();
        if (!resultsCard) return;

        var ms = (data.response_time_ms !== undefined) ? data.response_time_ms : clientElapsed;
        if (resultsTime) resultsTime.textContent = ms + ' ms';
        if (responseTimeEl) responseTimeEl.textContent = ms + ' ms';

        // ── Not Found State ──
        if (!data.found || !data.total_records) {
            resultsCard.classList.add('is-notfound');
            if (resultsTitle) resultsTitle.textContent = 'NO RECORDS FOUND';
            if (resultsBadges) {
                resultsBadges.innerHTML =
                    '<span class="badge">0 Records</span>' +
                    '<span class="badge">Depth ' + (data.search_depth || currentDepth) + '</span>';
            }
            if (resultsBody) {
                resultsBody.innerHTML =
                    '<div class="notfound">' +
                        '<div class="notfound-icon"><svg class="icon" style="width:26px;height:26px;"><use href="#i-search-x"/></svg></div>' +
                        '<div class="notfound-title">No records located for <strong>' + escHtml(queryVal) + '</strong></div>' +
                        '<p class="notfound-hint">Try selecting 3 hops depth or verifying the mobile / Aadhaar number.</p>' +
                    '</div>';
            }
            if (resultsStats) resultsStats.textContent = '0 records found in SQLite database';
            resultsCard.hidden = false;
            showToast('No records found for ' + queryVal, 'info', 3000);
            return;
        }

        // ── Target Located State ──
        resultsCard.classList.remove('is-notfound');
        if (resultsTitle) resultsTitle.textContent = 'TARGET LOCATED';

        if (resultsBadges) {
            var badgesHtml = [
                '<span class="badge badge-success"><svg class="icon icon-sm"><use href="#i-check"/></svg>' + data.total_records + ' Record(s)</span>',
                '<span class="badge badge-accent"><svg class="icon icon-sm"><use href="#i-network"/></svg>' + (data.search_depth || 1) + ' Hop(s)</span>'
            ];
            if (data.truncated) {
                badgesHtml.push('<span class="badge" style="color:var(--warning);border-color:rgba(251,191,36,0.3);">Truncated at Cap</span>');
            }
            resultsBadges.innerHTML = badgesHtml.join('');
        }

        // ── Render BFS Traversal Chain ──
        renderBfsChain(data, queryVal);

        // ── Render Identity Groups ──
        var bodyHtml = '';

        // Primary Phone Numbers
        if (data.phones && data.phones.length) {
            bodyHtml += '<div class="rgroup" style="--d:0ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-phone"/></svg>Primary Phones</div>' +
                '<div class="rgroup-value">' +
                    data.phones.map(function (ph) {
                        return '<button type="button" class="chip" data-copy="' + escHtml(ph) + '" title="Click to copy">' +
                            escHtml(ph) +
                            '<svg class="icon chip-ic-copy"><use href="#i-copy"/></svg>' +
                            '<svg class="icon chip-ic-check"><use href="#i-check"/></svg>' +
                        '</button>';
                    }).join('') +
                '</div></div>';
        }

        // Aadhaar UIDs
        if (data.aadhar_numbers && data.aadhar_numbers.length) {
            bodyHtml += '<div class="rgroup" style="--d:40ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-id"/></svg>Aadhaar UID</div>' +
                '<div class="rgroup-value">' +
                    data.aadhar_numbers.map(function (ad) {
                        return '<button type="button" class="chip chip-aadhaar" data-copy="' + escHtml(ad) + '" title="Click to copy">' +
                            escHtml(ad) +
                            '<svg class="icon chip-ic-copy"><use href="#i-copy"/></svg>' +
                            '<svg class="icon chip-ic-check"><use href="#i-check"/></svg>' +
                        '</button>';
                    }).join('') +
                '</div></div>';
        }

        // Alternate / Linked Numbers
        if (data.other_numbers && data.other_numbers.length) {
            bodyHtml += '<div class="rgroup" style="--d:80ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-network"/></svg>Alternate Numbers</div>' +
                '<div class="rgroup-value">' +
                    data.other_numbers.map(function (on) {
                        return '<button type="button" class="chip chip-alt" data-copy="' + escHtml(on) + '" title="Click to copy">' +
                            escHtml(on) +
                            '<svg class="icon chip-ic-copy"><use href="#i-copy"/></svg>' +
                            '<svg class="icon chip-ic-check"><use href="#i-check"/></svg>' +
                        '</button>';
                    }).join('') +
                '</div></div>';
        }

        // Full Names
        if (data.names && data.names.length) {
            bodyHtml += '<div class="rgroup" style="--d:120ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-user"/></svg>Full Name</div>' +
                '<div class="rgroup-value">' +
                    data.names.map(function (n) { return '<span class="val-line">' + escHtml(n) + '</span>'; }).join('') +
                '</div></div>';
        }

        // Father's Names
        if (data.father_names && data.father_names.length) {
            bodyHtml += '<div class="rgroup" style="--d:160ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-users"/></svg>Father\'s Name</div>' +
                '<div class="rgroup-value">' +
                    data.father_names.map(function (f) { return '<span class="val-line">' + escHtml(f) + '</span>'; }).join('') +
                '</div></div>';
        }

        // Addresses
        if (data.addresses && data.addresses.length) {
            bodyHtml += '<div class="rgroup" style="--d:200ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-map-pin"/></svg>Address Profile</div>' +
                '<div class="rgroup-value">' +
                    data.addresses.map(function (a) {
                        return '<div class="addr">' + escHtml(cleanAddress(a)) + '</div>';
                    }).join('') +
                '</div></div>';
        }

        // Geographic Details
        var geoPills = [];
        if (data.districts && data.districts.length) {
            data.districts.forEach(function (d) {
                geoPills.push('<span class="geo-pill"><b>DISTRICT</b> ' + escHtml(d) + '</span>');
            });
        }
        if (data.states && data.states.length) {
            data.states.forEach(function (s) {
                geoPills.push('<span class="geo-pill"><b>STATE</b> ' + escHtml(s) + '</span>');
            });
        }
        if (data.pincodes && data.pincodes.length) {
            data.pincodes.forEach(function (p) {
                geoPills.push('<span class="geo-pill"><b>PINCODE</b> ' + escHtml(p) + '</span>');
            });
        }
        if (data.regions && data.regions.length) {
            data.regions.forEach(function (r) {
                geoPills.push('<span class="geo-pill"><b>CIRCLE</b> ' + escHtml(r) + '</span>');
            });
        }

        if (geoPills.length) {
            bodyHtml += '<div class="rgroup" style="--d:240ms">' +
                '<div class="rgroup-label"><svg class="icon"><use href="#i-globe"/></svg>Geographic Intel</div>' +
                '<div class="rgroup-value"><div class="geo-row">' + geoPills.join('') + '</div></div></div>';
        }

        if (resultsBody) resultsBody.innerHTML = bodyHtml;

        if (resultsStats) {
            var stats = [data.total_records + ' records located'];
            if (data.phones && data.phones.length) stats.push(data.phones.length + ' phone(s)');
            if (data.aadhar_numbers && data.aadhar_numbers.length) stats.push(data.aadhar_numbers.length + ' Aadhaar UID(s)');
            if (data.search_depth) stats.push(data.search_depth + ' hop traversal');
            resultsStats.textContent = stats.join(' · ');
        }

        resultsCard.hidden = false;
        showToast('Target located: ' + data.total_records + ' record(s) across ' + (data.search_depth || 1) + ' hop(s).', 'success', 3500);
    }

    function renderBfsChain(data, seedVal) {
        if (!bfsChainWrap || !bfsChainNodes) return;
        var nodes = [];

        // Seed Node
        var isSeedAadhaar = seedVal && seedVal.length === 12;
        nodes.push({
            type: 'SEED ' + (isSeedAadhaar ? 'AADHAAR' : 'PHONE'),
            val: seedVal,
            cls: 'seed'
        });

        // Discovered Aadhaar UIDs
        if (data.aadhar_numbers && data.aadhar_numbers.length) {
            data.aadhar_numbers.forEach(function (ad) {
                if (ad !== seedVal) {
                    nodes.push({
                        type: 'LINKED AADHAAR',
                        val: ad,
                        cls: 'aadhaar'
                    });
                }
            });
        }

        // Discovered Alternate Phones
        if (data.other_numbers && data.other_numbers.length) {
            data.other_numbers.slice(0, 3).forEach(function (on) {
                if (on !== seedVal) {
                    nodes.push({
                        type: 'LINKED PHONE',
                        val: on,
                        cls: 'seed'
                    });
                }
            });
        }

        // Discovered Names
        if (data.names && data.names.length) {
            nodes.push({
                type: 'RESOLVED IDENTITY',
                val: data.names[0],
                cls: 'identity'
            });
        }

        if (nodes.length <= 1) {
            bfsChainWrap.hidden = true;
            return;
        }

        if (bfsChainDepthBadge) {
            bfsChainDepthBadge.textContent = 'Depth ' + (data.search_depth || currentDepth);
        }

        var chainHtml = '';
        for (var i = 0; i < nodes.length; i++) {
            if (i > 0) {
                chainHtml += '<svg class="icon icon-sm bfs-arrow"><use href="#i-arrow-right"/></svg>';
            }
            chainHtml += '<div class="bfs-node ' + nodes[i].cls + '" style="--d:' + (i * 50) + 'ms">' +
                '<span class="bfs-node-type">' + escHtml(nodes[i].type) + '</span>' +
                '<span class="bfs-node-val">' + escHtml(nodes[i].val) + '</span>' +
            '</div>';
        }

        bfsChainNodes.innerHTML = chainHtml;
        bfsChainWrap.hidden = false;
    }

    // ── Non-Destructive Clipboard Copying ──────────────────────
    function copyText(text, btnElement) {
        if (!text) return;

        function onSuccess() {
            if (btnElement) {
                btnElement.classList.add('copied');
                setTimeout(function () {
                    btnElement.classList.remove('copied');
                }, 2000);
            }
            showToast('Copied: ' + text, 'success', 2000);
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(onSuccess).catch(function () {
                fallbackCopy(text, onSuccess);
            });
        } else {
            fallbackCopy(text, onSuccess);
        }
    }

    function fallbackCopy(text, callback) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '-9999px';
        ta.setAttribute('readonly', '');
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            if (callback) callback();
        } catch (e) {
            showToast('Failed to copy to clipboard', 'error', 2000);
        }
        document.body.removeChild(ta);
    }

    // Delegated click listener for all data-copy elements
    document.addEventListener('click', function (e) {
        var copyBtn = e.target.closest('[data-copy]');
        if (copyBtn) {
            var val = copyBtn.getAttribute('data-copy');
            if (val) {
                copyText(val, copyBtn);
            }
        }
    });

    // ── Engine Status Monitoring ───────────────────────────────
    async function checkEngineStatus() {
        if (!engineChip || !engineText) return;
        var startTime = performance.now();

        try {
            var response = await fetch(API_BASE + '/health', {
                signal: AbortSignal.timeout ? AbortSignal.timeout(6000) : undefined
            });
            var latency = Math.round(performance.now() - startTime);

            if (response.ok) {
                var data = await response.json();
                var isOk = (data && data.status === 'healthy');
                if (isOk) {
                    engineChip.className = 'engine-chip online';
                    engineText.textContent = 'SQLite WAL · Operational';
                    if (responseTimeEl) responseTimeEl.textContent = '~' + latency + ' ms';
                } else {
                    engineChip.className = 'engine-chip offline';
                    engineText.textContent = 'SQLite WAL · Degraded';
                }
            } else {
                engineChip.className = 'engine-chip offline';
                engineText.textContent = 'SQLite WAL · HTTP ' + response.status;
            }
        } catch (e) {
            engineChip.className = 'engine-chip offline';
            engineText.textContent = 'SQLite WAL · Unreachable';
        }
    }

    // ── Mobile Navigation Toggle ───────────────────────────────
    function initMobileNavigation() {
        if (!menuToggle || !navLinks) return;

        menuToggle.addEventListener('click', function () {
            var isOpen = navLinks.classList.toggle('open');
            menuToggle.setAttribute('aria-expanded', String(isOpen));
        });

        navLinks.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                navLinks.classList.remove('open');
                menuToggle.setAttribute('aria-expanded', 'false');
            });
        });
    }

    // ── Ambient Background Particle Canvas ─────────────────────
    function initBackgroundCanvas() {
        var canvas = document.getElementById('bgCanvas');
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        var particles = [];
        var count = 35;

        function resize() {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }
        resize();
        window.addEventListener('resize', resize);

        for (var i = 0; i < count; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: Math.random() * canvas.height,
                radius: Math.random() * 1.4 + 0.6,
                vx: (Math.random() - 0.5) * 0.28,
                vy: (Math.random() - 0.5) * 0.28,
                alpha: Math.random() * 0.35 + 0.15
            });
        }

        function draw() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            for (var i = 0; i < particles.length; i++) {
                var p = particles[i];
                p.x += p.vx;
                p.y += p.vy;

                if (p.x < 0) p.x = canvas.width;
                else if (p.x > canvas.width) p.x = 0;
                if (p.y < 0) p.y = canvas.height;
                else if (p.y > canvas.height) p.y = 0;

                ctx.beginPath();
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(167, 139, 250, ' + p.alpha + ')';
                ctx.fill();
            }

            // Draw connective web
            for (var i = 0; i < particles.length; i++) {
                for (var j = i + 1; j < particles.length; j++) {
                    var dx = particles[i].x - particles[j].x;
                    var dy = particles[i].y - particles[j].y;
                    var dist = Math.sqrt(dx * dx + dy * dy);

                    if (dist < 115) {
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = 'rgba(167, 139, 250, ' + (0.07 * (1 - dist / 115)) + ')';
                        ctx.lineWidth = 0.6;
                        ctx.stroke();
                    }
                }
            }

            requestAnimationFrame(draw);
        }

        draw();
    }

    // ── Docs Page Interactions ─────────────────────────────────
    function initDocsPage() {
        var docsLayout = document.querySelector('.docs-layout');
        if (!docsLayout) return;

        // Enhance <pre> code blocks with interactive copy header
        document.querySelectorAll('.docs-content pre').forEach(function (pre) {
            var parent = pre.parentElement;
            if (parent && parent.classList.contains('code-block')) return;

            var lang = pre.getAttribute('data-lang') || 'code';
            var wrapper = document.createElement('div');
            wrapper.className = 'code-block';

            var head = document.createElement('div');
            head.className = 'code-head';
            head.innerHTML =
                '<span class="code-lang">' + escHtml(lang) + '</span>' +
                '<button type="button" class="code-copy">' +
                    '<svg class="icon icon-sm"><use href="#i-copy"/></svg>' +
                    '<span>Copy</span>' +
                '</button>';

            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(head);
            wrapper.appendChild(pre);

            var copyBtn = head.querySelector('.code-copy');
            if (copyBtn) {
                copyBtn.addEventListener('click', function () {
                    var text = pre.textContent;
                    copyText(text, copyBtn);
                    var span = copyBtn.querySelector('span');
                    if (span) {
                        span.textContent = 'Copied!';
                        setTimeout(function () { span.textContent = 'Copy'; }, 2000);
                    }
                });
            }
        });

        // Sticky TOC Scroll Spy
        var tocLinks = document.querySelectorAll('.docs-toc .toc-link');
        var sections = document.querySelectorAll('.docs-section[id]');

        if (tocLinks.length && sections.length && ('IntersectionObserver' in window)) {
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        var id = entry.target.getAttribute('id');
                        tocLinks.forEach(function (link) {
                            var href = link.getAttribute('href');
                            if (href === '#' + id) {
                                link.classList.add('active');
                            } else {
                                link.classList.remove('active');
                            }
                        });
                    }
                });
            }, {
                rootMargin: '-10% 0px -70% 0px',
                threshold: 0.1
            });

            sections.forEach(function (sec) {
                observer.observe(sec);
            });
        }
    }

    // ── Scroll Reveal Observer ─────────────────────────────────
    function initScrollReveal() {
        function revealAll() {
            document.querySelectorAll('.reveal').forEach(function (el) {
                el.classList.add('revealed');
            });
        }

        if (!('IntersectionObserver' in window)) {
            revealAll();
            return;
        }

        var reveals = document.querySelectorAll('.reveal');
        if (!reveals.length) return;

        var observer = new IntersectionObserver(function (entries, obs) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                    obs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.05, rootMargin: '0px 0px -15px 0px' });

        reveals.forEach(function (el) {
            observer.observe(el);
        });

        // Fallback safeguard to guarantee visibility
        setTimeout(revealAll, 600);
    }

    // ── String Helpers ─────────────────────────────────────────
    function escHtml(str) {
        if (str === null || str === undefined) return '';
        var d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

    function cleanAddress(raw) {
        if (!raw) return '';
        var addr = String(raw).replace(/!+/g, ', ');
        addr = addr.replace(/^[, ]+/, '');
        addr = addr.replace(/[, ]{2,}/g, ', ');
        addr = addr.replace(/[, ]+$/, '');
        return addr;
    }

    // ── Initialization on DOM Ready ────────────────────────────
    window.addEventListener('DOMContentLoaded', function () {
        initMobileNavigation();
        initSegmentedControls();
        initSampleChips();
        initBackgroundCanvas();
        initScrollReveal();
        initDocsPage();

        if (searchInput) {
            searchInput.addEventListener('input', updateLiveTypeBadge);
            searchInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    doSearch();
                }
            });
        }

        if (searchBtn) {
            searchBtn.addEventListener('click', function (e) {
                e.preventDefault();
                doSearch();
            });
        }

        // Live engine health check
        checkEngineStatus();

        // Welcome Toast on search page
        if (document.querySelector('.hero')) {
            setTimeout(function () {
                showToast('HiTek + ICMR OSINT v2 — Engine ready for lookup.', 'info', 3500);
            }, 800);
        }
    });

})();
