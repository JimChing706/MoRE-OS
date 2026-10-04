import type { Tile } from '@/types/morev3';

export interface TileDrawOptions {
  highlighted?: boolean;
  selected?: boolean;
  hovered?: boolean;
}

const WAN_CHARS = ['一', '二', '三', '四', '五', '六', '七', '八', '九'];
const TIAO_CHARS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
const TONG_DOTS: Array<Array<[number, number]>> = [
  [[0.5, 0.5]],
  [[0.25, 0.25], [0.75, 0.75]],
  [[0.25, 0.25], [0.5, 0.5], [0.75, 0.75]],
  [[0.25, 0.2], [0.75, 0.2], [0.25, 0.8], [0.75, 0.8]],
  [[0.25, 0.2], [0.75, 0.2], [0.5, 0.5], [0.25, 0.8], [0.75, 0.8]],
  [[0.25, 0.2], [0.75, 0.2], [0.25, 0.5], [0.75, 0.5], [0.25, 0.8], [0.75, 0.8]],
  [[0.25, 0.2], [0.5, 0.35], [0.75, 0.2], [0.25, 0.5], [0.75, 0.5], [0.25, 0.8], [0.5, 0.65]],
  [[0.25, 0.2], [0.75, 0.2], [0.25, 0.45], [0.5, 0.45], [0.75, 0.45], [0.25, 0.8], [0.5, 0.8], [0.75, 0.8]],
  [[0.2, 0.2], [0.5, 0.2], [0.8, 0.2], [0.2, 0.5], [0.5, 0.5], [0.8, 0.5], [0.2, 0.8], [0.5, 0.8], [0.8, 0.8]],
];

const WIND_CHARS: Record<string, string> = {
  East: '東',
  South: '南',
  West: '西',
  North: '北',
};

const DRAGON_CHARS: Record<string, string> = {
  Zhong: '中',
  Fa: '發',
  Bai: '白',
};

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawBackPattern(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
) {
  ctx.fillStyle = '#1a5f3a';
  roundRect(ctx, x, y, w, h, 4);
  ctx.fill();
  ctx.save();
  ctx.beginPath();
  roundRect(ctx, x, y, w, h, 4);
  ctx.clip();
  ctx.strokeStyle = 'rgba(255,255,255,0.07)';
  ctx.lineWidth = 1;
  const step = 6;
  for (let i = -h; i < w + h; i += step) {
    ctx.beginPath();
    ctx.moveTo(x + i, y);
    ctx.lineTo(x + i + h, y + h);
    ctx.stroke();
  }
  for (let i = 0; i < w + h; i += step) {
    ctx.beginPath();
    ctx.moveTo(x + i, y + h);
    ctx.lineTo(x + i - h, y);
    ctx.stroke();
  }
  ctx.strokeStyle = 'rgba(0,0,0,0.12)';
  for (let i = -h + step / 2; i < w + h; i += step) {
    ctx.beginPath();
    ctx.moveTo(x + i, y);
    ctx.lineTo(x + i + h, y + h);
    ctx.stroke();
  }
  ctx.restore();
  ctx.strokeStyle = 'rgba(0,0,0,0.25)';
  ctx.lineWidth = 1;
  roundRect(ctx, x, y, w, h, 4);
  ctx.stroke();
  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 3, y + 3, w - 6, h - 6);
}

export function drawTile(
  ctx: CanvasRenderingContext2D,
  tile: Tile | 'back',
  x: number,
  y: number,
  w = 36,
  h = 52,
  opts: TileDrawOptions = {},
) {
  const { highlighted = false, selected = false, hovered = false } = opts;
  const drawY = hovered ? y - 6 : y;
  const shadowOffset = hovered ? 6 : 2;
  ctx.save();
  if (highlighted) {
    ctx.shadowColor = 'rgba(220, 38, 38, 0.45)';
    ctx.shadowBlur = 10;
    ctx.shadowOffsetY = shadowOffset;
  } else {
    ctx.shadowColor = 'rgba(0,0,0,0.15)';
    ctx.shadowBlur = 3;
    ctx.shadowOffsetY = shadowOffset;
  }
  if (tile === 'back') {
    drawBackPattern(ctx, x, drawY, w, h);
    ctx.restore();
    return;
  }
  ctx.fillStyle = '#faf6ed';
  roundRect(ctx, x, drawY, w, h, 4);
  ctx.fill();
  ctx.shadowColor = 'transparent';
  if (selected) {
    ctx.strokeStyle = '#d4a017';
    ctx.lineWidth = 2;
  } else if (highlighted) {
    ctx.strokeStyle = '#dc2626';
    ctx.lineWidth = 2;
  } else {
    ctx.strokeStyle = '#9ca3af';
    ctx.lineWidth = 1;
  }
  roundRect(ctx, x, drawY, w, h, 4);
  ctx.stroke();
  const padX = 4;
  const padY = 5;
  const cx = x + w / 2;
  const cy = drawY + h / 2;
  if (tile.kind === 'suit') {
    const suit = tile.suit!;
    const val = tile.value!;
    if (suit === 'Wan') {
      ctx.fillStyle = '#1d4ed8';
      ctx.font = `bold ${Math.floor(h * 0.42)}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(WAN_CHARS[val - 1], cx, cy - h * 0.14);
      ctx.font = `bold ${Math.floor(h * 0.24)}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.fillText('萬', cx, cy + h * 0.22);
    } else if (suit === 'Tiao') {
      ctx.fillStyle = '#15803d';
      if (val === 1) {
        ctx.strokeStyle = '#15803d';
        ctx.lineWidth = 2;
        ctx.beginPath();
        const spx = cx;
        const spy = drawY + padY + 4;
        ctx.arc(spx, spy, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(spx, spy + 4);
        ctx.quadraticCurveTo(spx - 6, spy + 14, spx - 3, drawY + h - padY - 2);
        ctx.stroke();
        ctx.beginPath();
        ctx.quadraticCurveTo(spx + 6, spy + 14, spx + 3, drawY + h - padY - 2);
        ctx.stroke();
      } else {
        ctx.font = `bold ${Math.floor(h * 0.5)}px Arial,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(TIAO_CHARS[val - 1], cx, cy - h * 0.1);
        const barW = w * 0.55;
        const barH = Math.max(4, h * 0.09);
        const count = Math.min(val, 4);
        const totalH = count * (barH + 2) - 2;
        let sy = cy + h * 0.12;
        for (let i = 0; i < count; i++) {
          const by = sy + i * (barH + 2) - totalH / 2 + barH / 2;
          ctx.fillRect(cx - barW / 2, by - barH / 2, barW, barH);
        }
      }
    } else if (suit === 'Tong') {
      ctx.fillStyle = '#b91c1c';
      const dots = TONG_DOTS[val - 1];
      const baseR = Math.max(2, Math.min(w, h) * 0.07);
      for (const [px, py] of dots) {
        ctx.beginPath();
        ctx.arc(
          x + padX + px * (w - padX * 2),
          drawY + padY + py * (h - padY * 2),
          baseR,
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }
    }
  } else {
    const honor = tile.honor!;
    if (honor === 'Zhong') {
      ctx.fillStyle = '#dc2626';
      ctx.font = `bold ${Math.floor(h * 0.55)}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(DRAGON_CHARS[honor], cx, cy);
    } else if (honor === 'Fa') {
      ctx.fillStyle = '#15803d';
      ctx.font = `bold ${Math.floor(h * 0.55)}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(DRAGON_CHARS[honor], cx, cy);
    } else if (honor === 'Bai') {
      ctx.strokeStyle = '#1e3a8a';
      ctx.lineWidth = 1.5;
      const bw = w * 0.55;
      const bh = h * 0.5;
      ctx.strokeRect(cx - bw / 2, cy - bh / 2, bw, bh);
      ctx.font = `bold ${Math.floor(h * 0.42)}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.fillStyle = '#1e3a8a';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(DRAGON_CHARS[honor], cx, cy);
    } else {
      ctx.fillStyle = '#111827';
      ctx.font = `bold ${Math.floor(h * 0.6)}px "STKaiti","KaiTi","SimSun",serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(WIND_CHARS[honor], cx, cy);
    }
  }
  ctx.restore();
}

export const ALL_TILE_IDS: string[] = (() => {
  const ids: string[] = [];
  for (const s of ['Wan', 'Tiao', 'Tong'] as const) {
    for (let v = 1; v <= 9; v++) ids.push(`${s}${v}`);
  }
  for (const w of ['East', 'South', 'West', 'North'] as const) ids.push(w);
  for (const d of ['Zhong', 'Fa', 'Bai'] as const) ids.push(d);
  return ids;
})();

export function tileFromId(id: string): Tile {
  if (id.startsWith('Wan') || id.startsWith('Tiao') || id.startsWith('Tong')) {
    const suit = id.slice(0, 4) as 'Wan' | 'Tiao' | 'Tong';
    const value = parseInt(id.slice(4), 10);
    return { id, kind: 'suit', suit, value };
  }
  if (['East', 'South', 'West', 'North'].includes(id)) {
    return { id, kind: 'honor', honor: id as 'East' | 'South' | 'West' | 'North' };
  }
  return { id, kind: 'honor', honor: id as 'Zhong' | 'Fa' | 'Bai' };
}
