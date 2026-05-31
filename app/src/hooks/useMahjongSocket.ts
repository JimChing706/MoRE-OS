import { useEffect, useRef, useState, useCallback } from 'react';

export interface MahjongTile {
  suit: string;
  value: number;
  label: string;
}

export interface MahjongPlayer {
  id: string;
  name: string;
  seat: number;
  score: number;
  is_ready: boolean;
  is_online: boolean;
  discards: MahjongTile[];
  calls: Array<{ type: string; tiles: MahjongTile[]; from_seat: number }>;
  hand_count: number;
  hand?: MahjongTile[];
}

export interface MahjongRoom {
  id: string;
  name: string;
  host_id: string;
  rule: string;
  max_players: number;
  player_count: number;
  players: MahjongPlayer[];
  phase: string;
  current_player_seat: number;
  last_discard: MahjongTile | null;
  round: number;
  dealer_seat: number;
  wall_remaining: number;
  dora_indicators: MahjongTile[];
  messages: Array<{ type: string; player: string; action: string; time: string }>;
  is_player: boolean;
}

export interface MahjongMessage {
  action: string;
  room?: MahjongRoom;
  message?: any;
  tile?: MahjongTile;
  result?: any;
  seat?: number;
  error?: string;
}

const WS_BASE = `ws://${import.meta.env.VITE_API_BASE?.replace(/^https?:\/\//, '') || 'localhost:8015'}/ws/mahjong`;

export function useMahjongSocket(playerId: string, playerName: string) {
  const [connected, setConnected] = useState(false);
  const [room, setRoom] = useState<MahjongRoom | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Array<{ type: string; player: string; action: string; time: string }>>([]);
  const [lastAction, setLastAction] = useState<string>('');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_BASE);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setError(null);
      // Send identity + any pending join
      ws.send(JSON.stringify({
        action: 'join',
        data: { player_id: playerId, player_name: playerName }
      }));
    };

    ws.onmessage = (event) => {
      try {
        const msg: MahjongMessage = JSON.parse(event.data);
        if (msg.action === 'sync' && msg.room) {
          setRoom(msg.room);
          if (msg.room.messages) {
            setMessages(msg.room.messages);
          }
        } else if (msg.action === 'join') {
          setLastAction('joined');
        } else if (msg.action === 'draw' && msg.tile) {
          setLastAction('drawn');
        } else if (msg.action === 'call') {
          setLastAction('called');
        } else if (msg.action === 'chat' && msg.message) {
          setMessages(prev => [...prev, msg.message].slice(-100));
        } else if (msg.action === 'error') {
          setError(msg.error || 'Unknown error');
        }
      } catch (e) {
        console.error('WS parse error:', e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Reconnect after 2s
      reconnectRef.current = setTimeout(() => connect(), 2000);
    };

    ws.onerror = () => {
      setError('WebSocket connection error');
    };
  }, [playerId, playerName]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((action: string, data?: Record<string, any>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action, data: { ...data, player_id: playerId } }));
    }
  }, [playerId]);

  const joinRoom = useCallback((roomId: string) => {
    send('join', { room_id: roomId });
  }, [send]);

  const leaveRoom = useCallback(() => {
    send('leave');
    setRoom(null);
  }, [send]);

  const readyUp = useCallback((roomId: string) => {
    send('ready', { room_id: roomId });
  }, [send]);

  const startGame = useCallback((roomId: string) => {
    send('start', { room_id: roomId });
  }, [send]);

  const discardTile = useCallback((tileIdx: number) => {
    send('discard', { tile_idx: tileIdx });
  }, [send]);

  const drawTile = useCallback(() => {
    send('draw');
  }, [send]);

  const makeCall = useCallback((callType: string, tileData?: any) => {
    send('call', { call_type: callType, tile_data: tileData });
  }, [send]);

  const passCall = useCallback(() => {
    send('call_response', { call_type: 'pass' });
  }, [send]);

  const sendChat = useCallback((text: string, roomId: string) => {
    send('chat', { text, room_id: roomId });
  }, [send]);

  return {
    connected,
    room,
    error,
    messages,
    lastAction,
    joinRoom,
    leaveRoom,
    readyUp,
    startGame,
    discardTile,
    drawTile,
    makeCall,
    passCall,
    sendChat,
  };
}
