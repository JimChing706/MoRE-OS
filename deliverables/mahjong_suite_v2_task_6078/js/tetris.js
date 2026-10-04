/* Tetris 前端核心逻辑：渲染 + 键盘控制 + 简易 WebAudio 音效合成。
 * 后端 Rust 核心算法通过 WebAssembly 接入（此文件内置等价 JS 实现保证开箱即用）。
 */
(function () {
  "use strict";

  const COLS = 10, ROWS = 20, CELL = 30;
  const COLORS = {
    I: "#22d3ee", O: "#facc15", T: "#a78bfa",
    S: "#4ade80", Z: "#f87171", J: "#60a5fa", L: "#fb923c"
  };
  const PIECES = {
    I: [[0,1],[1,1],[2,1],[3,1]],
    O: [[0,0],[1,0],[0,1],[1,1]],
    T: [[0,1],[1,1],[2,1],[1,2]],
    S: [[1,1],[2,1],[0,2],[1,2]],
    Z: [[0,1],[1,1],[1,2],[2,2]],
    J: [[0,0],[0,1],[1,1],[2,1]],
    L: [[2,0],[0,1],[1,1],[2,1]],
  };
  const TYPES = ["I","O","T","S","Z","J","L"];

  const boardCvs = document.getElementById("board");
  const ctx = boardCvs.getContext("2d");
  const nextCvs = document.getElementById("next");
  const nctx = nextCvs.getContext("2d");
  const holdCvs = document.getElementById("hold");
  const hctx = holdCvs.getContext("2d");

  const $score = document.getElementById("score");
  const $level = document.getElementById("level");
  const $lines = document.getElementById("lines");
  const $combo = document.getElementById("combo");
  const $status = document.getElementById("status");

  let board, current, curX, curY, curRot, nextQueue, holdPiece, holdUsed;
  let score, lines, level, combo, gameOver, paused, dropTimer, lastTick;
  let bagBuf = [];

  function reset() {
    board = Array.from({length: ROWS}, () => Array(COLS).fill(null));
    score = 0; lines = 0; level = 1; combo = 0;
    gameOver = false; paused = false; holdPiece = null; holdUsed = false;
    nextQueue = []; bagBuf = [];
    for (let i = 0; i < 5; i++) nextQueue.push(nextBagPiece());
    spawn();
    dropTimer = 0; lastTick = performance.now();
    $status.textContent = "";
    updateStats();
  }

  function refillBag() {
    bagBuf = TYPES.slice();
    for (let i = bagBuf.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [bagBuf[i], bagBuf[j]] = [bagBuf[j], bagBuf[i]];
    }
  }
  function nextBagPiece() {
    if (bagBuf.length === 0) refillBag();
    return bagBuf.pop();
  }

  function spawn() {
    current = nextQueue.shift();
    nextQueue.push(nextBagPiece());
    curRot = 0;
    curX = 3;
    curY = -1;
    holdUsed = false;
    if (!valid(current, curX, curY, curRot)) {
      gameOver = true;
      $status.textContent = "游戏结束 (Game Over) — 按 R 重开";
      playSfx("gameover");
    }
  }

  function rotCells(type, rot) {
    // 简易旋转（非完整 SRS 但满足基本游戏）
    const base = PIECES[type].map(p => p.slice());
    for (let r = 0; r < rot; r++) {
      for (const p of base) {
        const [x, y] = p;
        if (type === "I") { p[0] = 3 - y; p[1] = x; }
        else if (type === "O") { /* noop */ }
        else { p[0] = 2 - y; p[1] = x; }
      }
    }
    return base;
  }

  function valid(type, x, y, rot) {
    for (const [dx, dy] of rotCells(type, rot)) {
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || nx >= COLS || ny >= ROWS) return false;
      if (ny >= 0 && board[ny][nx]) return false;
    }
    return true;
  }

  function merge() {
    for (const [dx, dy] of rotCells(current, curRot)) {
      const nx = curX + dx, ny = curY + dy;
      if (ny >= 0) board[ny][nx] = current;
    }
  }

  function clearLines() {
    let cleared = 0;
    for (let y = ROWS - 1; y >= 0; y--) {
      if (board[y].every(c => c)) {
        board.splice(y, 1);
        board.unshift(Array(COLS).fill(null));
        cleared++;
        y++;
      }
    }
    if (cleared > 0) {
      const base = [0, 100, 300, 500, 800][cleared] || 0;
      score += base * level;
      lines += cleared;
      combo += 1;
      score += 50 * combo * level;
      const newLevel = Math.floor(lines / 10) + 1;
      if (newLevel !== level) { level = newLevel; playSfx("levelup"); }
      playSfx(cleared === 4 ? "tetris" : "clear");
    } else {
      combo = 0;
    }
    updateStats();
  }

  function move(dx) {
    if (valid(current, curX + dx, curY, curRot)) { curX += dx; playSfx("move"); return true; }
    return false;
  }
  function softDrop() {
    if (valid(current, curX, curY + 1, curRot)) {
      curY += 1; score += 1; updateStats(); playSfx("move"); return true;
    }
    return false;
  }
  function hardDrop() {
    let d = 0;
    while (valid(current, curX, curY + 1, curRot)) { curY++; d++; }
    score += d * 2;
    lockPiece();
    playSfx("hard");
  }
  function rotate(dir) {
    const newRot = (curRot + (dir > 0 ? 1 : 3)) % 4;
    const kicks = [[0,0],[-1,0],[1,0],[0,-1],[-1,-1],[1,-1]];
    for (const [kx, ky] of kicks) {
      if (valid(current, curX + kx, curY + ky, newRot)) {
        curX += kx; curY += ky; curRot = newRot;
        playSfx("rotate"); return true;
      }
    }
    return false;
  }
  function hold() {
    if (holdUsed) return;
    if (holdPiece === null) {
      holdPiece = current;
      spawn();
    } else {
      const tmp = holdPiece; holdPiece = current; current = tmp;
      curRot = 0; curX = 3; curY = -1;
    }
    holdUsed = true;
    playSfx("hold");
  }
  function lockPiece() {
    merge();
    playSfx("lock");
    clearLines();
    spawn();
  }

  function updateStats() {
    $score.textContent = score;
    $level.textContent = level;
    $lines.textContent = lines;
    $combo.textContent = combo;
  }

  function ghostY() {
    let y = curY;
    while (valid(current, curX, y + 1, curRot)) y++;
    return y;
  }

  function drawCell(c, x, y, color, alpha) {
    c.globalAlpha = alpha || 1;
    c.fillStyle = color;
    c.fillRect(x * CELL, y * CELL, CELL - 1, CELL - 1);
    c.strokeStyle = "rgba(255,255,255,0.25)";
    c.lineWidth = 1;
    c.strokeRect(x * CELL + 0.5, y * CELL + 0.5, CELL - 2, CELL - 2);
    c.globalAlpha = 1;
  }

  function drawBoard() {
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(0, 0, boardCvs.width, boardCvs.height);
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        if (board[y][x]) drawCell(ctx, x, y, COLORS[board[y][x]]);
      }
    }
    if (!gameOver) {
      const gy = ghostY();
      for (const [dx, dy] of rotCells(current, curRot)) {
        const nx = curX + dx, ny = gy + dy;
        if (ny >= 0) drawCell(ctx, nx, ny, COLORS[current], 0.25);
      }
      for (const [dx, dy] of rotCells(current, curRot)) {
        const nx = curX + dx, ny = curY + dy;
        if (ny >= 0) drawCell(ctx, nx, ny, COLORS[current]);
      }
    }
  }
  function drawQueue() {
    nctx.fillStyle = "#1e293b";
    nctx.fillRect(0, 0, nextCvs.width, nextCvs.height);
    for (let i = 0; i < Math.min(5, nextQueue.length); i++) {
      const t = nextQueue[i];
      const baseY = i * 72 + 10;
      for (const [dx, dy] of PIECES[t]) {
        drawCell(nctx, dx + 1, dy + Math.floor(baseY / 24), COLORS[t], 1);
      }
    }
  }
  function drawHold() {
    hctx.fillStyle = "#1e293b";
    hctx.fillRect(0, 0, holdCvs.width, holdCvs.height);
    if (holdPiece) {
      for (const [dx, dy] of PIECES[holdPiece]) {
        drawCell(hctx, dx + 0.5, dy + 0.5, COLORS[holdPiece]);
      }
    }
  }
  function draw() { drawBoard(); drawQueue(); drawHold(); }

  function loop(now) {
    const dt = now - lastTick; lastTick = now;
    if (!paused && !gameOver) {
      dropTimer += dt;
      const interval = Math.max(50, 1000 - (level - 1) * 80);
      if (dropTimer > interval) {
        if (!softDrop()) { /* softDrop 已包含音效/加分，不触发时走静默下落 */
          if (valid(current, curX, curY + 1, curRot)) {
            curY += 1;
          } else {
            lockPiece();
          }
        }
        dropTimer = 0;
      }
    }
    draw();
    requestAnimationFrame(loop);
  }

  /* ===== WebAudio 简易合成 ===== */
  let audioCtx = null;
  function ensureAudio() {
    if (!audioCtx) {
      try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { audioCtx = null; }
    }
  }
  function playTone(freq, durMs, type, gain) {
    if (!audioCtx) return;
    const t0 = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    osc.type = type || "square";
    osc.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(gain || 0.08, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + durMs / 1000);
    osc.connect(g).connect(audioCtx.destination);
    osc.start(t0); osc.stop(t0 + durMs / 1000 + 0.02);
  }
  function playSfx(kind) {
    ensureAudio();
    if (!audioCtx) return;
    switch (kind) {
      case "move":    playTone(520, 30, "square", 0.05); break;
      case "rotate":  playTone(760, 40, "triangle", 0.06); break;
      case "lock":    playTone(160, 90, "square", 0.1); break;
      case "clear":   playTone(880, 100, "sine", 0.08); break;
      case "tetris":  [523, 659, 784, 988].forEach((f, i) => setTimeout(() => playTone(f, 120, "square", 0.08), i * 60)); break;
      case "hard":    playTone(1100, 25, "sawtooth", 0.07); break;
      case "hold":    playTone(700, 30, "sine", 0.06); break;
      case "levelup": [523, 659, 784, 1046].forEach((f, i) => setTimeout(() => playTone(f, 150, "triangle", 0.08), i * 80)); break;
      case "gameover":[523, 440, 349, 262].forEach((f, i) => setTimeout(() => playTone(f, 220, "sawtooth", 0.08), i * 140)); break;
    }
  }

  /* ===== 键盘事件 ===== */
  document.addEventListener("keydown", (e) => {
    ensureAudio();
    if (e.repeat && !["ArrowDown"].includes(e.key)) return;
    switch (e.key) {
      case "ArrowLeft":  move(-1); break;
      case "ArrowRight": move(1);  break;
      case "ArrowDown":  softDrop(); break;
      case "ArrowUp":
      case "x": case "X": rotate(1); break;
      case "z": case "Z": rotate(-1); break;
      case " ": hardDrop(); e.preventDefault(); break;
      case "c": case "C":
      case "Shift": hold(); break;
      case "p": case "P":
        if (!gameOver) { paused = !paused; $status.textContent = paused ? "已暂停 (P 继续)" : ""; }
        break;
      case "r": case "R": reset(); break;
    }
  });

  reset();
  requestAnimationFrame(loop);
})();
