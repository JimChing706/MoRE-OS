export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SeatAreas {
  seatIdx: number;
  handArea: Rect;
  meldArea: Rect;
  discardArea: Rect;
  labelPoint: { x: number; y: number };
}

export function seatRect(
  seatIdx: number,
  canvasW: number,
  canvasH: number,
): SeatAreas {
  const pad = Math.round(Math.min(canvasW, canvasH) * 0.03);
  const feltMargin = Math.max(10, Math.min(canvasW, canvasH) * 0.04);
  const feltX = feltMargin;
  const feltY = feltMargin;
  const feltW = canvasW - feltMargin * 2;
  const feltH = canvasH - feltMargin * 2;
  const handH = Math.min(80, canvasH * 0.16);
  const sideW = Math.min(90, canvasW * 0.14);
  const meldH = Math.min(44, canvasH * 0.08);
  if (seatIdx === 0) {
    return {
      seatIdx: 0,
      handArea: {
        x: feltX + feltW * 0.18,
        y: feltY + feltH - handH - pad,
        w: feltW * 0.64,
        h: handH,
      },
      meldArea: {
        x: feltX + feltW * 0.18,
        y: feltY + feltH - handH - meldH - pad - 4,
        w: feltW * 0.64,
        h: meldH,
      },
      discardArea: {
        x: feltX + feltW * 0.22,
        y: feltY + feltH * 0.3,
        w: feltW * 0.56,
        h: feltH * 0.32,
      },
      labelPoint: {
        x: feltX + feltW / 2,
        y: feltY + feltH - handH - meldH - pad - 10,
      },
    };
  }
  if (seatIdx === 1) {
    return {
      seatIdx: 1,
      handArea: {
        x: feltX + feltW - sideW - pad,
        y: feltY + feltH * 0.2,
        w: sideW,
        h: feltH * 0.5,
      },
      meldArea: {
        x: feltX + feltW - sideW - meldH - pad - 4,
        y: feltY + feltH * 0.2,
        w: meldH,
        h: feltH * 0.5,
      },
      discardArea: {
        x: feltX + feltW * 0.22,
        y: feltY + feltH * 0.3,
        w: feltW * 0.56,
        h: feltH * 0.32,
      },
      labelPoint: {
        x: feltX + feltW - sideW - meldH - pad - 18,
        y: feltY + feltH * 0.08,
      },
    };
  }
  if (seatIdx === 2) {
    return {
      seatIdx: 2,
      handArea: {
        x: feltX + feltW * 0.18,
        y: feltY + pad,
        w: feltW * 0.64,
        h: handH,
      },
      meldArea: {
        x: feltX + feltW * 0.18,
        y: feltY + handH + pad + 4,
        w: feltW * 0.64,
        h: meldH,
      },
      discardArea: {
        x: feltX + feltW * 0.22,
        y: feltY + feltH * 0.3,
        w: feltW * 0.56,
        h: feltH * 0.32,
      },
      labelPoint: {
        x: feltX + feltW / 2,
        y: feltY + handH + meldH + pad + 26,
      },
    };
  }
  return {
    seatIdx: 3,
    handArea: {
      x: feltX + pad,
      y: feltY + feltH * 0.2,
      w: sideW,
      h: feltH * 0.5,
    },
    meldArea: {
      x: feltX + sideW + pad + 4,
      y: feltY + feltH * 0.2,
      w: meldH,
      h: feltH * 0.5,
    },
    discardArea: {
      x: feltX + feltW * 0.22,
      y: feltY + feltH * 0.3,
      w: feltW * 0.56,
      h: feltH * 0.32,
    },
    labelPoint: {
      x: feltX + sideW + meldH + pad + 18,
      y: feltY + feltH * 0.08,
    },
  };
}

export function centerSquare(canvasW: number, canvasH: number): Rect {
  const s = Math.min(canvasW, canvasH) * 0.1;
  return {
    x: (canvasW - s) / 2,
    y: (canvasH - s) / 2,
    w: s,
    h: s,
  };
}

export function feltRect(canvasW: number, canvasH: number): Rect {
  const m = Math.max(10, Math.min(canvasW, canvasH) * 0.04);
  return { x: m, y: m, w: canvasW - m * 2, h: canvasH - m * 2 };
}

export function discardGrid(
  discardArea: Rect,
  cols = 12,
  rows = 8,
): { cellW: number; cellH: number; gapX: number; gapY: number } {
  const gapX = 2;
  const gapY = 2;
  const cellW = (discardArea.w - gapX * (cols - 1)) / cols;
  const cellH = (discardArea.h - gapY * (rows - 1)) / rows;
  return { cellW, cellH, gapX, gapY };
}
