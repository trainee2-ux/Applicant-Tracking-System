/* global fetch */
(function (global) {
  "use strict";

  const DEFAULTS = {
    sessionToken: "",
    maxWarnings: 3,
    enableWebcam: true,
    enableFullscreen: true,
    formSelector: "form",
    snapshotIntervalMs: 15000,
    devtoolsCheckIntervalMs: 1500,
    voiceCheckIntervalMs: 1200,
    voiceRmsThreshold: 0.18,
    multiTab: true,
    endpoints: {
      violation: "/proctoring/violation/",
      snapshot: "/proctoring/snapshot/",
      complete: "/proctoring/complete/",
    },
  };

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function safeJson(res) {
    return res.json().catch(() => ({}));
  }

  function nowIso() {
    try {
      return new Date().toISOString();
    } catch (_) {
      return "";
    }
  }

  function clamp(n, min, max) {
    const v = Number(n);
    if (Number.isNaN(v)) return min;
    return Math.min(max, Math.max(min, v));
  }

  function createOverlay(message) {
    const el = document.createElement("div");
    el.id = "aankhOverlay";
    el.style.cssText =
      "position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.65);display:flex;align-items:center;justify-content:center;padding:24px;";
    const card = document.createElement("div");
    card.style.cssText =
      "max-width:720px;width:100%;background:var(--surface,#ffffff);border:1px solid var(--border, rgba(0,0,0,0.12));border-radius:18px;padding:22px 22px 18px;color:var(--text,#0f172a);box-shadow:0 20px 60px rgba(0,0,0,0.35);";
    const title = document.createElement("div");
    title.style.cssText = "font-weight:900;font-size:16px;margin-bottom:8px;letter-spacing:0.2px;color:var(--text,#0f172a);";
    title.textContent = "Proctoring Alert";
    const body = document.createElement("div");
    body.id = "aankhOverlayBody";
    body.style.cssText = "color:var(--text2,#334155);font-size:13px;line-height:1.6;margin-bottom:14px;";
    body.textContent = message;
    const note = document.createElement("div");
    note.style.cssText = "color:var(--text3,#64748b);font-size:12px;line-height:1.6;";
    note.textContent = "Please return to the assessment tab and follow the on-screen instructions.";
    card.appendChild(title);
    card.appendChild(body);
    card.appendChild(note);
    el.appendChild(card);
    return el;
  }

  class AankhProctor {
    constructor(options) {
      this.options = Object.assign({}, DEFAULTS, options || {});
      this.options.maxWarnings = clamp(this.options.maxWarnings, 1, 50);
      this.sessionToken = String(this.options.sessionToken || "").trim();

      this._running = false;
      this._terminated = false;
      this._overlay = null;
      this._overlayHideTimer = null;
      this._form = null;

      this._videoStream = null;
      this._audioStream = null;
      this._videoEl = null;
      this._canvasEl = null;
      this._audioCtx = null;
      this._analyser = null;
      this._voiceLastViolationAt = 0;
      this._devtoolsOpen = false;
      this._lastViolationAt = {};
      this._channel = null;
      this._tabId = Math.random().toString(16).slice(2);

      this._onVisibility = this._onVisibility.bind(this);
      this._onBlur = this._onBlur.bind(this);
      this._onFullscreenChange = this._onFullscreenChange.bind(this);
      this._onContextMenu = this._onContextMenu.bind(this);
      this._onCopy = this._onCopy.bind(this);
      this._onPaste = this._onPaste.bind(this);
      this._onKeydown = this._onKeydown.bind(this);
      this._onSubmit = this._onSubmit.bind(this);
    }

    async start() {
      if (!this.sessionToken) return;
      if (this._running) return;
      this._running = true;

      this._form = document.querySelector(this.options.formSelector) || null;
      if (this._form) this._form.addEventListener("submit", this._onSubmit, { capture: true });

      document.addEventListener("visibilitychange", this._onVisibility);
      window.addEventListener("blur", this._onBlur);
      document.addEventListener("fullscreenchange", this._onFullscreenChange);
      document.addEventListener("contextmenu", this._onContextMenu);
      document.addEventListener("copy", this._onCopy);
      document.addEventListener("paste", this._onPaste);
      document.addEventListener("cut", this._onCopy);
      document.addEventListener("keydown", this._onKeydown);

      if (this.options.multiTab) this._setupMultiTab();

      if (this.options.enableFullscreen) {
        await this._ensureFullscreen();
      }

      if (this.options.enableWebcam) {
        await this._startWebcam();
        await this._startMic();
      }

      this._loopDevtools();
      this._loopSnapshots();
      this._loopVoice();
    }

    stop() {
      this._running = false;

      document.removeEventListener("visibilitychange", this._onVisibility);
      window.removeEventListener("blur", this._onBlur);
      document.removeEventListener("fullscreenchange", this._onFullscreenChange);
      document.removeEventListener("contextmenu", this._onContextMenu);
      document.removeEventListener("copy", this._onCopy);
      document.removeEventListener("paste", this._onPaste);
      document.removeEventListener("cut", this._onCopy);
      document.removeEventListener("keydown", this._onKeydown);

      if (this._form) this._form.removeEventListener("submit", this._onSubmit, { capture: true });

      this._teardownMedia();
      if (this._channel) {
        try {
          this._channel.close();
        } catch (_) {}
        this._channel = null;
      }
    }

    async _ensureFullscreen() {
      if (!document.documentElement.requestFullscreen) return;
      if (document.fullscreenElement) return;
      try {
        await document.documentElement.requestFullscreen();
      } catch (_) {
        // If user blocked fullscreen, log once and continue.
        this._logViolation("fullscreen_exit", { reason: "fullscreen_request_failed" });
      }
    }

    async _startWebcam() {
      try {
        this._videoStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        const v = document.createElement("video");
        v.setAttribute("playsinline", "");
        v.muted = true;
        v.autoplay = true;
        v.srcObject = this._videoStream;
        this._videoEl = v;

        const c = document.createElement("canvas");
        c.width = 640;
        c.height = 480;
        this._canvasEl = c;
      } catch (_) {
        this._videoStream = null;
        this._videoEl = null;
        this._canvasEl = null;
        this._logViolation("no_face", { reason: "webcam_permission_denied" });
      }
    }

    async _startMic() {
      try {
        this._audioStream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const ctx = new AudioContext();
        const source = ctx.createMediaStreamSource(this._audioStream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        this._audioCtx = ctx;
        this._analyser = analyser;
      } catch (_) {
        this._audioStream = null;
        this._audioCtx = null;
        this._analyser = null;
      }
    }

    _teardownMedia() {
      const stopTracks = (stream) => {
        try {
          if (stream && stream.getTracks) stream.getTracks().forEach((t) => t.stop());
        } catch (_) {}
      };
      stopTracks(this._videoStream);
      stopTracks(this._audioStream);
      this._videoStream = null;
      this._audioStream = null;
      this._videoEl = null;
      this._canvasEl = null;
      try {
        if (this._audioCtx) this._audioCtx.close();
      } catch (_) {}
      this._audioCtx = null;
      this._analyser = null;
    }

    _setupMultiTab() {
      try {
        const channel = new BroadcastChannel("aankh:" + this.sessionToken);
        this._channel = channel;
        channel.onmessage = (evt) => {
          const msg = evt && evt.data ? evt.data : {};
          if (!msg || msg.type !== "hello") return;
          if (msg.tabId && msg.tabId !== this._tabId) {
            this._logViolation("tab_switch", { reason: "multiple_tabs", otherTab: msg.tabId });
          }
        };
        channel.postMessage({ type: "hello", tabId: this._tabId, ts: nowIso() });
      } catch (_) {
        // ignore
      }
    }

    _shouldThrottle(type, minMs) {
      const now = Date.now();
      const last = this._lastViolationAt[type] || 0;
      if (now - last < minMs) return true;
      this._lastViolationAt[type] = now;
      return false;
    }

    async _logViolation(type, meta) {
      if (!this._running || this._terminated) return;
      if (this._shouldThrottle(type, 1200)) return;
      try {
        const res = await fetch(this.options.endpoints.violation, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_token: this.sessionToken,
            violation_type: type,
            meta: meta && typeof meta === "object" ? meta : {},
          }),
        });
        const payload = await safeJson(res);
        this._showViolationAlert(type, payload);
        if (payload && payload.terminated) this._handleTerminated(payload);
      } catch (_) {
        // ignore
      }
    }

    _violationMessage(type) {
      const map = {
        tab_switch: "Tab switch detected. Stay on the assessment page.",
        fullscreen_exit: "Fullscreen exited. Fullscreen is required during the assessment.",
        devtools_open: "Developer Tools detected. Please close DevTools.",
        copy_paste: "Copy/Paste attempt detected. This activity is not allowed.",
        right_click: "Right-click detected. This activity is not allowed.",
        multiple_faces: "Multiple faces detected on camera. Only one person is allowed.",
        no_face: "No face detected. Please keep your face visible to the camera.",
        unknown: "Suspicious activity detected. Please continue the assessment fairly.",
      };
      return map[type] || "Proctoring policy violation detected.";
    }

    _showViolationAlert(type, payload) {
      if (this._terminated) return;
      const warnings = payload && typeof payload.warnings_count === "number" ? payload.warnings_count : null;
      const max = payload && typeof payload.max_warnings === "number" ? payload.max_warnings : this.options.maxWarnings;
      const remaining = warnings !== null ? Math.max(0, max - warnings) : null;
      const base = this._violationMessage(type);
      const tail =
        remaining === null
          ? ""
          : remaining === 0
            ? " This was your final warning."
            : ` Warnings left: ${remaining}.`;
      const msg = base + tail;

      if (!this._overlay) {
        this._overlay = createOverlay(msg);
        document.body.appendChild(this._overlay);
      } else {
        const body = this._overlay.querySelector("#aankhOverlayBody");
        if (body) body.textContent = msg;
      }

      // Auto-hide warnings (keep overlay for termination).
      if (!(payload && payload.terminated)) {
        clearTimeout(this._overlayHideTimer);
        this._overlayHideTimer = setTimeout(() => {
          try {
            if (this._overlay && this._overlay.parentNode) this._overlay.parentNode.removeChild(this._overlay);
          } catch (_) {}
          this._overlay = null;
        }, 3500);
      }
    }

    _handleTerminated(payload) {
      this._terminated = true;
      const msg =
        "This session has been terminated due to repeated policy violations. You will not be able to submit this assessment.";
      if (!this._overlay) {
        this._overlay = createOverlay(msg);
        document.body.appendChild(this._overlay);
      } else {
        const body = this._overlay.querySelector("#aankhOverlayBody");
        if (body) body.textContent = msg;
      }
      try {
        if (this._form) {
          this._form.querySelectorAll("input,select,textarea,button").forEach((el) => {
            el.disabled = true;
          });
        }
      } catch (_) {}
      this._teardownMedia();
    }

    async _sendSnapshot(imageData) {
      if (!imageData) return;
      if (!this._running || this._terminated) return;
      try {
        const res = await fetch(this.options.endpoints.snapshot, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_token: this.sessionToken,
            image_data: imageData,
          }),
        });
        const payload = await safeJson(res);
        if (payload && payload.terminated) this._handleTerminated(payload);
      } catch (_) {
        // ignore
      }
    }

    async _captureJpegBase64() {
      if (!this._videoEl || !this._canvasEl) return "";
      const video = this._videoEl;
      const canvas = this._canvasEl;
      const w = video.videoWidth || 640;
      const h = video.videoHeight || 480;
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, w, h);
      try {
        return canvas.toDataURL("image/jpeg", 0.7);
      } catch (_) {
        return "";
      }
    }

    async _detectFaces() {
      if (!this._videoEl) return -1;
      const FaceDetector = global.FaceDetector;
      if (!FaceDetector) return -1;
      try {
        const detector = new FaceDetector({ fastMode: true, maxDetectedFaces: 5 });
        const faces = await detector.detect(this._videoEl);
        return Array.isArray(faces) ? faces.length : -1;
      } catch (_) {
        return -1;
      }
    }

    async _loopSnapshots() {
      while (this._running && !this._terminated) {
        if (this.options.enableWebcam && this._videoEl) {
          const faceCount = await this._detectFaces();
          if (faceCount === 0) this._logViolation("no_face", { face_count: 0 });
          if (faceCount > 1) this._logViolation("multiple_faces", { face_count: faceCount });
          const img = await this._captureJpegBase64();
          await this._sendSnapshot(img);
        }
        await sleep(this.options.snapshotIntervalMs);
      }
    }

    _isDevtoolsOpen() {
      // Heuristic: detect significant chrome difference OR debugger timing.
      const threshold = 160;
      const w = Math.abs((window.outerWidth || 0) - (window.innerWidth || 0));
      const h = Math.abs((window.outerHeight || 0) - (window.innerHeight || 0));
      return w > threshold || h > threshold;
    }

    async _loopDevtools() {
      while (this._running && !this._terminated) {
        const open = this._isDevtoolsOpen();
        if (open && !this._devtoolsOpen) {
          this._devtoolsOpen = true;
          this._logViolation("devtools_open", { reason: "heuristic" });
        }
        if (!open) this._devtoolsOpen = false;
        await sleep(this.options.devtoolsCheckIntervalMs);
      }
    }

    _computeRms() {
      if (!this._analyser) return 0;
      const buf = new Uint8Array(this._analyser.fftSize);
      this._analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        sum += v * v;
      }
      return Math.sqrt(sum / buf.length);
    }

    async _loopVoice() {
      while (this._running && !this._terminated) {
        if (this.options.enableWebcam && this._analyser) {
          const rms = this._computeRms();
          if (rms > this.options.voiceRmsThreshold) {
            // Map voice detection into known types (unknown is too noisy). Use right_click? No.
            // If server has "unknown" only, this will become unknown. We'll keep it explicit for easier extension.
            this._logViolation("unknown", { reason: "voice_detected", rms: Number(rms.toFixed(3)) });
          }
        }
        await sleep(this.options.voiceCheckIntervalMs);
      }
    }

    _onVisibility() {
      if (document.visibilityState === "hidden") {
        this._logViolation("tab_switch", { event: "visibilitychange", state: "hidden" });
      }
    }

    _onBlur() {
      this._logViolation("tab_switch", { event: "blur" });
    }

    _onFullscreenChange() {
      if (!this.options.enableFullscreen) return;
      if (!document.fullscreenElement) {
        this._logViolation("fullscreen_exit", { event: "fullscreenchange" });
        this._ensureFullscreen();
      }
    }

    _onContextMenu(e) {
      try {
        e.preventDefault();
      } catch (_) {}
      this._logViolation("right_click", { event: "contextmenu" });
    }

    _onCopy(e) {
      try {
        e.preventDefault();
      } catch (_) {}
      this._logViolation("copy_paste", { event: e && e.type ? e.type : "copy" });
    }

    _onPaste(e) {
      try {
        e.preventDefault();
      } catch (_) {}
      this._logViolation("copy_paste", { event: "paste" });
    }

    _onKeydown(e) {
      // Prevent common shortcuts for copy/paste/devtools
      const key = (e && e.key ? String(e.key) : "").toLowerCase();
      const ctrl = !!(e && (e.ctrlKey || e.metaKey));
      if (ctrl && (key === "c" || key === "v" || key === "x")) {
        try {
          e.preventDefault();
        } catch (_) {}
        this._logViolation("copy_paste", { event: "keydown", key: key });
      }
      if (key === "f12" || (ctrl && e.shiftKey && key === "i") || (ctrl && e.shiftKey && key === "j")) {
        try {
          e.preventDefault();
        } catch (_) {}
        this._logViolation("devtools_open", { event: "keydown", key: key });
      }
    }

    async _onSubmit(e) {
      if (this._terminated) {
        try {
          e.preventDefault();
          e.stopPropagation();
        } catch (_) {}
        return;
      }
      // Mark completed server-side (best-effort).
      try {
        await fetch(this.options.endpoints.complete, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_token: this.sessionToken }),
        });
      } catch (_) {}
      // Let submission proceed.
    }
  }

  global.AankhProctor = AankhProctor;
})(window);
