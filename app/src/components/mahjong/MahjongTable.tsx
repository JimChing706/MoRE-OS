import * as React from 'react';
import type { GameState, Tile, Meld } from '@/types/morev3';
import { drawTile } from './TileRenderer';
import { reorderPermutation } from './HandReorder';
import { AnimationQueue, easeOutQuad, easeOutBounce, easeInOutQuad } from './Animations';
import { seatRect, feltRect, centerSquare, discardGrid } from './SeatLayout';

export interface MahjongTableProps {
  gameState: GameState;
  mySeatIdx: number;
  selectedTileIdx: number | null;
  onSelectTile: (idx: number | null) => void;
  onReorder: (perm: number[]) => void;
  onDiscardTile: (idx: number) => void;
  fanDisplay?: string;
  onUserGesture?: () => void;
}

interface DiscardAnim {
  id: string;
  seatIdx: number;
  tile: Tile;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  cx: number;
  cy: number;
  tiltFrom: number;
  tiltTo: number;
}

interface MeldAnim {
  id: string;
  seatIdx: number;
  meld: Meld;
  at: number;
}

interface HuAnim {
  seatIdx: number;
  startedAt: number;
}

interface DragState {
  active: boolean;
  dragIdx: number;
  ghostX: number;
  ghostY: number;
  pointerId: number;
  startX: number;
  startY: number;
  insertAt: number;
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

const RULESET_LABEL: Record<string, string> = {
  guobiao: '国标麻将',
  sichuan_xuemen: '四川血战',
  guangdong: '广东麻将',
};

export const MahjongTable: React.FC<MahjongTableProps> = ({
  gameState,
  mySeatIdx,
  selectedTileIdx,
  onSelectTile,
  onReorder,
  onDiscardTile,
  fanDisplay,
  onUserGesture,
}) => {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const wrapRef = React.useRef<HTMLDivElement | null>(null);
  const animQueueRef = React.useRef<AnimationQueue>(new AnimationQueue());
  const discardAnimsRef = React.useRef<Map<string, DiscardAnim>>(new Map());
  const meldAnimsRef = React.useRef<Map<string, MeldAnim>>(new Map());
  const huAnimRef = React.useRef<HuAnim | null>(null);
  const hoverIdxRef = React.useRef<number>(-1);
  const dragRef = React.useRef<DragState>({
    active: false,
    dragIdx: -1,
    ghostX: 0,
    ghostY: 0,
    pointerId: -1,
    startX: 0,
    startY: 0,
    insertAt: -1,
  });
  const rafRef = React.useRef<number>(0);
  const lastTsRef = React.useRef<number>(0);
  const prevStateRef = React.useRef<GameState>(gameState);
  const sizeRef = React.useRef<{ w: number; h: number }>({ w: 800, h: 600 });
  const [, force] = React.useReducer((x: number) => x + 1, 0);

  React.useEffect(() => {
    const prev = prevStateRef.current;
    const ps = prev.seats;
    const ns = gameState.seats;
    for (let s = 0; s < 4; s++) {
      const pSeat = ps[s];
      const nSeat = ns[s];
      if (!pSeat || !nSeat) continue;
      if (nSeat.discards.length > pSeat.discards.length) {
        const idx = nSeat.discards.length - 1;
        const tile = nSeat.discards[idx];
        if (tile) {
          const { w, h } = sizeRef.current;
          const seat = seatRect(s, w, h);
          const handArea = seat.handArea;
          const dArea = seat.discardArea;
          const dg = discardGrid(dArea, 12, 8);
          const col = idx % 12;
          const row = Math.floor(idx / 12);
          const tileW = Math.min(dg.cellW * 0.9, 28);
          const tileH = tileW * 1.4;
          const toX = dArea.x + col * (dg.cellW + dg.gapX) + (dg.cellW - tileW) / 2;
          const toY = dArea.y + row * (dg.cellH + dg.gapY) + (dg.cellH - tileH) / 2;
          let fromX: number;
          let fromY: number;
          if (s === mySeatIdx) {
            const hand = nSeat.hand;
            const handCount = Math.max(hand.length, 1);
            const tw = Math.min(handArea.w / handCount, 40);
            fromX = handArea.x + (handCount - 1) * (tw * 1.05) / 2 + tw * 0.02;
            fromY = handArea.y + (handArea.h - tw * 1.4) / 2;
          } else {
            fromX = handArea.x + handArea.w / 2;
            fromY = handArea.y + handArea.h / 2;
          }
          const cx = (fromX + toX) / 2 + (toY < fromY ? -30 : 30);
          const cy = Math.min(fromY, toY) - 40;
          const id = `d_${Date.now()}_${s}_${idx}`;
          const anim: DiscardAnim = {
            id,
            seatIdx: s,
            tile,
            fromX,
            fromY,
            toX,
            toY,
            cx,
            cy,
            tiltFrom: -20,
            tiltTo: 10,
          };
          discardAnimsRef.current.set(id, anim);
          const q = animQueueRef.current;
          q.play({
            keyframes: { p: 1 },
            duration: 280,
            easing: (t) => easeOutBounce(0.35 + 0.65 * easeOutQuad(t)),
            onUpdate: () => {},
            onEnd: () => {
              discardAnimsRef.current.delete(id);
            },
          });
        }
      }
      if (nSeat.melds.length > pSeat.melds.length) {
        for (let i = pSeat.melds.length; i < nSeat.melds.length; i++) {
          const m = nSeat.melds[i];
          if (!m) continue;
          const id = `m_${Date.now()}_${s}_${i}`;
          meldAnimsRef.current.set(id, { id, seatIdx: s, meld: m, at: Date.now() });
          const q = animQueueRef.current;
          q.play({
            keyframes: { p: 1 },
            duration: 220,
            easing: easeInOutQuad,
            onUpdate: () => {},
            onEnd: () => meldAnimsRef.current.delete(id),
          });
        }
      }
    }
    if (gameState.huResult && !prev.huResult) {
      huAnimRef.current = { seatIdx: gameState.huResult.winnerSeat, startedAt: Date.now() };
    } else if (!gameState.huResult) {
      huAnimRef.current = null;
    }
    prevStateRef.current = gameState;
  }, [gameState, mySeatIdx]);

  React.useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const r = e.contentRect;
        const w = Math.max(320, Math.floor(r.width));
        const h = Math.max(300, Math.floor(r.height));
        sizeRef.current = { w, h };
        const canvas = canvasRef.current;
        if (canvas) {
          const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
          canvas.width = w * dpr;
          canvas.height = h * dpr;
          canvas.style.width = `${w}px`;
          canvas.style.height = `${h}px`;
          const ctx = canvas.getContext('2d');
          if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const renderFrame = React.useCallback(
    (dt: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const { w, h } = sizeRef.current;
      animQueueRef.current.onTick(dt);
      ctx.clearRect(0, 0, w, h);
      const felt = feltRect(w, h);
      const radius = Math.max(18, Math.min(felt.w, felt.h) * 0.05);
      ctx.save();
      ctx.fillStyle = '#0f3d29';
      ctx.beginPath();
      const x = felt.x;
      const y = felt.y;
      const rw = felt.w;
      const rh = felt.h;
      ctx.moveTo(x + radius, y);
      ctx.lineTo(x + rw - radius, y);
      ctx.quadraticCurveTo(x + rw, y, x + rw, y + radius);
      ctx.lineTo(x + rw, y + rh - radius);
      ctx.quadraticCurveTo(x + rw, y + rh, x + rw - radius, y + rh);
      ctx.lineTo(x + radius, y + rh);
      ctx.quadraticCurveTo(x, y + rh, x, y + rh - radius);
      ctx.lineTo(x, y + radius);
      ctx.quadraticCurveTo(x, y, x + radius, y);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,0.25)';
      ctx.lineWidth = 2;
      ctx.stroke();
      const cxPad = Math.max(20, Math.min(rw, rh) * 0.04);
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.strokeRect(felt.x + cxPad, felt.y + cxPad, rw - cxPad * 2, rh - cxPad * 2);
      ctx.restore();
      const center = centerSquare(w, h);
      ctx.save();
      const grad = ctx.createLinearGradient(center.x, center.y, center.x + center.w, center.y + center.h);
      grad.addColorStop(0, 'rgba(212,160,23,0.25)');
      grad.addColorStop(1, 'rgba(212,160,23,0.08)');
      ctx.fillStyle = grad;
      ctx.strokeStyle = 'rgba(212,160,23,0.55)';
      ctx.lineWidth = 2;
      const rr = Math.min(center.w, center.h) * 0.18;
      ctx.beginPath();
      ctx.moveTo(center.x + rr, center.y);
      ctx.lineTo(center.x + center.w - rr, center.y);
      ctx.quadraticCurveTo(center.x + center.w, center.y, center.x + center.w, center.y + rr);
      ctx.lineTo(center.x + center.w, center.y + center.h - rr);
      ctx.quadraticCurveTo(center.x + center.w, center.y + center.h, center.x + center.w - rr, center.y + center.h);
      ctx.lineTo(center.x + rr, center.y + center.h);
      ctx.quadraticCurveTo(center.x, center.y + center.h, center.x, center.y + center.h - rr);
      ctx.lineTo(center.x, center.y + rr);
      ctx.quadraticCurveTo(center.x, center.y, center.x + rr, center.y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#fde68a';
      ctx.font = `bold ${Math.max(12, Math.floor(center.h * 0.32))}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const fanTxt = fanDisplay || `${gameState.round}局`;
      ctx.fillText(fanTxt, center.x + center.w / 2, center.y + center.h / 2);
      ctx.font = `${Math.max(9, Math.floor(center.h * 0.14))}px sans-serif`;
      ctx.fillStyle = 'rgba(253,230,138,0.85)';
      ctx.fillText(
        RULESET_LABEL[gameState.ruleset] || gameState.ruleset,
        center.x + center.w / 2,
        center.y + center.h - Math.max(8, center.h * 0.14),
      );
      ctx.restore();
      const seats = gameState.seats;
      const lastSeatIdx = gameState.lastDiscard?.seatIdx;
      const lastTileId = gameState.lastDiscard?.tile.id;
      for (let s = 0; s < 4; s++) {
        const seat = seatRect(s, w, h);
        const seatData = seats[s];
        const meldArea = seat.meldArea;
        const discardArea = seat.discardArea;
        const labelPt = seat.labelPoint;
        ctx.save();
        ctx.fillStyle = s === gameState.currentTurn ? '#fde68a' : 'rgba(255,255,255,0.9)';
        ctx.font = `bold ${Math.max(10, Math.floor(h * 0.022))}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const seatLabel =
          seatData?.playerName ||
          ['东', '南', '西', '北'][s] ||
          `座位${s + 1}`;
        if (s === gameState.currentTurn) {
          ctx.shadowColor = 'rgba(253,224,71,0.8)';
          ctx.shadowBlur = 8;
        }
        ctx.fillText(seatLabel, labelPt.x, labelPt.y);
        ctx.restore();
        if (seatData) {
          const dg = discardGrid(discardArea, 12, 8);
          const tileW = Math.min(dg.cellW * 0.9, 28);
          const tileH = tileW * 1.4;
          for (let i = 0; i < seatData.discards.length; i++) {
            const tile = seatData.discards[i];
            if (!tile) continue;
            const col = i % 12;
            const row = Math.floor(i / 12);
            const tx = discardArea.x + col * (dg.cellW + dg.gapX) + (dg.cellW - tileW) / 2;
            const ty = discardArea.y + row * (dg.cellH + dg.gapY) + (dg.cellH - tileH) / 2;
            const isLast = s === lastSeatIdx && lastTileId === tile.id && i === seatData.discards.length - 1;
            drawTile(ctx, tile, tx, ty, tileW, tileH, {
              highlighted: isLast,
            });
          }
          const meldCount = seatData.melds.length;
          if (meldCount > 0) {
            const meldTileW = Math.min(meldArea.h * 0.7, meldArea.w / Math.max(meldCount * 3, 1));
            const meldTileH = meldTileW * 1.4;
            for (let mIdx = 0; mIdx < meldCount; mIdx++) {
              const meld = seatData.melds[mIdx];
              let mx: number;
              let my: number;
              if (s === 0 || s === 2) {
                mx = meldArea.x + mIdx * (meldTileW * 3.2 + 8);
                my = meldArea.y + (meldArea.h - meldTileH) / 2;
              } else if (s === 1) {
                mx = meldArea.x + (meldArea.w - meldTileH) / 2;
                my = meldArea.y + mIdx * (meldTileW * 3.2 + 8);
              } else {
                mx = meldArea.x + (meldArea.w - meldTileH) / 2;
                my = meldArea.y + mIdx * (meldTileW * 3.2 + 8);
              }
              const meldAnimKey = Array.from(meldAnimsRef.current.values()).find(
                (a) => a.seatIdx === s,
              )?.id;
              const animVal = meldAnimKey
                ? Math.min(1, (Date.now() - (meldAnimsRef.current.get(meldAnimKey)?.at ?? 0)) / 220)
                : 1;
              const scale = animVal < 1 ? 1 + 0.1 * Math.sin(animVal * Math.PI) : 1;
              const highlight = animVal < 1;
              for (let t = 0; t < meld.tiles.length; t++) {
                const mt = meld.tiles[t];
                if (!mt) continue;
                let ox = 0;
                let oy = 0;
                if (s === 0 || s === 2) {
                  ox = t * meldTileW * 1.05;
                } else {
                  oy = t * meldTileW * 1.05;
                }
                ctx.save();
                const cxp = mx + ox + meldTileW / 2;
                const cyp = my + oy + meldTileH / 2;
                ctx.translate(cxp, cyp);
                ctx.scale(scale, scale);
                ctx.translate(-cxp, -cyp);
                drawTile(ctx, mt, mx + ox, my + oy, meldTileW, meldTileH, {
                  highlighted: highlight,
                });
                ctx.restore();
              }
            }
          }
        }
      }
      const mySeat = seats[mySeatIdx];
      if (mySeat) {
        const me = seatRect(mySeatIdx, w, h);
        const handArea = me.handArea;
        const hand = mySeat.hand;
        const baseW = hand.length > 0 ? Math.min(handArea.w / hand.length, 44) : 40;
        const tileW = baseW;
        const tileH = tileW * 1.4;
        const gap = tileW * 0.05;
        const totalW = hand.length * tileW + (hand.length - 1) * gap;
        const startX = handArea.x + (handArea.w - totalW) / 2;
        const y = handArea.y + (handArea.h - tileH) / 2;
        for (let i = 0; i < hand.length; i++) {
          const t = hand[i];
          if (!t) continue;
          const isSelected = selectedTileIdx === i;
          const isHover = hoverIdxRef.current === i && !dragRef.current.active;
          const dragging = dragRef.current.active && dragRef.current.dragIdx === i;
          if (dragging) continue;
          let tx = startX + i * (tileW + gap);
          if (dragRef.current.active && dragRef.current.dragIdx >= 0) {
            const dragIdx = dragRef.current.dragIdx;
            const insertAt = dragRef.current.insertAt;
            let shift = 0;
            if (insertAt >= 0) {
              if (dragIdx < insertAt) {
                if (i > dragIdx && i <= insertAt) shift = -1;
              } else {
                if (i < dragIdx && i >= insertAt) shift = 1;
              }
            }
            tx += shift * (tileW + gap);
          }
          drawTile(ctx, t, tx, y, tileW, tileH, {
            selected: isSelected,
            hovered: isHover,
          });
        }
        if (dragRef.current.active && dragRef.current.dragIdx >= 0) {
          const dIdx = dragRef.current.dragIdx;
          const t = hand[dIdx];
          if (t) {
            ctx.save();
            ctx.globalAlpha = 0.85;
            drawTile(
              ctx,
              t,
              dragRef.current.ghostX - tileW / 2,
              dragRef.current.ghostY - tileH / 2,
              tileW,
              tileH,
              { selected: true },
            );
            ctx.restore();
          }
        }
      }
      for (const anim of discardAnimsRef.current.values()) {
        const elapsed = Date.now() % 10000;
        void elapsed;
        const p = Math.min(1, (Date.now() - parseInt(anim.id.split('_')[1], 10) || 0) / 280);
        const t = easeOutQuad(p);
        const u = 1 - t;
        const x = u * u * anim.fromX + 2 * u * t * anim.cx + t * t * anim.toX;
        const yy = u * u * anim.fromY + 2 * u * t * anim.cy + t * t * anim.toY;
        const tilt = anim.tiltFrom + (anim.tiltTo - anim.tiltFrom) * t;
        const dg = discardGrid(seatRect(anim.seatIdx, w, h).discardArea, 12, 8);
        const tileW = Math.min(dg.cellW * 0.9, 28);
        const tileH = tileW * 1.4;
        ctx.save();
        ctx.translate(x + tileW / 2, yy + tileH / 2);
        ctx.rotate((tilt * Math.PI) / 180);
        ctx.translate(-tileW / 2, -tileH / 2);
        drawTile(ctx, anim.tile, 0, 0, tileW, tileH);
        ctx.restore();
      }
      if (huAnimRef.current) {
        const elapsed = Date.now() - huAnimRef.current.startedAt;
        const tFlip = Math.min(1, elapsed / 500);
        const tScale = Math.min(1, elapsed / 800);
        const sIdx = huAnimRef.current.seatIdx;
        const seatData = seats[sIdx];
        const seat = seatRect(sIdx, w, h);
        const handArea = seat.handArea;
        if (seatData && seatData.hand.length > 0) {
          const hand = seatData.hand;
          const baseW = Math.min(handArea.w / hand.length, 44);
          const tileW = baseW;
          const tileH = tileW * 1.4;
          const gap = tileW * 0.05;
          const totalW = hand.length * tileW + (hand.length - 1) * gap;
          const startX = handArea.x + (handArea.w - totalW) / 2;
          const yy = handArea.y + (handArea.h - tileH) / 2;
          const scale = 1 + 0.15 * (1 - Math.pow(1 - tScale, 3));
          const flip = Math.cos(tFlip * Math.PI);
          for (let i = 0; i < hand.length; i++) {
            const tile = hand[i];
            if (!tile) continue;
            ctx.save();
            const cxp = startX + i * (tileW + gap) + tileW / 2;
            const cyp = yy + tileH / 2;
            ctx.translate(cxp, cyp);
            ctx.scale(scale * Math.max(0.15, Math.abs(flip)), scale);
            ctx.translate(-tileW / 2, -tileH / 2);
            if (flip < 0) drawTile(ctx, 'back', 0, 0, tileW, tileH);
            else drawTile(ctx, tile, 0, 0, tileW, tileH, { selected: true });
            ctx.restore();
          }
          if (elapsed > 300) {
            const haloT = Math.min(1, (elapsed - 300) / 500);
            const cxp = handArea.x + handArea.w / 2;
            const cyp = handArea.y + handArea.h / 2;
            const haloR = Math.min(handArea.w, handArea.h * 2) * (0.3 + 0.7 * haloT);
            const g = ctx.createRadialGradient(cxp, cyp, 0, cxp, cyp, haloR);
            g.addColorStop(0, `rgba(253, 224, 71, ${0.55 * haloT})`);
            g.addColorStop(0.6, `rgba(253, 224, 71, ${0.2 * haloT})`);
            g.addColorStop(1, 'rgba(253, 224, 71, 0)');
            ctx.save();
            ctx.globalCompositeOperation = 'lighter';
            ctx.fillStyle = g;
            ctx.beginPath();
            ctx.arc(cxp, cyp, haloR, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
          }
        }
      }
    },
    [gameState, mySeatIdx, selectedTileIdx, fanDisplay],
  );

  React.useEffect(() => {
    const loop = (ts: number) => {
      const last = lastTsRef.current || ts;
      const dt = Math.min(64, ts - last);
      lastTsRef.current = ts;
      renderFrame(dt);
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [renderFrame]);

  const getHandTileAt = React.useCallback(
    (px: number, py: number): { idx: number; tx: number; ty: number; tileW: number; tileH: number } | null => {
      const { w, h } = sizeRef.current;
      const seat = seatRect(mySeatIdx, w, h);
      const handArea = seat.handArea;
      const seatData = gameState.seats[mySeatIdx];
      if (!seatData) return null;
      const hand = seatData.hand;
      if (hand.length === 0) return null;
      const tileW = Math.min(handArea.w / hand.length, 44);
      const tileH = tileW * 1.4;
      const gap = tileW * 0.05;
      const totalW = hand.length * tileW + (hand.length - 1) * gap;
      const startX = handArea.x + (handArea.w - totalW) / 2;
      const y = handArea.y + (handArea.h - tileH) / 2;
      for (let i = 0; i < hand.length; i++) {
        const tx = startX + i * (tileW + gap);
        if (px >= tx - 2 && px <= tx + tileW + 2 && py >= y - 10 && py <= y + tileH + 2) {
          return { idx: i, tx, ty: y, tileW, tileH };
        }
      }
      return null;
    },
    [gameState, mySeatIdx],
  );

  const onPointerDown = React.useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      onUserGesture?.();
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const hit = getHandTileAt(px, py);
      if (!hit) {
        onSelectTile(null);
        return;
      }
      dragRef.current = {
        active: true,
        dragIdx: hit.idx,
        ghostX: px,
        ghostY: py,
        pointerId: e.pointerId,
        startX: px,
        startY: py,
        insertAt: hit.idx,
      };
      hoverIdxRef.current = -1;
      canvas.setPointerCapture(e.pointerId);
      force();
    },
    [getHandTileAt, onSelectTile, onUserGesture],
  );

  const onPointerMove = React.useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      if (dragRef.current.active && dragRef.current.pointerId === e.pointerId) {
        dragRef.current.ghostX = px;
        dragRef.current.ghostY = py;
        const seat = seatRect(mySeatIdx, sizeRef.current.w, sizeRef.current.h);
        const handArea = seat.handArea;
        const seatData = gameState.seats[mySeatIdx];
        if (seatData && seatData.hand.length > 1) {
          const hand = seatData.hand;
          const tileW = Math.min(handArea.w / hand.length, 44);
          const gap = tileW * 0.05;
          const totalW = hand.length * tileW + (hand.length - 1) * gap;
          const startX = handArea.x + (handArea.w - totalW) / 2;
          const localX = clamp(px - startX + tileW / 2, 0, totalW);
          let idx = Math.floor(localX / (tileW + gap));
          idx = clamp(idx, 0, hand.length);
          dragRef.current.insertAt = idx;
        }
        force();
      } else {
        const hit = getHandTileAt(px, py);
        const newHover = hit ? hit.idx : -1;
        if (newHover !== hoverIdxRef.current) {
          hoverIdxRef.current = newHover;
          force();
        }
      }
    },
    [gameState, mySeatIdx, getHandTileAt],
  );

  const onPointerUp = React.useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (dragRef.current.active && dragRef.current.pointerId === e.pointerId) {
        const canvas = canvasRef.current;
        if (canvas) {
          try {
            canvas.releasePointerCapture(e.pointerId);
          } catch {
            /* ignore */
          }
        }
        const moved =
          Math.abs(dragRef.current.ghostX - dragRef.current.startX) +
            Math.abs(dragRef.current.ghostY - dragRef.current.startY) >
          6;
        const dragIdx = dragRef.current.dragIdx;
        const insertAt = dragRef.current.insertAt;
        const wasActive = dragRef.current.active;
        dragRef.current = {
          active: false,
          dragIdx: -1,
          ghostX: 0,
          ghostY: 0,
          pointerId: -1,
          startX: 0,
          startY: 0,
          insertAt: -1,
        };
        if (wasActive && moved && dragIdx >= 0 && insertAt >= 0 && insertAt !== dragIdx) {
          const seatData = gameState.seats[mySeatIdx];
          if (seatData) {
            const { perm } = reorderPermutation(seatData.hand, dragIdx, insertAt);
            onReorder(perm);
          }
        } else if (wasActive && !moved && dragIdx >= 0) {
          if (selectedTileIdx === dragIdx) {
            onDiscardTile(dragIdx);
            onSelectTile(null);
          } else {
            onSelectTile(dragIdx);
          }
        }
        force();
      }
    },
    [gameState, mySeatIdx, onReorder, onSelectTile, onDiscardTile, selectedTileIdx],
  );

  return (
    <div
      ref={wrapRef}
      className="relative w-full h-full touch-none"
      style={{ minHeight: '420px' }}
    >
      <canvas
        ref={canvasRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className="w-full h-full block rounded-xl"
        style={{ aspectRatio: '4 / 3' }}
      />
    </div>
  );
};

export default MahjongTable;
