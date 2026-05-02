/* The Idea Graveyard — frontend logic (vanilla JS, no build step) */
(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);

    const state = {
        attachments: [],
        seed: '',
        mode: 'quick',
        result: null,
        recognition: null,
        recording: false,
    };

    // ---------- View switching ----------

    function showView(name) {
        ['inputView', 'loadingView', 'resultsView'].forEach((v) => {
            $(v).classList.toggle('view-active', v === name + 'View');
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // ---------- Attachments ----------

    function kindOf(file) {
        const m = (file.type || '').toLowerCase();
        const n = file.name.toLowerCase();
        if (m.startsWith('image/') || /\.(jpe?g|png|gif|webp)$/.test(n)) return 'image';
        if (m === 'application/pdf' || n.endsWith('.pdf')) return 'pdf';
        if (m.startsWith('audio/') || /\.(mp3|m4a|wav|webm|ogg|mp4)$/.test(n)) return 'audio';
        if (m.startsWith('text/') || /\.(txt|md|csv|json)$/.test(n)) return 'text';
        return 'other';
    }

    function fmtBytes(n) {
        if (n < 1024) return n + 'B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(0) + 'KB';
        return (n / 1024 / 1024).toFixed(1) + 'MB';
    }

    function renderAttachList() {
        const ul = $('attachList');
        ul.innerHTML = '';
        state.attachments.forEach((a, i) => {
            const li = document.createElement('li');
            li.innerHTML =
                '<span class="attach-meta">[' + a.kind.toUpperCase() + ']</span>' +
                '<span class="attach-name"></span>' +
                '<span class="attach-meta">' + fmtBytes(a.size) + '</span>' +
                '<button class="attach-remove" type="button" aria-label="Remove">[X]</button>';
            li.querySelector('.attach-name').textContent = a.name;
            li.querySelector('.attach-remove').addEventListener('click', () => {
                state.attachments.splice(i, 1);
                renderAttachList();
            });
            ul.appendChild(li);
        });
    }

    function handleFiles(fileList) {
        Array.from(fileList).forEach((file) => {
            if (!file) return;
            state.attachments.push({
                file: file,
                name: file.name,
                size: file.size,
                kind: kindOf(file),
            });
        });
        renderAttachList();
    }

    // ---------- Voice (Web Speech API) ----------

    function setupVoice() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            $('voiceBtn').addEventListener('click', () => {
                showError('Voice input not supported on this browser. Try Chrome or Safari, or attach an audio file instead.');
            });
            return;
        }
        const rec = new SR();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = 'en-US';
        let baseText = '';
        rec.onresult = (e) => {
            let interim = '';
            let final = '';
            for (let i = e.resultIndex; i < e.results.length; i++) {
                const t = e.results[i][0].transcript;
                if (e.results[i].isFinal) final += t;
                else interim += t;
            }
            const merged = (baseText + (final ? ' ' + final : '') + (interim ? ' ' + interim : '')).trim();
            $('seedInput').value = merged;
        };
        rec.onerror = (e) => {
            console.warn('Speech error', e);
            stopRec();
            if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
                showError('Microphone permission denied. Enable it in your browser settings.');
            }
        };
        rec.onend = () => {
            if (state.recording) {
                try { rec.start(); } catch (_) { stopRec(); }
            } else {
                stopRec();
            }
        };
        state.recognition = rec;

        function startRec() {
            baseText = $('seedInput').value.trim();
            try { rec.start(); } catch (_) {}
            state.recording = true;
            $('voiceBtn').classList.add('recording');
            $('voiceLabel').textContent = 'STOP';
            $('voiceGlyph').textContent = '[REC]';
        }
        function stopRec() {
            state.recording = false;
            try { rec.stop(); } catch (_) {}
            $('voiceBtn').classList.remove('recording');
            $('voiceLabel').textContent = 'VOICE';
            $('voiceGlyph').textContent = '[MIC]';
        }
        $('voiceBtn').addEventListener('click', () => {
            if (state.recording) stopRec(); else startRec();
        });
    }

    // ---------- Errors ----------

    function showError(msg) {
        const box = $('errorBox');
        box.textContent = '! ERROR: ' + msg;
        box.classList.remove('hidden');
        setTimeout(() => { box.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, 50);
    }
    function clearError() { $('errorBox').classList.add('hidden'); }

    // ---------- Loading: step-by-step animation ----------

    let loadingTimer = null;
    let waveTimer = null;
    const WAVE_CHARS = '\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588';

    function startLoading(mode) {
        const stepsEl = $('loadingSteps');
        const barFill = $('loadingBarFill');
        const pctEl = $('loadingPct');
        const signalEl = $('loadingSignal');

        $('loadingMode').textContent = mode === 'deep' ? 'DEEP' : 'QUICK';
        stepsEl.innerHTML = '';
        barFill.style.width = '0%';
        pctEl.textContent = '0%';
        signalEl.textContent = '';
        showView('loading');

        const steps = mode === 'deep' ? [
            { text: 'initializing',                     pct: 5  },
            { text: 'stage 1/4: diverging (12 dirs)',   pct: 28 },
            { text: 'stage 2/4: critiquing',            pct: 48 },
            { text: 'stage 3/4: expanding survivors',   pct: 72 },
            { text: 'stage 4/4: ranking',               pct: 92 },
        ] : [
            { text: 'initializing',             pct: 10 },
            { text: 'generating candidates',    pct: 50 },
            { text: 'selecting winner',         pct: 88 },
        ];

        const totalMs = mode === 'deep' ? 32000 : 7000;
        const start = performance.now();
        let currentStep = -1;
        let waveOffset = 0;

        function addStep(text) {
            const div = document.createElement('div');
            div.className = 'step active';
            div.innerHTML =
                '<span class="step-arrow">\u25b8</span> ' +
                '<span class="step-text">' + text + '</span>' +
                '<span class="step-dots"></span>' +
                '<span class="step-status"></span>';
            stepsEl.appendChild(div);
            stepsEl.scrollTop = stepsEl.scrollHeight;
            return div;
        }

        function completeStep(stepEl) {
            if (!stepEl) return;
            stepEl.querySelector('.step-dots').textContent = '';
            const st = stepEl.querySelector('.step-status');
            st.textContent = ' [OK]';
            st.classList.add('ok');
            stepEl.classList.remove('active');
            stepEl.classList.add('done');
        }

        function buildWave() {
            const width = Math.min(60, Math.floor((signalEl.offsetWidth || 400) / 9));
            let line1 = '', line2 = '';
            for (let i = 0; i < width; i++) {
                const v1 = Math.sin((waveOffset + i) * 0.25) * 0.4 +
                           Math.sin((waveOffset + i) * 0.6) * 0.3 +
                           Math.cos((waveOffset + i) * 0.15) * 0.2 +
                           Math.random() * 0.15;
                const v2 = Math.cos((waveOffset + i) * 0.2) * 0.35 +
                           Math.sin((waveOffset + i) * 0.45 + 2) * 0.35 +
                           Math.random() * 0.15;
                const i1 = Math.floor(Math.max(0, Math.min(7, (v1 + 0.5) * 7)));
                const i2 = Math.floor(Math.max(0, Math.min(7, (v2 + 0.5) * 7)));
                line1 += WAVE_CHARS[i1];
                line2 += WAVE_CHARS[i2];
            }
            waveOffset++;
            signalEl.textContent = 'SIG-A \u2502 ' + line1 + '\nSIG-B \u2502 ' + line2;
        }

        function tick() {
            const elapsed = performance.now() - start;
            const progress = Math.min(0.95, elapsed / totalMs);
            const pctVal = Math.round(progress * 100);

            barFill.style.width = pctVal + '%';
            pctEl.textContent = pctVal + '%';

            const expectedStep = steps.findIndex((s) => (s.pct / 100) > progress) - 1;
            const targetStep = expectedStep < 0 ? steps.length - 1 : expectedStep;

            while (currentStep < targetStep) {
                if (currentStep >= 0) {
                    completeStep(stepsEl.children[currentStep]);
                }
                currentStep++;
                addStep(steps[currentStep].text);
            }

            if (currentStep >= 0 && stepsEl.children[currentStep]) {
                const dotsEl = stepsEl.children[currentStep].querySelector('.step-dots');
                const dotPhase = Math.floor((elapsed % 1600) / 400);
                dotsEl.textContent = ' ' + '.'.repeat(dotPhase + 1);
            }

            buildWave();
        }

        tick();
        loadingTimer = setInterval(tick, 180);
    }

    function finishLoading() {
        if (loadingTimer) clearInterval(loadingTimer);
        if (waveTimer) clearInterval(waveTimer);
        loadingTimer = null;
        waveTimer = null;

        $('loadingBarFill').style.width = '100%';
        $('loadingPct').textContent = '100%';

        const stepsEl = $('loadingSteps');
        const last = stepsEl.lastElementChild;
        if (last && !last.classList.contains('done')) {
            last.querySelector('.step-dots').textContent = '';
            const st = last.querySelector('.step-status');
            st.textContent = ' [OK]';
            st.classList.add('ok');
            last.classList.remove('active');
            last.classList.add('done');
        }

        const done = document.createElement('div');
        done.className = 'step';
        done.innerHTML = '<span class="step-arrow">\u2714</span> <span class="step-text">complete</span>';
        stepsEl.appendChild(done);
    }

    // ---------- Brainstorm API ----------

    async function runBrainstorm() {
        clearError();
        const seed = $('seedInput').value.trim();
        if (!seed && state.attachments.length === 0) {
            showError('Enter an idea or attach a file first.');
            return;
        }
        const mode = (document.querySelector('input[name="mode"]:checked') || {}).value || 'quick';
        state.seed = seed;
        state.mode = mode;

        startLoading(mode);

        const fd = new FormData();
        fd.append('seed', seed);
        fd.append('mode', mode);
        state.attachments.forEach((a) => fd.append('attachments', a.file, a.name));

        try {
            const r = await fetch('/api/brainstorm', { method: 'POST', body: fd });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
                throw new Error(data.error || ('HTTP ' + r.status));
            }
            finishLoading();
            state.result = data;
            await new Promise((res) => setTimeout(res, 600));
            renderResults();
            showView('results');
        } catch (e) {
            finishLoading();
            await new Promise((res) => setTimeout(res, 300));
            showView('input');
            showError(String(e.message || e));
        }
    }

    // ---------- Render results ----------

    function renderResults() {
        const body = $('resultsBody');
        body.innerHTML = '';
        const r = state.result;
        if (!r) return;

        $('resultsMeta').textContent =
            (r.mode || state.mode).toUpperCase() + ' / ' + r.ideas.length + ' IDEAS';

        const winnerIdx = r.ideas.findIndex((x) => x.id === r.winner_id);
        const ordered = [];
        if (winnerIdx >= 0) ordered.push(r.ideas[winnerIdx]);
        r.ideas.forEach((it, i) => { if (i !== winnerIdx) ordered.push(it); });

        ordered.forEach((idea, displayIdx) => {
            const isWinner = idea.id === r.winner_id;
            body.appendChild(renderIdeaCard(idea, isWinner, displayIdx + 1, r.rationale));
        });
    }

    function renderIdeaCard(idea, isWinner, displayRank, rationale) {
        const card = document.createElement('article');
        card.className = 'idea-card' + (isWinner ? ' is-winner expanded' : '');
        card.dataset.ideaId = idea.id;

        const head = document.createElement('div');
        head.className = 'idea-card-head';
        head.innerHTML =
            '<div class="idea-rank">' + (isWinner ? '#1 \u2605' : '#' + displayRank) + '</div>' +
            '<div class="idea-head-text">' +
                '<h2 class="idea-title"></h2>' +
                '<p class="idea-tldr"></p>' +
            '</div>' +
            '<div class="idea-toggle">\u25b6</div>';
        head.querySelector('.idea-title').textContent = idea.title || '';
        head.querySelector('.idea-tldr').textContent = idea.tldr || '';
        head.addEventListener('click', () => card.classList.toggle('expanded'));
        card.appendChild(head);

        const body = document.createElement('div');
        body.className = 'idea-body';

        if (isWinner && rationale) {
            const rat = document.createElement('div');
            rat.className = 'idea-rationale';
            rat.textContent = '\u2605 Why this wins: ' + rationale;
            body.appendChild(rat);
        }

        const full = document.createElement('div');
        full.className = 'idea-full';
        full.textContent = idea.full || '';
        body.appendChild(full);

        const actions = document.createElement('div');
        actions.className = 'idea-actions';
        actions.innerHTML =
            '<button class="btn btn-ghost btn-enhance" data-act="enhance">[+] ENHANCE</button>' +
            '<button class="btn btn-ghost" data-act="feedback">[~] FEEDBACK</button>' +
            '<button class="btn btn-ghost" data-act="png">SAVE PNG</button>' +
            '<button class="btn btn-ghost" data-act="pdf">SAVE PDF</button>' +
            '<button class="btn btn-ghost" data-act="share">SHARE</button>';
        body.appendChild(actions);

        const fb = document.createElement('div');
        fb.className = 'idea-feedback';
        fb.innerHTML =
            '<textarea placeholder="What would you change? More edge, different audience, new constraint..." rows="3"></textarea>' +
            '<div class="feedback-actions">' +
              '<button class="btn btn-primary" data-act="refine-one">REFINE THIS ONE</button>' +
              '<button class="btn" data-act="rebrainstorm">BRAINSTORM AGAIN</button>' +
              '<button class="btn btn-ghost" data-act="cancel-feedback">CANCEL</button>' +
            '</div>' +
            '<div class="idea-status"></div>';
        body.appendChild(fb);

        card.appendChild(body);

        actions.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-act]');
            if (!btn) return;
            const act = btn.dataset.act;
            if (act === 'enhance') enhanceIdea(card, idea, btn);
            else if (act === 'feedback') { fb.classList.toggle('open'); fb.querySelector('textarea').focus(); }
            else if (act === 'png') saveAsPng(card, idea);
            else if (act === 'pdf') saveAsPdf(card, idea);
            else if (act === 'share') shareIdea(idea);
        });

        fb.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-act]');
            if (!btn) return;
            const act = btn.dataset.act;
            const status = fb.querySelector('.idea-status');
            const fbText = fb.querySelector('textarea').value.trim();

            if (act === 'cancel-feedback') {
                fb.classList.remove('open');
                fb.querySelector('textarea').value = '';
                status.textContent = '';
                status.classList.remove('error');
                return;
            }
            if (!fbText) {
                status.textContent = 'enter feedback first.';
                status.classList.add('error');
                return;
            }
            if (act === 'refine-one') refineSingleIdea(card, idea, fbText, status);
            else if (act === 'rebrainstorm') rebrainstormWithFeedback(idea, fbText, status);
        });

        return card;
    }

    // ---------- Enhance Idea (one-click) ----------

    async function enhanceIdea(card, idea, btn) {
        const origText = btn.innerHTML;
        btn.innerHTML = 'ENHANCING...';
        btn.disabled = true;
        btn.style.opacity = '0.6';

        const feedback =
            'Enhance this idea. Make the hook sharper and more memorable. ' +
            'Add a specific, concrete first step someone could take today. ' +
            'Make it more original — push it further from obvious. ' +
            'Be more honest and specific about the biggest risk. ' +
            'Keep the core direction but elevate it.';

        try {
            const r = await fetch('/api/refine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ idea: idea, feedback: feedback, seed: state.seed }),
            });
            const data = await r.json();
            if (!r.ok || !data.ok) throw new Error(data.error || ('HTTP ' + r.status));

            const idx = state.result.ideas.findIndex((x) => x.id === idea.id);
            if (idx >= 0) state.result.ideas[idx] = data.idea;

            const isWinner = state.result.winner_id === data.idea.id;
            const rank = idx >= 0 ? idx + 1 : 1;
            const fresh = renderIdeaCard(data.idea, isWinner, rank, state.result.rationale);
            fresh.classList.add('expanded');

            const titleEl = fresh.querySelector('.idea-title');
            if (titleEl) {
                const badge = document.createElement('span');
                badge.className = 'enhanced-badge';
                badge.textContent = 'ENHANCED';
                titleEl.appendChild(badge);
            }

            card.replaceWith(fresh);
        } catch (e) {
            btn.innerHTML = origText;
            btn.disabled = false;
            btn.style.opacity = '';
            const status = card.querySelector('.idea-status');
            if (status) {
                status.classList.add('error');
                status.textContent = '! ' + (e.message || e);
            }
        }
    }

    // ---------- Refine + re-brainstorm ----------

    async function refineSingleIdea(card, idea, feedback, statusEl) {
        statusEl.classList.remove('error');
        statusEl.textContent = 'refining...';
        try {
            const r = await fetch('/api/refine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ idea: idea, feedback: feedback, seed: state.seed }),
            });
            const data = await r.json();
            if (!r.ok || !data.ok) throw new Error(data.error || ('HTTP ' + r.status));
            const idx = state.result.ideas.findIndex((x) => x.id === idea.id);
            if (idx >= 0) state.result.ideas[idx] = data.idea;
            const isWinner = state.result.winner_id === data.idea.id;
            const rank = idx >= 0 ? idx + 1 : 1;
            const fresh = renderIdeaCard(data.idea, isWinner, rank, state.result.rationale);
            fresh.classList.add('expanded');
            card.replaceWith(fresh);
        } catch (e) {
            statusEl.classList.add('error');
            statusEl.textContent = '! ' + (e.message || e);
        }
    }

    async function rebrainstormWithFeedback(idea, feedback, statusEl) {
        statusEl.classList.remove('error');
        statusEl.textContent = 'rebooting brainstorm...';
        const newSeed =
            state.seed +
            '\n\n--- PRIOR DIRECTION ---\n' +
            (idea.title || '') + ' \u2014 ' + (idea.tldr || '') +
            '\n\n--- USER FEEDBACK ON THAT ---\n' + feedback +
            '\n\nIncorporate this feedback into a fresh brainstorm.';
        $('seedInput').value = newSeed;
        await runBrainstorm();
    }

    // ---------- Export ----------

    async function withTempExpanded(card, fn) {
        const wasExpanded = card.classList.contains('expanded');
        card.classList.add('expanded');
        const actions = card.querySelector('.idea-actions');
        const fb = card.querySelector('.idea-feedback');
        const oldDisplay = actions ? actions.style.display : '';
        const oldFbDisplay = fb ? fb.style.display : '';
        if (actions) actions.style.display = 'none';
        if (fb) fb.style.display = 'none';
        try {
            return await fn();
        } finally {
            if (actions) actions.style.display = oldDisplay;
            if (fb) fb.style.display = oldFbDisplay;
            if (!wasExpanded) card.classList.remove('expanded');
        }
    }

    async function saveAsPng(card, idea) {
        if (typeof html2canvas === 'undefined') {
            alert('PNG export not loaded yet, try again in a moment.');
            return;
        }
        await withTempExpanded(card, async () => {
            const canvas = await html2canvas(card, {
                backgroundColor: '#111d35',
                scale: 2,
                useCORS: true,
            });
            const url = canvas.toDataURL('image/png');
            triggerDownload(url, slugify(idea.title) + '.png');
        });
    }

    async function saveAsPdf(card, idea) {
        if (typeof html2canvas === 'undefined' || typeof window.jspdf === 'undefined') {
            alert('PDF export not loaded yet, try again in a moment.');
            return;
        }
        await withTempExpanded(card, async () => {
            const canvas = await html2canvas(card, { backgroundColor: '#111d35', scale: 2, useCORS: true });
            const img = canvas.toDataURL('image/png');
            const { jsPDF } = window.jspdf;
            const pdf = new jsPDF({ orientation: 'p', unit: 'pt', format: 'letter' });
            const pageW = pdf.internal.pageSize.getWidth();
            const pageH = pdf.internal.pageSize.getHeight();
            const imgW = pageW - 40;
            const imgH = (canvas.height * imgW) / canvas.width;
            let y = 20;
            if (imgH <= pageH - 40) {
                pdf.addImage(img, 'PNG', 20, y, imgW, imgH);
            } else {
                let remainingH = imgH;
                let sy = 0;
                const sliceH = pageH - 40;
                while (remainingH > 0) {
                    const slice = document.createElement('canvas');
                    const sliceCanvasH = Math.min(sliceH * (canvas.width / imgW), canvas.height - sy);
                    slice.width = canvas.width;
                    slice.height = sliceCanvasH;
                    slice.getContext('2d').drawImage(
                        canvas, 0, sy, canvas.width, sliceCanvasH,
                        0, 0, canvas.width, sliceCanvasH
                    );
                    const sImg = slice.toDataURL('image/png');
                    const sH = (sliceCanvasH * imgW) / canvas.width;
                    pdf.addImage(sImg, 'PNG', 20, 20, imgW, sH);
                    sy += sliceCanvasH;
                    remainingH -= sH;
                    if (remainingH > 0) pdf.addPage();
                }
            }
            pdf.save(slugify(idea.title) + '.pdf');
        });
    }

    async function shareIdea(idea) {
        const text =
            'THE IDEA GRAVEYARD \u2014 ' + (idea.title || '') + '\n\n' +
            (idea.tldr || '') + '\n\n' + (idea.full || '');
        if (navigator.share) {
            try {
                await navigator.share({ title: idea.title || 'The Idea Graveyard', text: text });
                return;
            } catch (_) { /* user canceled */ }
        }
        try {
            await navigator.clipboard.writeText(text);
            alert('Copied to clipboard.');
        } catch (_) {
            alert('Copy failed. Long-press the text to copy manually.');
        }
    }

    function slugify(s) {
        return (s || 'idea')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-|-$/g, '')
            .slice(0, 60) || 'idea';
    }

    function triggerDownload(href, filename) {
        const a = document.createElement('a');
        a.href = href;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    // ---------- Wire up ----------

    document.addEventListener('DOMContentLoaded', () => {
        $('attachInput').addEventListener('change', (e) => {
            handleFiles(e.target.files);
            e.target.value = '';
        });
        $('generateBtn').addEventListener('click', runBrainstorm);
        $('backBtn').addEventListener('click', () => {
            showView('input');
            clearError();
        });
        document.querySelectorAll('input[name="mode"]').forEach((el) => {
            el.addEventListener('change', () => {
                document.querySelectorAll('.mode-pill').forEach((p) => {
                    p.classList.toggle('mode-pill-active', p.querySelector('input').checked);
                });
            });
        });
        $('seedInput').addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                runBrainstorm();
            }
        });
        setupVoice();
    });
})();
