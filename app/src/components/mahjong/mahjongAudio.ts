import type { AudioCfg, SfxKind } from '@/types/morev3';

const CFG_KEY = 'mahjong_audio_cfg_v1';

const DEFAULT_CFG: AudioCfg = {
  sfx: 70,
  bgm: 40,
  sfxOn: true,
  bgmOn: true,
};

function loadCfg(): AudioCfg {
  try {
    const raw = localStorage.getItem(CFG_KEY);
    if (!raw) return { ...DEFAULT_CFG };
    const parsed = JSON.parse(raw) as Partial<AudioCfg>;
    return { ...DEFAULT_CFG, ...parsed };
  } catch {
    return { ...DEFAULT_CFG };
  }
}

function saveCfg(cfg: AudioCfg) {
  try {
    localStorage.setItem(CFG_KEY, JSON.stringify(cfg));
  } catch {
    /* ignore */
  }
}

type BgmKind = 'bamboo_pentatonic' | 'fast_pentatonic';

interface MixerHandle {
  ctx: AudioContext | null;
  ensureCtx: () => AudioContext;
  sfxGain: GainNode | null;
  bgmGain: GainNode | null;
  cfg: AudioCfg;
  setCfg: (next: AudioCfg) => void;
  listeners: Set<(c: AudioCfg) => void>;
  lastAction: Map<string, number>;
  bgmNodes: Array<{ stop: () => void }>;
  bgmCurrent: BgmKind | null;
}

const HANDLE: MixerHandle = {
  ctx: null,
  ensureCtx() {
    if (!this.ctx) {
      const AC =
        (window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext }).AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) throw new Error('AudioContext not available');
      this.ctx = new AC();
      this.sfxGain = this.ctx.createGain();
      this.sfxGain.gain.value = this.cfg.sfxOn ? this.cfg.sfx / 100 : 0;
      this.sfxGain.connect(this.ctx.destination);
      this.bgmGain = this.ctx.createGain();
      this.bgmGain.gain.value = this.cfg.bgmOn ? this.cfg.bgm / 100 : 0;
      this.bgmGain.connect(this.ctx.destination);
    }
    if (this.ctx.state === 'suspended') {
      void this.ctx.resume();
    }
    return this.ctx;
  },
  sfxGain: null,
  bgmGain: null,
  cfg: loadCfg(),
  setCfg(next: AudioCfg) {
    this.cfg = next;
    saveCfg(next);
    if (this.sfxGain) this.sfxGain.gain.value = next.sfxOn ? next.sfx / 100 : 0;
    if (this.bgmGain) this.bgmGain.gain.value = next.bgmOn ? next.bgm / 100 : 0;
    for (const l of this.listeners) l(next);
  },
  listeners: new Set(),
  lastAction: new Map(),
  bgmNodes: [],
  bgmCurrent: null,
};

function playTone(
  ctx: AudioContext,
  dest: AudioNode,
  freq: number,
  type: OscillatorType,
  durMs: number,
  peak = 0.22,
  hpHz: number | null = null,
  lpHz: number | null = null,
) {
  const osc = ctx.createOscillator();
  osc.type = type;
  osc.frequency.value = freq;
  let node: AudioNode = osc;
  if (hpHz !== null) {
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = hpHz;
    node.connect(hp);
    node = hp;
  }
  if (lpHz !== null) {
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = lpHz;
    node.connect(lp);
    node = lp;
  }
  const g = ctx.createGain();
  const now = ctx.currentTime;
  const attack = 0.004;
  const decay = 0.006;
  const sustainRatio = 0.4;
  const release = Math.max(0.02, durMs / 1000 - attack - decay);
  g.gain.setValueAtTime(0, now);
  g.gain.linearRampToValueAtTime(peak, now + attack);
  g.gain.linearRampToValueAtTime(peak * sustainRatio, now + attack + decay);
  g.gain.linearRampToValueAtTime(0.0001, now + attack + decay + release);
  node.connect(g);
  g.connect(dest);
  osc.start(now);
  osc.stop(now + attack + decay + release + 0.02);
}

function makeNoiseBuffer(ctx: AudioContext, seconds: number) {
  const len = Math.floor(ctx.sampleRate * seconds);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  return buf;
}

function playNoise(
  ctx: AudioContext,
  dest: AudioNode,
  durMs: number,
  peak = 0.12,
  lpHz = 1800,
  hpHz = 200,
) {
  const src = ctx.createBufferSource();
  src.buffer = makeNoiseBuffer(ctx, Math.max(0.05, durMs / 1000 + 0.05));
  let node: AudioNode = src;
  const hp = ctx.createBiquadFilter();
  hp.type = 'highpass';
  hp.frequency.value = hpHz;
  node.connect(hp);
  node = hp;
  const lp = ctx.createBiquadFilter();
  lp.type = 'lowpass';
  lp.frequency.value = lpHz;
  node.connect(lp);
  node = lp;
  const g = ctx.createGain();
  const now = ctx.currentTime;
  const attack = 0.004;
  const decay = 0.006;
  const sustainRatio = 0.4;
  const release = Math.max(0.02, durMs / 1000 - attack - decay);
  g.gain.setValueAtTime(0, now);
  g.gain.linearRampToValueAtTime(peak, now + attack);
  g.gain.linearRampToValueAtTime(peak * sustainRatio, now + attack + decay);
  g.gain.linearRampToValueAtTime(0.0001, now + attack + decay + release);
  node.connect(g);
  g.connect(dest);
  src.start(now);
  src.stop(now + attack + decay + release + 0.02);
}

function dedupe(actionId: string): boolean {
  const now = Date.now();
  const prev = HANDLE.lastAction.get(actionId) ?? 0;
  if (now - prev < 150) return false;
  HANDLE.lastAction.set(actionId, now);
  return true;
}

export function playSfx(kind: SfxKind, actionId?: string) {
  if (actionId && !dedupe(actionId)) return;
  if (!HANDLE.cfg.sfxOn) return;
  const ctx = HANDLE.ensureCtx();
  const dest = HANDLE.sfxGain!;
  if (kind === 'draw') {
    playNoise(ctx, dest, 120, 0.1, 2600, 120);
    playTone(ctx, dest, 520, 'sine', 110, 0.12);
  } else if (kind === 'discard') {
    playNoise(ctx, dest, 90, 0.13, 3200, 220);
    playTone(ctx, dest, 420, 'triangle', 80, 0.12);
  } else if (kind === 'chow') {
    playTone(ctx, dest, 440, 'square', 100, 0.14, 80, 2000);
    setTimeout(() => playTone(ctx, dest, 554, 'square', 100, 0.14, 80, 2000), 60);
    setTimeout(() => playTone(ctx, dest, 659, 'square', 130, 0.14, 80, 2000), 120);
  } else if (kind === 'pung') {
    playTone(ctx, dest, 330, 'square', 150, 0.18, 80, 2200);
    setTimeout(() => playTone(ctx, dest, 330, 'square', 150, 0.18, 80, 2200), 80);
  } else if (kind === 'kong') {
    playTone(ctx, dest, 247, 'square', 180, 0.2, 80, 2400);
    setTimeout(() => playTone(ctx, dest, 247, 'square', 180, 0.2, 80, 2400), 90);
    setTimeout(() => playTone(ctx, dest, 494, 'square', 220, 0.22, 80, 2400), 180);
  } else if (kind === 'draw_game') {
    playTone(ctx, dest, 392, 'sine', 220, 0.16);
    setTimeout(() => playTone(ctx, dest, 330, 'sine', 220, 0.16), 140);
    setTimeout(() => playTone(ctx, dest, 262, 'sine', 300, 0.16), 280);
  } else if (kind === 'hu') {
    const notes = [523, 659, 784, 1047];
    notes.forEach((n, i) =>
      setTimeout(() => playTone(ctx, dest, n, 'square', 220, 0.2, 80, 3600), i * 100),
    );
  } else if (kind === 'cascade') {
    const n = 6;
    for (let i = 0; i < n; i++) {
      const f = 300 + (i * 120) % 600 + Math.random() * 120;
      setTimeout(
        () => playTone(ctx, dest, f, 'sine', 140, 0.13 + Math.random() * 0.05, 80, 4200),
        i * 35,
      );
    }
  }
}

const SCALE_C_PENTA = [261.63, 293.66, 329.63, 392.0, 440.0];
const SCALE_G_PENTA = [392.0, 440.0, 493.88, 587.33, 659.25];

function startBgm(kind: BgmKind) {
  if (HANDLE.bgmCurrent === kind) return;
  stopBgm();
  if (!HANDLE.cfg.bgmOn) return;
  const ctx = HANDLE.ensureCtx();
  const dest = HANDLE.bgmGain!;
  const bpm = kind === 'bamboo_pentatonic' ? 72 : 108;
  const scale = kind === 'bamboo_pentatonic' ? SCALE_C_PENTA : SCALE_G_PENTA;
  const bassScale = scale.map((f) => f / 2);
  const beatMs = 60000 / bpm;
  const unitMs = beatMs / 4;
  let tick = 0;
  let stopped = false;
  const bassOsc = ctx.createOscillator();
  bassOsc.type = 'triangle';
  bassOsc.frequency.value = bassScale[0];
  const bassGain = ctx.createGain();
  bassGain.gain.value = 0.0001;
  bassOsc.connect(bassGain);
  bassGain.connect(dest);
  bassOsc.start();
  const padOsc = ctx.createOscillator();
  padOsc.type = 'sine';
  padOsc.frequency.value = scale[0];
  const padLp = ctx.createBiquadFilter();
  padLp.type = 'lowpass';
  padLp.frequency.value = 1200;
  const padGain = ctx.createGain();
  padGain.gain.value = 0.0001;
  padOsc.connect(padLp);
  padLp.connect(padGain);
  padGain.connect(dest);
  padOsc.start();
  const interval = window.setInterval(() => {
    if (stopped || !HANDLE.ctx) return;
    const barPos = tick % 64;
    const beatIdx = Math.floor(barPos / 16) % 4;
    const now = HANDLE.ctx.currentTime;
    const melodyIdx =
      kind === 'bamboo_pentatonic'
        ? [0, 2, 4, 2, 1, 3, 4, 0, 2, 4, 3, 1, 2, 0, 3, 4][Math.floor(barPos / 4) % 16]
        : [4, 2, 0, 3, 1, 4, 2, 0, 3, 1, 4, 2, 0, 2, 4, 3][Math.floor(barPos / 4) % 16];
    const freq = scale[melodyIdx];
    const melDur = unitMs * 3.6;
    const peak = kind === 'bamboo_pentatonic' ? 0.04 : 0.055;
    playTone(HANDLE.ctx, dest, freq, 'sine', melDur, peak, null, 2800);
    if (barPos % 16 === 0) {
      const bassFreq = bassScale[beatIdx % bassScale.length];
      bassOsc.frequency.cancelScheduledValues(now);
      bassOsc.frequency.setValueAtTime(bassFreq, now);
      bassGain.gain.cancelScheduledValues(now);
      bassGain.gain.setValueAtTime(bassGain.gain.value, now);
      bassGain.gain.linearRampToValueAtTime(0.06, now + 0.02);
    }
    if (barPos % 8 === 0) {
      const padFreq = scale[(beatIdx + Math.floor(barPos / 32)) % scale.length];
      padOsc.frequency.cancelScheduledValues(now);
      padOsc.frequency.setValueAtTime(padFreq, now);
      padGain.gain.cancelScheduledValues(now);
      padGain.gain.setValueAtTime(padGain.gain.value, now);
      padGain.gain.linearRampToValueAtTime(0.035, now + 0.05);
    }
    if (barPos % 64 === 63) {
      const fadeAt = now + unitMs * 2 / 1000;
      bassGain.gain.setValueAtTime(bassGain.gain.value, now);
      bassGain.gain.linearRampToValueAtTime(0.0001, fadeAt);
      padGain.gain.setValueAtTime(padGain.gain.value, now);
      padGain.gain.linearRampToValueAtTime(0.0001, fadeAt);
    }
    tick += 1;
  }, unitMs);
  HANDLE.bgmNodes.push({
    stop: () => {
      stopped = true;
      window.clearInterval(interval);
      try {
        const now = HANDLE.ctx?.currentTime ?? 0;
        if (HANDLE.ctx) {
          bassGain.gain.cancelScheduledValues(now);
          bassGain.gain.setValueAtTime(bassGain.gain.value, now);
          bassGain.gain.linearRampToValueAtTime(0.0001, now + 0.1);
          padGain.gain.cancelScheduledValues(now);
          padGain.gain.setValueAtTime(padGain.gain.value, now);
          padGain.gain.linearRampToValueAtTime(0.0001, now + 0.1);
        }
        bassOsc.stop(now + 0.15);
        padOsc.stop(now + 0.15);
      } catch {
        /* ignore */
      }
    },
  });
  HANDLE.bgmCurrent = kind;
}

function stopBgm() {
  for (const n of HANDLE.bgmNodes) {
    try {
      n.stop();
    } catch {
      /* ignore */
    }
  }
  HANDLE.bgmNodes = [];
  HANDLE.bgmCurrent = null;
}

export function resumeAudio() {
  try {
    HANDLE.ensureCtx();
  } catch {
    /* ignore */
  }
}

export function playDraw(actionId?: string) {
  playSfx('draw', actionId);
}
export function playDiscard(actionId?: string) {
  playSfx('discard', actionId);
}
export function playChow(actionId?: string) {
  playSfx('chow', actionId);
}
export function playPung(actionId?: string) {
  playSfx('pung', actionId);
}
export function playKong(actionId?: string) {
  playSfx('kong', actionId);
}
export function playDrawGame(actionId?: string) {
  playSfx('draw_game', actionId);
}
export function playHu(actionId?: string) {
  playSfx('hu', actionId);
}
export function playCascade(level = 1) {
  for (let i = 0; i < Math.max(1, Math.min(5, level)); i++) {
    setTimeout(() => playSfx('cascade'), i * 60);
  }
}
export function playBgm(kind: BgmKind) {
  startBgm(kind);
}
export function stopAllBgm() {
  stopBgm();
}

/** 读取当前音效/音乐配置快照。 */
export function getAudioCfg(): AudioCfg {
  return { ...HANDLE.cfg };
}

/** 更新配置（写盘 + 广播给订阅者）。 */
export function setAudioCfg(next: AudioCfg): void {
  HANDLE.setCfg(next);
}

/** 订阅配置变化；返回取消订阅函数。 */
export function subscribeAudioCfg(listener: (c: AudioCfg) => void): () => void {
  HANDLE.listeners.add(listener);
  return () => {
    HANDLE.listeners.delete(listener);
  };
}

/** 当前是否正在播放 BGM（供设置面板展示/切换）。 */
export function isBgmPlaying(): boolean {
  return HANDLE.bgmCurrent !== null;
}

/** 在「停止试听」与「播放默认曲目」之间切换。 */
export function toggleBgm(kind: BgmKind = 'bamboo_pentatonic') {
  if (HANDLE.bgmCurrent) stopBgm();
  else startBgm(kind);
}
