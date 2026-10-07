import { useEffect, useRef, useState, useCallback } from 'react';
import type {
  GameState,
  Tile,
  MeldKind,
  Ruleset,
  SeatInfo,
  Meld,
  HuResult,
} from '@/types/morev3';
import { tileFromId } from '@/components/mahjong/TileRenderer';

const WS_HOST =
  import.meta.env.VITE_WS_MAHJONG_HOST || 'localhost:9527';

export interface UseMahjongSocketHandlers {
  onStateSnapshot?: (state: GameState) => void;
  onEventDraw?: (seatIdx: number, tile: Tile, actionId: string) => void;
  onEventDiscard?: (seatIdx: number, tile: Tile, actionId: string) => void;
  onEventChow?: (seatIdx: number, meld: Meld, actionId: string) => void;
  onEventPung?: (seatIdx: number, meld: Meld, actionId: string) => void;
  onEventKong?: (seatIdx: number, meld: Meld, actionId: string) => void;
  onEventHu?: (result: HuResult, actionId: string) => void;
  onEventDrawGame?: (actionId: string) => void;
  onEventCascade?: (level: number, actionId: string) => void;
  onEventCallOpportunity?: (
    seatIdx: number,
    options: Array<{ kind: MeldKind | 'hu'; tile: Tile }>,
    actionId: string,
  ) => void;
  onError?: (msg: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

const EMPTY_STATE: GameState = {
  roomId: '',
  ruleset: 'guangdong',
  phase: 'waiting',
  currentTurn: 0,
  lastActionId: '',
  lastDiscard: null,
  wallRemaining: 0,
  round: 1,
  dealerSeat: 0,
  seats: [],
  doraIndicators: [],
  pendingCalls: [],
  huResult: null,
};

function parseTile(raw: unknown): Tile | null {
  if (!raw) return null;
  if (typeof raw === 'string') return tileFromId(raw);
  const obj = raw as Record<string, unknown>;
  if (typeof obj.id === 'string') return tileFromId(obj.id);
  const suit = obj.suit as string | undefined;
  const value = obj.value as number | undefined;
  const honor = obj.honor as string | undefined;
  if (suit && typeof value === 'number') {
    const map: Record<string, 'Wan' | 'Tiao' | 'Tong'> = {
      Wan: 'Wan',
      MAN: 'Wan',
      wan: 'Wan',
      Tiao: 'Tiao',
      TIAO: 'Tiao',
      SOU: 'Tiao',
      sou: 'Tiao',
      Tong: 'Tong',
      TONG: 'Tong',
      PIN: 'Tong',
      pin: 'Tong',
    };
    const s = map[suit] || 'Wan';
    return tileFromId(`${s}${value}`);
  }
  if (honor) {
    const map: Record<string, string> = {
      East: 'East',
      EAST: 'East',
      east: 'East',
      東: 'East',
      South: 'South',
      SOUTH: 'South',
      south: 'South',
      南: 'South',
      West: 'West',
      WEST: 'West',
      west: 'West',
      西: 'West',
      North: 'North',
      NORTH: 'North',
      north: 'North',
      北: 'North',
      Zhong: 'Zhong',
      ZHONG: 'Zhong',
      zhong: 'Zhong',
      中: 'Zhong',
      Fa: 'Fa',
      FA: 'Fa',
      fa: 'Fa',
      發: 'Fa',
      发: 'Fa',
      Bai: 'Bai',
      BAI: 'Bai',
      bai: 'Bai',
      白: 'Bai',
    };
    const h = map[honor];
    if (h) return tileFromId(h);
  }
  if (typeof obj.label === 'string') {
    return tileFromId(obj.label);
  }
  return null;
}

function parseSeat(raw: Record<string, unknown>, seatIdx: number): SeatInfo {
  const handRaw = (raw.hand as Array<unknown>) || [];
  const hand: Tile[] = handRaw.map((t) => parseTile(t) ?? tileFromId('Wan1')).filter(Boolean);
  const discardsRaw = (raw.discards as Array<unknown>) || [];
  const discards: Tile[] = discardsRaw
    .map((t) => parseTile(t))
    .filter((t): t is Tile => Boolean(t));
  const meldsRaw = (raw.melds as Array<Record<string, unknown>>) || (raw.calls as Array<Record<string, unknown>>) || [];
  const melds: Meld[] = meldsRaw
    .map((m) => {
      const kindRaw = String(m.kind || m.type || 'pung');
      const kindMap: Record<string, MeldKind> = {
        chow: 'chow',
        chi: 'chow',
        CHOW: 'chow',
        pung: 'pung',
        peng: 'pung',
        PUNG: 'pung',
        kong: 'kong',
        gang: 'kong',
        KONG: 'kong',
        concealed_kong: 'concealed_kong',
        concealedKong: 'concealed_kong',
        angang: 'concealed_kong',
      };
      const tilesRaw = (m.tiles as Array<unknown>) || [];
      const tiles: Tile[] = tilesRaw
        .map((t) => parseTile(t))
        .filter((t): t is Tile => Boolean(t));
      if (tiles.length === 0) return null;
      return {
        kind: kindMap[kindRaw] || 'pung',
        tiles,
        fromSeat: typeof m.fromSeat === 'number' ? m.fromSeat : typeof m.from_seat === 'number' ? m.from_seat : seatIdx,
      } as Meld;
    })
    .filter((m): m is Meld => Boolean(m));
  return {
    seatIdx,
    playerUuid: String(raw.playerUuid || raw.player_id || raw.id || `p${seatIdx}`),
    playerName: String(raw.playerName || raw.name || `玩家${seatIdx + 1}`),
    score: typeof raw.score === 'number' ? raw.score : 0,
    hand,
    discards,
    melds,
    isDealer: Boolean(raw.isDealer || raw.is_dealer),
    isOnline: typeof raw.isOnline === 'boolean' ? raw.isOnline : typeof raw.is_online === 'boolean' ? raw.is_online : true,
    isAI: Boolean(raw.isAI || raw.is_ai),
  };
}

function parseState(raw: Record<string, unknown>): GameState {
  const seatsRaw = (raw.seats as Array<Record<string, unknown>>) ||
    (raw.players as Array<Record<string, unknown>>) ||
    [];
  const rulesetRaw = String(raw.ruleset || raw.rule || 'guangdong');
  const rulesetMap: Record<string, Ruleset> = {
    guobiao: 'guobiao',
    GB: 'guobiao',
    国标: 'guobiao',
    sichuan_xuemen: 'sichuan_xuemen',
    sichuan: 'sichuan_xuemen',
    SICHUAN: 'sichuan_xuemen',
    四川: 'sichuan_xuemen',
    血战: 'sichuan_xuemen',
    guangdong: 'guangdong',
    GD: 'guangdong',
    广东: 'guangdong',
  };
  const phaseRaw = String(raw.phase || 'waiting');
  const phaseMap: Record<string, GameState['phase']> = {
    waiting: 'waiting',
    WAITING: 'waiting',
    waiting_ready: 'waiting',
    dealing: 'dealing',
    DEALING: 'dealing',
    playing: 'playing',
    PLAYING: 'playing',
    calling: 'calling',
    CALLING: 'calling',
    call: 'calling',
    cascade: 'cascade',
    CASCADE: 'cascade',
    ended: 'ended',
    ENDED: 'ended',
    end: 'ended',
    finished: 'ended',
  };
  const lastDiscardRaw = raw.lastDiscard || raw.last_discard;
  let lastDiscard: GameState['lastDiscard'] = null;
  if (lastDiscardRaw && typeof lastDiscardRaw === 'object') {
    const ld = lastDiscardRaw as Record<string, unknown>;
    const t = parseTile(ld.tile);
    const seatIdx = typeof ld.seatIdx === 'number' ? ld.seatIdx : typeof ld.seat === 'number' ? ld.seat : typeof ld.seat_idx === 'number' ? ld.seat_idx : 0;
    if (t) lastDiscard = { tile: t, seatIdx };
  }
  const doraRaw = (raw.doraIndicators || raw.dora_indicators || []) as Array<unknown>;
  const doraIndicators: Tile[] = doraRaw
    .map((t) => parseTile(t))
    .filter((t): t is Tile => Boolean(t));
  const pendingRaw = (raw.pendingCalls || raw.pending_calls || raw.availableCalls || []) as Array<
    Record<string, unknown>
  >;
  const pendingCalls: GameState['pendingCalls'] = pendingRaw
    .map((c) => {
      const t = parseTile(c.tile);
      if (!t) return null;
      const seatIdx = typeof c.seatIdx === 'number' ? c.seatIdx : typeof c.seat === 'number' ? c.seat : 0;
      const kindRaw = String(c.callKind || c.kind || c.type || 'hu');
      const kindMap: Record<string, MeldKind | 'hu'> = {
        chow: 'chow',
        chi: 'chow',
        pung: 'pung',
        peng: 'pung',
        kong: 'kong',
        gang: 'kong',
        concealed_kong: 'concealed_kong',
        hu: 'hu',
        ron: 'hu',
        tsumo: 'hu',
      };
      return { seatIdx, callKind: kindMap[kindRaw] || 'hu', tile: t };
    })
    .filter((c): c is NonNullable<typeof c> => Boolean(c));
  const huRaw = raw.huResult || raw.hu_result || raw.result;
  let huResult: HuResult | null = null;
  if (huRaw && typeof huRaw === 'object') {
    const hr = huRaw as Record<string, unknown>;
    const winnerSeat = typeof hr.winnerSeat === 'number' ? hr.winnerSeat : typeof hr.winner === 'number' ? hr.winner : 0;
    const handRaw = (hr.winnerHand || hr.hand || []) as Array<unknown>;
    const winnerHand: Tile[] = handRaw
      .map((t) => parseTile(t))
      .filter((t): t is Tile => Boolean(t));
    const fanTypesRaw = (hr.fanTypes || hr.fan_types || hr.yakus || []) as Array<unknown>;
    const fanTypes: string[] = fanTypesRaw.map((v) => String(v));
    const fanCount = typeof hr.fanCount === 'number' ? hr.fanCount : typeof hr.fan === 'number' ? hr.fan : fanTypes.length;
    const deltaRaw = (hr.deltaScores || hr.delta_scores || hr.deltas || []) as Array<unknown>;
    const deltaScores: number[] = deltaRaw.map((v) => (typeof v === 'number' ? v : 0));
    while (deltaScores.length < 4) deltaScores.push(0);
    const isRon = Boolean(hr.isRon || hr.is_ron);
    const discarderSeatRaw = hr.discarderSeat ?? hr.discarder ?? null;
    const discarderSeat = typeof discarderSeatRaw === 'number' ? discarderSeatRaw : null;
    huResult = { winnerSeat, winnerHand, fanTypes, fanCount, deltaScores, isRon, discarderSeat };
  }
  return {
    roomId: String(raw.roomId || raw.room_id || raw.id || ''),
    ruleset: rulesetMap[rulesetRaw] || 'guangdong',
    phase: phaseMap[phaseRaw] || 'waiting',
    currentTurn: typeof raw.currentTurn === 'number' ? raw.currentTurn : typeof raw.current_player_seat === 'number' ? raw.current_player_seat : 0,
    lastActionId: String(raw.lastActionId || raw.last_action_id || ''),
    lastDiscard,
    wallRemaining: typeof raw.wallRemaining === 'number' ? raw.wallRemaining : typeof raw.wall_remaining === 'number' ? raw.wall_remaining : 0,
    round: typeof raw.round === 'number' ? raw.round : 1,
    dealerSeat: typeof raw.dealerSeat === 'number' ? raw.dealerSeat : typeof raw.dealer_seat === 'number' ? raw.dealer_seat : 0,
    seats: seatsRaw.map((s, i) => parseSeat(s, i)),
    doraIndicators,
    pendingCalls,
    huResult,
  };
}

export function useMahjongSocket(roomId: string, playerUuid: string, handlers: UseMahjongSocketHandlers = {}) {
  const [gameState, setGameState] = useState<GameState>(EMPTY_STATE);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastActionIdRef = useRef<string>('');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // connect 需要在自身的重连定时器里回调自己；用 ref 间接引用，
  // 既避免"先使用后声明"，也保证回调拿到的是最新一版 connect。
  const connectRef = useRef<(() => void) | null>(null);
  const handlersRef = useRef(handlers);
  // 同步最新 handlers / connect：放入 effect（在 render 阶段写 ref 会破坏
  // React Compiler 的规则，也会让并发渲染读到中间态）。
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);
  const connect = useCallback(() => {
    const url = `ws://${WS_HOST}/ws/mahjong/${roomId}?player=${encodeURIComponent(playerUuid)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      setError(null);
      handlersRef.current.onConnect?.();
    };
    ws.onmessage = (ev) => {
      try {
        const raw = JSON.parse(String(ev.data));
        const msg = typeof raw === 'object' && raw ? (raw as Record<string, unknown>) : null;
        if (!msg) return;
        const action = String(msg.action || msg.type || '');
        const actionId = String(msg.actionId || msg.action_id || `a_${Date.now()}_${Math.random()}`);
        if (lastActionIdRef.current === actionId) return;
        lastActionIdRef.current = actionId;
        if (action === 'state' || action === 'sync' || action === 'snapshot') {
          const s = parseState((msg.state || msg.room || msg) as Record<string, unknown>);
          setGameState(s);
          handlersRef.current.onStateSnapshot?.(s);
          return;
        }
        const seatIdxRaw = msg.seatIdx ?? msg.seat ?? msg.seat_idx;
        const seatIdx = typeof seatIdxRaw === 'number' ? seatIdxRaw : 0;
        const tile = parseTile(msg.tile);
        if (action === 'draw' || action === 'event_draw') {
          if (tile) handlersRef.current.onEventDraw?.(seatIdx, tile, actionId);
        } else if (action === 'discard' || action === 'event_discard') {
          if (tile) handlersRef.current.onEventDiscard?.(seatIdx, tile, actionId);
        } else if (action === 'chow' || action === 'chi' || action === 'event_chow') {
          const meldRaw = (msg.meld || msg.call || {}) as Record<string, unknown>;
          const melds = parseSeat({ melds: [meldRaw] }, seatIdx).melds;
          if (melds[0]) handlersRef.current.onEventChow?.(seatIdx, melds[0], actionId);
        } else if (action === 'pung' || action === 'peng' || action === 'event_pung') {
          const meldRaw = (msg.meld || msg.call || {}) as Record<string, unknown>;
          const melds = parseSeat({ melds: [meldRaw] }, seatIdx).melds;
          if (melds[0]) handlersRef.current.onEventPung?.(seatIdx, melds[0], actionId);
        } else if (action === 'kong' || action === 'gang' || action === 'event_kong') {
          const meldRaw = (msg.meld || msg.call || {}) as Record<string, unknown>;
          const melds = parseSeat({ melds: [meldRaw] }, seatIdx).melds;
          if (melds[0]) handlersRef.current.onEventKong?.(seatIdx, melds[0], actionId);
        } else if (action === 'hu' || action === 'ron' || action === 'tsumo' || action === 'event_hu') {
          const st = parseState((msg.state || msg.result || {}) as Record<string, unknown>);
          if (st.huResult) handlersRef.current.onEventHu?.(st.huResult, actionId);
        } else if (action === 'draw_game' || action === 'ryukyoku' || action === 'event_draw') {
          handlersRef.current.onEventDrawGame?.(actionId);
        } else if (action === 'cascade' || action === 'event_cascade') {
          const level = typeof msg.level === 'number' ? msg.level : 1;
          handlersRef.current.onEventCascade?.(level, actionId);
        } else if (action === 'call_opportunity' || action === 'pending_calls' || action === 'available_calls') {
          const optsRaw = (msg.options || msg.calls || []) as Array<Record<string, unknown>>;
          const options: Array<{ kind: MeldKind | 'hu'; tile: Tile }> = [];
          for (const o of optsRaw) {
            const t = parseTile(o.tile);
            if (!t) continue;
            const kindRaw = String(o.kind || o.type || o.call || 'hu');
            const map: Record<string, MeldKind | 'hu'> = {
              chow: 'chow', chi: 'chow',
              pung: 'pung', peng: 'pung',
              kong: 'kong', gang: 'kong',
              concealed_kong: 'concealed_kong',
              hu: 'hu', ron: 'hu', tsumo: 'hu',
            };
            options.push({ kind: map[kindRaw] || 'hu', tile: t });
          }
          handlersRef.current.onEventCallOpportunity?.(seatIdx, options, actionId);
        } else if (action === 'error') {
          const m = String(msg.error || msg.message || 'Unknown error');
          setError(m);
          handlersRef.current.onError?.(m);
        } else if (action === 'state_update' || action === 'update') {
          setGameState((prev) => {
            const next = parseState((msg.state || msg) as Record<string, unknown>);
            return { ...prev, ...next };
          });
        }
        if (msg.state) {
          const s = parseState((msg.state || {}) as Record<string, unknown>);
          setGameState(s);
        }
      } catch (e) {
        console.error('WS parse error:', e);
      }
    };
    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      handlersRef.current.onDisconnect?.();
      reconnectRef.current = setTimeout(() => connectRef.current?.(), 2000);
    };
    ws.onerror = () => {
      setError('WebSocket connection error');
    };
  }, [roomId, playerUuid]);
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);
  useEffect(() => {
    if (!roomId || !playerUuid) return;
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect, roomId, playerUuid]);
  const send = useCallback((payload: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);
  const sendDiscard = useCallback(
    (tileIdx: number) => send({ action: 'discard', tile_idx: tileIdx }),
    [send],
  );
  const sendChow = useCallback(
    (tileId?: string, comboTiles?: string[]) =>
      send({ action: 'call', call_type: 'chow', tile_id: tileId, combo: comboTiles }),
    [send],
  );
  const sendPung = useCallback(
    () => send({ action: 'call', call_type: 'pung' }),
    [send],
  );
  const sendKong = useCallback(
    () => send({ action: 'call', call_type: 'kong' }),
    [send],
  );
  const sendRon = useCallback(
    () => send({ action: 'call', call_type: 'hu' }),
    [send],
  );
  const sendTsumo = useCallback(
    () => send({ action: 'call', call_type: 'tsumo' }),
    [send],
  );
  const sendSkip = useCallback(
    () => send({ action: 'call_response', call_type: 'pass' }),
    [send],
  );
  const sendReady = useCallback(
    () => send({ action: 'ready' }),
    [send],
  );
  const sendStart = useCallback(
    (ruleset?: Ruleset, minFan?: number, aiSeats?: number[]) =>
      send({ action: 'start', ruleset, min_fan: minFan, ai_seats: aiSeats }),
    [send],
  );
  const sendReorder = useCallback(
    (perm: number[]) => send({ action: 'reorder', perm }),
    [send],
  );
  return {
    gameState,
    connected,
    error,
    sendDiscard,
    sendChow,
    sendPung,
    sendKong,
    sendRon,
    sendTsumo,
    sendSkip,
    sendReady,
    sendStart,
    sendReorder,
  };
}
