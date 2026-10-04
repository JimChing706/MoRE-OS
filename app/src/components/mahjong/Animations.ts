export type EasingFn = (t: number) => number;

export const easeOutQuad: EasingFn = (t) => 1 - (1 - t) * (1 - t);

export const easeOutCubic: EasingFn = (t) => 1 - Math.pow(1 - t, 3);

export const easeInOutQuad: EasingFn = (t) =>
  t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

export const easeOutBounce: EasingFn = (t) => {
  const n1 = 7.5625;
  const d1 = 2.75;
  if (t < 1 / d1) {
    return n1 * t * t;
  }
  if (t < 2 / d1) {
    const x = t - 1.5 / d1;
    return n1 * x * x + 0.75;
  }
  if (t < 2.5 / d1) {
    const x = t - 2.25 / d1;
    return n1 * x * x + 0.9375;
  }
  const x = t - 2.625 / d1;
  return n1 * x * x + 0.984375;
};

export type KeyframeMap<T extends number | string> = Record<T, number>;

export interface AnimationOptions<T extends number | string> {
  keyframes: KeyframeMap<T>;
  duration: number;
  easing?: EasingFn;
  onUpdate: (values: Record<T, number>, progress: number) => void;
  onEnd?: () => void;
}

interface ActiveAnimation {
  elapsed: number;
  duration: number;
  easing: EasingFn;
  keys: string[];
  startVals: number[];
  endVals: number[];
  onUpdate: (values: Record<string, number>, progress: number) => void;
  onEnd?: () => void;
  done: boolean;
}

export class AnimationQueue {
  private anims: Map<string, ActiveAnimation> = new Map();

  play<T extends string | number>(opts: AnimationOptions<T>) {
    const { keyframes, duration, easing = easeOutQuad, onUpdate, onEnd } = opts;
    const keys = Object.keys(keyframes).sort();
    const id = `anim_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const startVals: number[] = [];
    const endVals: number[] = [];
    for (const k of keys) {
      startVals.push(0);
      endVals.push(keyframes[k as keyof typeof keyframes]);
    }
    this.anims.set(id, {
      elapsed: 0,
      duration,
      easing,
      keys,
      startVals,
      endVals,
      onUpdate: onUpdate as unknown as (
        values: Record<string, number>,
        progress: number,
      ) => void,
      onEnd,
      done: false,
    });
    return id;
  }

  stop(id: string) {
    this.anims.delete(id);
  }

  clear() {
    this.anims.clear();
  }

  onTick(dtMs: number) {
    const finished: string[] = [];
    for (const [id, a] of this.anims) {
      a.elapsed += dtMs;
      const t = Math.min(1, a.elapsed / Math.max(1, a.duration));
      const e = a.easing(t);
      const values: Record<string, number> = {};
      for (let i = 0; i < a.keys.length; i++) {
        values[a.keys[i]] =
          a.startVals[i] + (a.endVals[i] - a.startVals[i]) * e;
      }
      a.onUpdate(values, t);
      if (t >= 1 && !a.done) {
        a.done = true;
        finished.push(id);
        if (a.onEnd) {
          try {
            a.onEnd();
          } catch {
            /* ignore */
          }
        }
      }
    }
    for (const id of finished) this.anims.delete(id);
  }

  get activeCount() {
    return this.anims.size;
  }
}
