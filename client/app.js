/**
 * app.js — Logika utama frontend Remote PC Control.
 * Menangani: login, koneksi WebSocket, render frame, dan forward input.
 */

// ─── Konfigurasi ─────────────────────────────────────────────────────────────

// Deteksi URL server secara otomatis dari lokasi halaman ini diakses
const SERVER_ORIGIN = window.location.origin;
const WS_ORIGIN = SERVER_ORIGIN.replace(/^http/, "ws");

const API_LOGIN = `${SERVER_ORIGIN}/auth/login`;
const WS_CLIENT = `${WS_ORIGIN}/ws/client`;

// ─── Elemen DOM ───────────────────────────────────────────────────────────────

const screenLogin  = document.getElementById("screen-login");
const screenViewer = document.getElementById("screen-viewer");
const formLogin    = document.getElementById("form-login");
const inputPwd     = document.getElementById("input-password");
const btnLogin     = document.getElementById("btn-login");
const btnText      = btnLogin.querySelector(".btn-text");
const btnSpinner   = btnLogin.querySelector(".btn-spinner");
const loginError   = document.getElementById("login-error");

const canvas        = document.getElementById("canvas-screen");
const ctx           = canvas.getContext("2d");
const viewerArea    = document.getElementById("viewer-area");
const overlayOffline = document.getElementById("overlay-offline");
const overlayLoading = document.getElementById("overlay-loading");

const statusDot   = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const infoFps     = document.getElementById("info-fps");
const infoPing    = document.getElementById("info-ping");
const infoRes     = document.getElementById("info-res");

const btnFullscreen = document.getElementById("btn-fullscreen");
const btnLogout     = document.getElementById("btn-logout");
const toggleInput   = document.getElementById("toggle-input");
const hotkeys       = document.querySelectorAll(".hotkey-btn");

// ─── State aplikasi ───────────────────────────────────────────────────────────

let ws = null;
let jwtToken = sessionStorage.getItem("jwt_token") || null;
let agentConnected = false;
let inputEnabled = true;

// Ukuran layar agent (untuk scaling koordinat mouse)
let remoteWidth  = 1920;
let remoteHeight = 1080;

// Metrik FPS
let frameCount = 0;
let lastFpsTime = performance.now();
let lastPingTime = 0;

// ─── Login ────────────────────────────────────────────────────────────────────

/**
 * Menangani submit form login.
 * Mengirim password ke server, menyimpan JWT, lalu membuka koneksi WebSocket.
 */
formLogin.addEventListener("submit", async (e) => {
  e.preventDefault();
  setLoginLoading(true);
  tampilError("");

  try {
    const res = await fetch(API_LOGIN, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: inputPwd.value }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Password salah");
    }

    const data = await res.json();
    jwtToken = data.access_token;
    sessionStorage.setItem("jwt_token", jwtToken);

    tampilViewer();
    hubungkanWebSocket();

  } catch (err) {
    tampilError(err.message);
  } finally {
    setLoginLoading(false);
  }
});

function setLoginLoading(aktif) {
  btnLogin.disabled = aktif;
  btnText.hidden = aktif;
  btnSpinner.hidden = !aktif;
}

function tampilError(pesan) {
  loginError.textContent = pesan;
  loginError.hidden = !pesan;
}

// ─── Navigasi layar ───────────────────────────────────────────────────────────

function tampilViewer() {
  screenLogin.classList.remove("active");
  screenViewer.classList.add("active");
}

function tampilLogin() {
  screenViewer.classList.remove("active");
  screenLogin.classList.add("active");
  inputPwd.value = "";
}

// ─── WebSocket ────────────────────────────────────────────────────────────────

/**
 * Membuka koneksi WebSocket ke server dengan JWT sebagai query parameter.
 * Menangani reconnect otomatis jika koneksi terputus.
 */
function hubungkanWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  updateStatus("connecting");
  const url = `${WS_CLIENT}?token=${encodeURIComponent(jwtToken)}`;
  ws = new WebSocket(url);

  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    updateStatus("connected");
    mulaiFpsCounter();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handlePesan(data);
    } catch {
      // bukan JSON, abaikan
    }
  };

  ws.onclose = (event) => {
    // Kode 4001 = token tidak valid, jangan reconnect
    if (event.code === 4001) {
      sessionStorage.removeItem("jwt_token");
      jwtToken = null;
      tampilLogin();
      return;
    }
    updateStatus("disconnected");
    setTimeout(hubungkanWebSocket, 3000);
  };

  ws.onerror = () => {
    updateStatus("disconnected");
  };
}

/**
 * Menangani pesan JSON yang masuk dari server.
 */
function handlePesan(data) {
  switch (data.type) {
    case "frame":
      renderFrame(data.data);
      break;

    case "info":
      remoteWidth  = data.width;
      remoteHeight = data.height;
      infoRes.textContent = `${data.width}×${data.height}`;
      aturUkuranCanvas(data.width, data.height);
      break;

    case "agent_status":
      agentConnected = data.connected;
      updateAgentStatus(data.connected);
      break;

    case "pong":
      infoPing.textContent = `${Math.round(performance.now() - lastPingTime)} ms`;
      break;
  }
}

// ─── Render frame ─────────────────────────────────────────────────────────────

/**
 * Menghitung dan menetapkan ukuran canvas agar proporsional dengan resolusi agent.
 * Dipanggil sekali saat pesan "info" diterima — bukan setiap frame.
 * Resize canvas menghapus isinya, jadi jangan lakukan di renderFrame.
 */
function aturUkuranCanvas(w, h) {
  const area = viewerArea.getBoundingClientRect();
  const scale = Math.min(area.width / w, area.height / h);
  canvas.width  = Math.floor(w * scale);
  canvas.height = Math.floor(h * scale);
}

/**
 * Mendekode string base64 JPEG dan menggambar ke canvas.
 * Tidak mengubah ukuran canvas agar tidak terjadi flash hitam antar frame.
 */
function renderFrame(base64Data) {
  overlayLoading.hidden = true;

  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    frameCount++;
  };
  img.src = `data:image/jpeg;base64,${base64Data}`;
}

// ─── FPS counter ──────────────────────────────────────────────────────────────

function mulaiFpsCounter() {
  setInterval(() => {
    const now = performance.now();
    const delta = (now - lastFpsTime) / 1000;
    infoFps.textContent = `${Math.round(frameCount / delta)} FPS`;
    frameCount = 0;
    lastFpsTime = now;

    // Kirim ping untuk mengukur latency
    if (ws && ws.readyState === WebSocket.OPEN) {
      lastPingTime = performance.now();
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 1000);
}

// ─── Input forwarding ─────────────────────────────────────────────────────────

/**
 * Menghitung posisi kursor relatif terhadap resolusi layar agent.
 * Mengonversi koordinat canvas ke koordinat piksel di layar agent.
 */
function hitungKoordinat(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = remoteWidth  / canvas.width;
  const scaleY = remoteHeight / canvas.height;
  return {
    x: Math.round((e.clientX - rect.left) * scaleX),
    y: Math.round((e.clientY - rect.top)  * scaleY),
  };
}

function kirimInput(data) {
  if (!inputEnabled) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!agentConnected) return;
  ws.send(JSON.stringify({ type: "input", ...data }));
}

// Mouse move — throttle agar tidak membanjiri server
let lastMoveTime = 0;
canvas.addEventListener("mousemove", (e) => {
  const now = Date.now();
  if (now - lastMoveTime < 16) return; // ~60Hz max
  lastMoveTime = now;
  const { x, y } = hitungKoordinat(e);
  kirimInput({ action: "mouse_move", x, y });
});

// Mouse click
canvas.addEventListener("mousedown", (e) => {
  e.preventDefault();
  const { x, y } = hitungKoordinat(e);
  const tombol = ["left", "middle", "right"][e.button] || "left";
  kirimInput({ action: "mouse_down", x, y, button: tombol });
});

canvas.addEventListener("mouseup", (e) => {
  e.preventDefault();
  const { x, y } = hitungKoordinat(e);
  const tombol = ["left", "middle", "right"][e.button] || "left";
  kirimInput({ action: "mouse_up", x, y, button: tombol });
});

canvas.addEventListener("dblclick", (e) => {
  const { x, y } = hitungKoordinat(e);
  kirimInput({ action: "mouse_click", x, y, button: "left", double: true });
});

// Scroll
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const { x, y } = hitungKoordinat(e);
  kirimInput({ action: "mouse_scroll", x, y, dx: e.deltaX, dy: -e.deltaY });
}, { passive: false });

// Klik kanan: kirim ke remote, jangan tampilkan context menu browser
canvas.addEventListener("contextmenu", (e) => e.preventDefault());

// Keyboard — tangkap saat fokus pada viewer
viewerArea.setAttribute("tabindex", "0");

/**
 * Tabel konversi dari key browser ke key pyautogui.
 * Hanya key-key khusus yang perlu dimap, huruf/angka biasa langsung diteruskan.
 */
const KEY_MAP = {
  " ": "space", Enter: "enter", Backspace: "backspace", Tab: "tab",
  Escape: "esc", Delete: "delete", Insert: "insert",
  Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  F1: "f1", F2: "f2", F3: "f3", F4: "f4", F5: "f5", F6: "f6",
  F7: "f7", F8: "f8", F9: "f9", F10: "f10", F11: "f11", F12: "f12",
  Control: "ctrl", Alt: "alt", Shift: "shift", Meta: "win",
  CapsLock: "capslock", NumLock: "numlock",
};

const tahan = new Set(); // Tombol yang sedang ditekan

viewerArea.addEventListener("keydown", (e) => {
  // Blokir shortcut browser yang umum agar diteruskan ke remote
  if (e.ctrlKey && ["a","c","v","x","z","y","r","w","t","n"].includes(e.key.toLowerCase())) {
    e.preventDefault();
  }
  if (e.key === "F11" || e.key === "F5") e.preventDefault();

  const kunci = KEY_MAP[e.key] || e.key.toLowerCase();
  if (tahan.has(kunci)) return; // sudah ditekan, skip repeat
  tahan.add(kunci);
  kirimInput({ action: "key_down", key: kunci });
});

viewerArea.addEventListener("keyup", (e) => {
  const kunci = KEY_MAP[e.key] || e.key.toLowerCase();
  tahan.delete(kunci);
  kirimInput({ action: "key_up", key: kunci });
});

// Klik area viewer agar langsung menerima keyboard
viewerArea.addEventListener("mouseenter", () => viewerArea.focus());

// ─── Hotkey buttons ───────────────────────────────────────────────────────────

/**
 * Tombol-tombol shortcut di footer — mengirim kombinasi key ke agent.
 */
hotkeys.forEach((btn) => {
  btn.addEventListener("click", () => {
    const aksi = btn.dataset.action;
    if (!aksi) return;

    const keys = aksi.split("+").map(k => KEY_MAP[k] || k);

    // Tekan semua key lalu lepas semua
    keys.forEach(k => kirimInput({ action: "key_down", key: k }));
    setTimeout(() => {
      [...keys].reverse().forEach(k => kirimInput({ action: "key_up", key: k }));
    }, 50);
  });
});

// ─── UI controls ──────────────────────────────────────────────────────────────

toggleInput.addEventListener("change", () => {
  inputEnabled = toggleInput.checked;
});

btnFullscreen.addEventListener("click", () => {
  if (!document.fullscreenElement) {
    viewerArea.requestFullscreen();
  } else {
    document.exitFullscreen();
  }
});

btnLogout.addEventListener("click", () => {
  sessionStorage.removeItem("jwt_token");
  jwtToken = null;
  if (ws) ws.close();
  tampilLogin();
});

// ─── Status UI ────────────────────────────────────────────────────────────────

function updateStatus(state) {
  const label = { connecting: "Menghubungkan...", connected: "Terhubung", disconnected: "Terputus" };
  statusLabel.textContent = label[state] || state;
  statusDot.className = `status-dot ${state}`;
}

function updateAgentStatus(online) {
  overlayOffline.hidden = online;

  if (online) {
    overlayLoading.hidden = false;
    statusLabel.textContent = "Agent online";
    statusDot.className = "status-dot connected";
  } else {
    overlayLoading.hidden = true;
    statusLabel.textContent = "Agent offline";
    statusDot.className = "status-dot offline";
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────

/**
 * Inisialisasi saat halaman dimuat.
 * Jika sudah ada JWT di sessionStorage, langsung ke viewer.
 */
window.addEventListener("resize", () => {
  if (remoteWidth && remoteHeight) aturUkuranCanvas(remoteWidth, remoteHeight);
});

(function init() {
  if (jwtToken) {
    tampilViewer();
    hubungkanWebSocket();
  } else {
    tampilLogin();
  }
})();
