(function () {
  'use strict';

  // Thresholds copied from the Thresholds defaults in src/aidelivery/gate.py,
  // which match config/thresholds.json. Keep them in sync (a test checks this).
  var T = {
    max_p95_latency_seconds: 2.0,
    max_error_rate: 0.02,
    max_cost_per_1k_tokens: 0.01,
    min_eval_score: 0.85,
    max_hallucination_rate: 0.05,
    min_requests: 20
  };
  // Held at the values of tests/fixtures/canary_good.prom and eval_good.json.
  var FIXED = { requests: 100, hallucination: 0.02 };

  // Values the Python gate computes from tests/fixtures/ (see site-tests/gate_cases.py).
  var PRESETS = {
    healthy: { err: 0, p95: 0.375, cost: 0.002, eval: 0.93 },
    slow: { err: 0, p95: 4.625, cost: 0.002, eval: 0.93 },
    errors: { err: 0.2, p95: 0.375, cost: 0.002, eval: 0.93 },
    costly: { err: 0, p95: 0.375, cost: 0.05, eval: 0.93 },
    badeval: { err: 0, p95: 0.375, cost: 0.002, eval: 0.7 }
  };

  function g(n) { return String(Number(n)); }
  function p6(n) { return String(Number(Number(n).toPrecision(6))); }

  // Mirrors evaluate() in gate.py: every check must pass to promote.
  function evaluate(v) {
    var checks = [
      { name: 'request_volume', value: FIXED.requests, limit: T.min_requests, op: '>=', ok: FIXED.requests >= T.min_requests },
      { name: 'p95_latency_seconds', value: v.p95, limit: T.max_p95_latency_seconds, op: '<=', ok: v.p95 <= T.max_p95_latency_seconds },
      { name: 'error_rate', value: v.err, limit: T.max_error_rate, op: '<=', ok: v.err <= T.max_error_rate },
      { name: 'cost_per_1k_tokens_usd', value: v.cost, limit: T.max_cost_per_1k_tokens, op: '<=', ok: v.cost <= T.max_cost_per_1k_tokens },
      { name: 'eval_score', value: v.eval, limit: T.min_eval_score, op: '>=', ok: v.eval >= T.min_eval_score },
      { name: 'hallucination_rate', value: FIXED.hallucination, limit: T.max_hallucination_rate, op: '<=', ok: FIXED.hallucination <= T.max_hallucination_rate }
    ];
    var promote = checks.every(function (c) { return c.ok; });
    return { promote: promote, checks: checks };
  }
  window.aideliveryGate = { thresholds: T, evaluate: evaluate };

  var demo = document.getElementById('demo');
  if (demo) {
    var inputs = {};
    [].forEach.call(demo.querySelectorAll('input[type=range]'), function (el) { inputs[el.dataset.key] = el; });
    var outs = { err: 'o-err', p95: 'o-p95', cost: 'o-cost', eval: 'o-eval' };
    var failKey = { error_rate: 'err', p95_latency_seconds: 'p95', cost_per_1k_tokens_usd: 'cost', eval_score: 'eval' };
    var fmt = {
      err: function (n) { return (n * 100).toFixed(1) + '%'; },
      p95: function (n) { return n.toFixed(3) + ' s'; },
      cost: function (n) { return '$' + n.toFixed(4); },
      eval: function (n) { return n.toFixed(2); }
    };
    var unitText = {
      err: function (n) { return (n * 100).toFixed(1) + ' percent'; },
      p95: function (n) { return n.toFixed(3) + ' seconds'; },
      cost: function (n) { return n.toFixed(4) + ' dollars'; },
      eval: function (n) { return n.toFixed(2); }
    };
    var verdict = document.getElementById('verdict');
    var exitEl = document.getElementById('exitcode');
    var reasons = document.getElementById('reasons');
    var list = document.getElementById('checks');
    var live = document.getElementById('live');

    function read() {
      return {
        err: parseFloat(inputs.err.value),
        p95: parseFloat(inputs.p95.value),
        cost: parseFloat(inputs.cost.value),
        eval: parseFloat(inputs.eval.value)
      };
    }

    function render() {
      var v = read();
      var d = evaluate(v);
      var failed = d.checks.filter(function (c) { return !c.ok; });
      var badKeys = {};
      failed.forEach(function (c) { if (failKey[c.name]) badKeys[failKey[c.name]] = true; });
      Object.keys(outs).forEach(function (k) {
        var o = document.getElementById(outs[k]);
        o.textContent = fmt[k](v[k]);
        o.className = badKeys[k] ? 'bad' : 'ok';
        inputs[k].setAttribute('aria-valuetext', unitText[k](v[k]) + (badKeys[k] ? ', fails the gate' : ', within the gate'));
      });
      verdict.textContent = d.promote ? 'PROMOTE' : 'ROLLBACK';
      verdict.className = 'big ' + (d.promote ? 'promote' : 'rollback');
      exitEl.textContent = 'exit ' + (d.promote ? 0 : 1);
      var text = d.promote
        ? 'All six checks pass.'
        : failed.length + (failed.length === 1 ? ' check fails: ' : ' checks fail: ') +
          failed.map(function (c) { return c.name + ' is ' + p6(c.value) + ', need ' + c.op + ' ' + g(c.limit); }).join('; ') + '.';
      reasons.textContent = text;
      list.innerHTML = '';
      d.checks.forEach(function (c) {
        var li = document.createElement('li');
        if (!c.ok) li.className = 'f';
        var s = document.createElement('span');
        s.className = 's ' + (c.ok ? 'p' : 'f');
        s.textContent = c.ok ? 'PASS' : 'FAIL';
        var t = document.createElement('span');
        t.textContent = c.name + ': ' + p6(c.value) + ' (need ' + c.op + ' ' + g(c.limit) + ')';
        li.appendChild(s); li.appendChild(t); list.appendChild(li);
      });
      live.textContent = 'Decision: ' + verdict.textContent + '. ' + text;
      [].forEach.call(demo.querySelectorAll('[data-preset]'), function (b) {
        var p = PRESETS[b.dataset.preset];
        b.setAttribute('aria-pressed', String(Object.keys(p).every(function (k) { return p[k] === v[k]; })));
      });
    }

    Object.keys(inputs).forEach(function (k) { inputs[k].addEventListener('input', render); });
    [].forEach.call(demo.querySelectorAll('[data-preset]'), function (b) {
      b.addEventListener('click', function () {
        var p = PRESETS[b.dataset.preset];
        Object.keys(p).forEach(function (k) { inputs[k].value = String(p[k]); });
        render();
      });
    });
    render();
  }

  // Copy buttons
  var status = document.getElementById('copy-status');
  function say(msg) { if (status) status.textContent = msg; }
  function fallbackCopy(el) {
    try {
      var r = document.createRange(); r.selectNodeContents(el);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      return document.execCommand && document.execCommand('copy');
    } catch (e) { return false; }
  }
  [].forEach.call(document.querySelectorAll('[data-copy-target]'), function (btn) {
    btn.addEventListener('click', function () {
      var el = document.getElementById(btn.dataset.copyTarget);
      var text = el.innerText.replace(/\s+$/, '');
      function done() { btn.textContent = 'Copied'; say('Command copied.'); setTimeout(function () { btn.textContent = 'Copy'; }, 2000); }
      function failed() {
        btn.textContent = 'Select and copy';
        say('Copy is not available here. The command is selected, press Ctrl or Command C.');
        setTimeout(function () { btn.textContent = 'Copy'; }, 4000);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(el) ? done() : failed(); });
      } else if (fallbackCopy(el)) { done(); } else { failed(); }
    });
  });

  // Scroll reveal and progress bar (skipped when reduced motion is requested)
  var root = document.documentElement;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduce) {
    var items = document.querySelectorAll('.reveal');
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
      }, { threshold: 0.08, rootMargin: '0px 0px -5% 0px' });
      [].forEach.call(items, function (el) { io.observe(el); });
    } else {
      [].forEach.call(items, function (el) { el.classList.add('in'); });
    }
    var bar = document.querySelector('.progress');
    var ticking = false;
    function update() {
      var h = root.scrollHeight - window.innerHeight;
      bar.style.transform = 'scaleX(' + (h > 0 ? Math.min(1, window.scrollY / h) : 0) + ')';
      ticking = false;
    }
    window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    update();
  }
  root.setAttribute('data-ready', '');
})();
