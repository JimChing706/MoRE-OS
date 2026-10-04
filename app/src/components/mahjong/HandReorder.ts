export function reorderPermutation<T>(
  oldOrder: T[],
  dragIdx: number,
  insertAt: number,
): { items: T[]; perm: number[] } {
  const n = oldOrder.length;
  const clampedDrag = Math.max(0, Math.min(n - 1, dragIdx));
  let target = insertAt;
  if (target > clampedDrag) target -= 1;
  target = Math.max(0, Math.min(n - 1, target));
  const items = oldOrder.slice();
  const [moved] = items.splice(clampedDrag, 1);
  items.splice(target, 0, moved);
  const oldToNew = new Map<number, number>();
  for (let i = 0; i < n; i++) {
    if (i < clampedDrag) oldToNew.set(i, i < target ? i : i + 1);
    else if (i === clampedDrag) oldToNew.set(i, target);
    else oldToNew.set(i, i <= target ? i - 1 : i);
  }
  const perm: number[] = [];
  for (let i = 0; i < n; i++) perm.push(oldToNew.get(i) ?? i);
  return { items, perm };
}

export function applyPermutation<T>(items: T[], perm: number[]): T[] {
  const out: T[] = new Array(items.length);
  for (let i = 0; i < items.length; i++) {
    out[perm[i]] = items[i];
  }
  return out;
}
