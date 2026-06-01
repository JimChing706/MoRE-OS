import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useMahjongSocket, type MahjongTile, type MahjongRoom } from '@/hooks/useMahjongSocket';
import { 
  UserPlus, X, MessageSquare, 
  Gamepad2, Eye, Wifi, WifiOff
} from 'lucide-react';

const API_BASE = `${import.meta.env.VITE_API_BASE || 'http://localhost:8011'}/api/v1`;

function generatePlayerId(name: string): string {
  return `p_${name}_${Date.now().toString(36)}`;
}

// 牌面渲染
function TileCard({ tile, selected, onClick }: { tile: MahjongTile; selected?: boolean; onClick?: () => void }) {
  const suitColor = {
    MAN: 'text-red-600',
    PIN: 'text-blue-600',
    SOU: 'text-green-600',
    HONOR: 'text-purple-600',
  }[tile.suit] || 'text-gray-600';

  return (
    <div
      onClick={onClick}
      className={`w-10 h-14 rounded border flex flex-col items-center justify-center cursor-pointer transition-all select-none
        ${selected ? 'border-orange-500 bg-orange-50 scale-105' : 'border-gray-300 bg-white hover:border-orange-300'}`}
    >
      <span className={`text-xs font-bold ${suitColor}`}>{tile.label}</span>
    </div>
  );
}

// 迷你牌（弃牌区用）
function MiniTile({ tile }: { tile: MahjongTile }) {
  return (
    <div className="w-6 h-8 rounded border border-gray-400 bg-white flex items-center justify-center text-[10px] font-bold text-gray-700">
      {tile.label}
    </div>
  );
}

export default function MahjongGame() {
  const [playerName, setPlayerName] = useState('');
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [playerId, setPlayerId] = useState('');
  const [rooms, setRooms] = useState<MahjongRoom[]>([]);
  const [isCreatingRoom, setIsCreatingRoom] = useState(false);
  const [newRoomName, setNewRoomName] = useState('');
  const [selectedTileIdx, setSelectedTileIdx] = useState<number | null>(null);
  const [chatText, setChatText] = useState('');
  const [fetchError, setFetchError] = useState<string | null>(null);

  const {
    connected,
    room,
    error: wsError,
    messages,
    joinRoom,
    leaveRoom,
    readyUp,
    startGame,
    discardTile,
    drawTile,
    makeCall,
    passCall,
    sendChat,
  } = useMahjongSocket(playerId, playerName);

  // Fetch room list from REST API
  const fetchRooms = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/mahjong/rooms`);
      const data = await res.json();
      setRooms(data.rooms || []);
      setFetchError(null);
    } catch (e) {
      setFetchError('无法连接到游戏服务器');
    }
  }, []);

  useEffect(() => {
    if (isLoggedIn) {
      fetchRooms();
      const interval = setInterval(fetchRooms, 3000);
      return () => clearInterval(interval);
    }
  }, [isLoggedIn, fetchRooms]);

  // Login
  const handleLogin = () => {
    const name = playerName.trim();
    if (name) {
      setPlayerId(generatePlayerId(name));
      setIsLoggedIn(true);
    }
  };

  // Create room via REST API
  const handleCreateRoom = async () => {
    if (!newRoomName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/mahjong/rooms`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newRoomName,
          host_id: playerId,
          host_name: playerName,
          rule: 'guangdong',
        }),
      });
      const data = await res.json();
      if (data.room) {
        setIsCreatingRoom(false);
        setNewRoomName('');
        joinRoom(data.room.id);
        fetchRooms();
      }
    } catch (e) {
      setFetchError('创建房间失败');
    }
  };

  // Join room via REST + WS
  const handleJoinRoom = async (roomId: string) => {
    try {
      await fetch(`${API_BASE}/mahjong/rooms/${roomId}/join`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: playerId, player_name: playerName }),
      });
      joinRoom(roomId);
      fetchRooms();
    } catch (e) {
      setFetchError('加入房间失败');
    }
  };

  // Spectate
  const handleSpectate = (roomId: string) => {
    joinRoom(roomId);
  };

  // Leave
  const handleLeaveRoom = async () => {
    if (room?.id) {
      try {
        await fetch(`${API_BASE}/mahjong/rooms/${room.id}/leave`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ player_id: playerId }),
        });
      } catch { /* ignore */ }
    }
    leaveRoom();
    fetchRooms();
  };

  // Ready
  const handleReady = () => {
    if (room?.id) readyUp(room.id);
  };

  // Start game
  const handleStartGame = () => {
    if (room?.id) startGame(room.id);
  };

  // Discard
  const handleDiscardClick = (tileIdx: number) => {
    if (selectedTileIdx === tileIdx) {
      discardTile(tileIdx);
      setSelectedTileIdx(null);
    } else {
      setSelectedTileIdx(tileIdx);
    }
  };

  // Send chat
  const handleSendChat = () => {
    if (chatText.trim() && room?.id) {
      sendChat(chatText, room.id);
      setChatText('');
    }
  };

  // Get my player data from room
  const myPlayer = room?.players.find(p => p.id === playerId);
  const isHost = room?.host_id === playerId;
  const isMyTurn = myPlayer?.seat === room?.current_player_seat && room?.phase === 'playing';
  const canCall = room?.phase === 'calling' && room?.players.some(p => p.id === playerId && String(p.seat) in (room as any).pending_call?.callers || {});

  if (!isLoggedIn) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl font-bold text-orange-600">MoRE 麻将游戏</CardTitle>
            <CardDescription>请输入您的游戏昵称</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="player-name">游戏昵称</Label>
              <Input id="player-name" placeholder="输入您的游戏昵称" value={playerName} onChange={(e) => setPlayerName(e.target.value)} />
            </div>
          </CardContent>
          <CardFooter>
            <Button className="w-full bg-orange-500 hover:bg-orange-600" onClick={handleLogin} disabled={!playerName.trim()}>
              登录游戏
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // Room lobby
  if (!room) {
    return (
      <div className="min-h-screen bg-gray-100 p-4">
        <header className="bg-white border-b border-gray-200 sticky top-0 z-50 mb-4">
          <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-amber-500 rounded-xl flex items-center justify-center shadow-lg">
                <Gamepad2 className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-gray-900">MoRE 麻将游戏</h1>
                <p className="text-xs text-gray-500">欢迎，{playerName} | {connected ? <span className="text-green-500 flex items-center gap-1 inline-flex"><Wifi className="w-3 h-3" />在线</span> : <span className="text-red-500 flex items-center gap-1 inline-flex"><WifiOff className="w-3 h-3" />离线</span>}</p>
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setIsLoggedIn(false)}>退出登录</Button>
          </div>
        </header>
        <main className="max-w-6xl mx-auto">
          {fetchError && <div className="mb-4 p-3 bg-red-50 text-red-600 rounded-lg text-sm">{fetchError}</div>}
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-gray-900">游戏房间</h2>
            <Dialog open={isCreatingRoom} onOpenChange={setIsCreatingRoom}>
              <DialogTrigger asChild>
                <Button className="bg-orange-500 hover:bg-orange-600"><UserPlus className="w-4 h-4 mr-2" /> 创建房间</Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader><DialogTitle>创建游戏房间</DialogTitle><DialogDescription>输入房间名称</DialogDescription></DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2"><Label>房间名称</Label><Input placeholder="输入房间名称" value={newRoomName} onChange={(e) => setNewRoomName(e.target.value)} /></div>
                  <div className="space-y-2"><Label>游戏规则</Label>
                    <RadioGroup defaultValue="guangdong">
                      <div className="flex items-center space-x-2"><RadioGroupItem value="guangdong" id="rule-guangdong" /><Label htmlFor="rule-guangdong">广东麻将</Label></div>
                    </RadioGroup>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="ghost" onClick={() => setIsCreatingRoom(false)}>取消</Button>
                  <Button className="bg-orange-500 hover:bg-orange-600" onClick={handleCreateRoom} disabled={!newRoomName.trim()}>创建</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {rooms.map((r) => (
              <Card key={r.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">{r.name}</CardTitle>
                    <Badge variant={r.phase === 'waiting' ? 'default' : 'destructive'}>{r.phase === 'waiting' ? '等待中' : '游戏中'}</Badge>
                  </div>
                  <CardDescription>{r.player_count}/{r.max_players} 玩家 | {r.rule === 'guangdong' ? '广东麻将' : r.rule}</CardDescription>
                </CardHeader>
                <CardContent className="pb-2">
                  <div className="flex -space-x-2">
                    {r.players.slice(0, 4).map((p, i) => (
                      <Avatar key={i} className="w-7 h-7 border-2 border-white"><AvatarFallback className="text-[10px] bg-orange-100">{p.name[0]}</AvatarFallback></Avatar>
                    ))}
                  </div>
                </CardContent>
                <CardFooter className="flex gap-2">
                  {r.phase === 'waiting' && r.player_count < r.max_players ? (
                    <Button className="flex-1 bg-orange-500 hover:bg-orange-600" onClick={() => handleJoinRoom(r.id)}>加入房间</Button>
                  ) : (
                    <Button className="flex-1 bg-blue-500 hover:bg-blue-600" onClick={() => handleSpectate(r.id)}><Eye className="w-4 h-4 mr-2" /> 观战</Button>
                  )}
                </CardFooter>
              </Card>
            ))}
            {rooms.length === 0 && (
              <div className="col-span-2 text-center py-12 text-gray-500">暂无房间，点击右上角创建房间开始游戏</div>
            )}
          </div>
        </main>
      </div>
    );
  }

  // In room / playing
  const isPlaying = room.phase === 'playing' || room.phase === 'calling';

  return (
    <div className="min-h-screen bg-gray-100 p-4">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50 mb-4">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-amber-500 rounded-xl flex items-center justify-center shadow-lg">
              <Gamepad2 className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900">{room.name}</h1>
              <p className="text-xs text-gray-500">{playerName} | {connected ? <Wifi className="w-3 h-3 text-green-500 inline" /> : <WifiOff className="w-3 h-3 text-red-500 inline" />} {room.phase === 'waiting' ? '等待中' : room.phase === 'playing' ? '游戏中' : room.phase === 'calling' ? '等待操作' : '已结束'}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {wsError && <span className="text-xs text-red-500">{wsError}</span>}
            <Button variant="ghost" size="sm" onClick={handleLeaveRoom}><X className="w-4 h-4 mr-1" /> 离开房间</Button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto">
        {!isPlaying ? (
          /* Room lobby */
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-gray-900">房间信息</h2>
              <Badge variant="default">等待中</Badge>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-3">玩家列表 ({room.player_count}/{room.max_players})</h3>
                <div className="space-y-3">
                  {room.players.map((player) => (
                    <div key={player.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div className="flex items-center gap-3">
                        <Avatar className="w-8 h-8"><AvatarFallback className="bg-orange-100 text-orange-600">{player.name[0]}</AvatarFallback></Avatar>
                        <div>
                          <p className="font-medium text-sm">{player.name} {player.id === playerId && <span className="text-orange-500 text-xs">(你)</span>}</p>
                          <p className="text-xs text-gray-500">座位: {player.seat + 1} | 分数: {player.score}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {player.id === room.host_id && <Badge variant="outline" className="text-[10px]">房主</Badge>}
                        {player.is_ready ? <Badge className="bg-green-500 text-[10px]">已准备</Badge> : <Badge variant="secondary" className="text-[10px]">未准备</Badge>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-3">游戏设置</h3>
                <div className="space-y-4">
                  <div className="flex items-center justify-between"><span className="text-sm text-gray-600">游戏规则</span><Badge variant="secondary">{room.rule === 'guangdong' ? '广东麻将' : room.rule}</Badge></div>
                  <div className="flex items-center justify-between"><span className="text-sm text-gray-600">房间ID</span><span className="text-xs font-mono text-gray-500">{room.id}</span></div>
                  <Separator />
                  {myPlayer && !myPlayer.is_ready && (
                    <Button className="w-full bg-green-500 hover:bg-green-600" onClick={handleReady}>准备</Button>
                  )}
                  {isHost && (
                    <Button className="w-full bg-orange-500 hover:bg-orange-600" onClick={handleStartGame} disabled={!room.players.every(p => p.is_ready)}>
                      开始游戏 {!room.players.every(p => p.is_ready) && '(等待所有人准备)'}
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Playing */
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Left: Players */}
            <div className="lg:col-span-1 space-y-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-lg">玩家信息</CardTitle></CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {room.players.map((player) => (
                      <div key={player.id} className={`p-3 rounded-lg ${room.current_player_seat === player.seat ? 'bg-orange-50 border border-orange-200' : 'bg-gray-50'}`}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <Avatar className="w-6 h-6"><AvatarFallback className="text-[10px] bg-orange-100">{player.name[0]}</AvatarFallback></Avatar>
                            <span className="text-sm font-medium">{player.name} {player.id === playerId && <span className="text-orange-500 text-[10px]">(你)</span>}</span>
                          </div>
                          <Badge variant={room.current_player_seat === player.seat ? 'default' : 'secondary'} className="text-[10px]">
                            {room.current_player_seat === player.seat ? '当前回合' : '等待'}
                          </Badge>
                        </div>
                        <div className="flex items-center justify-between text-xs text-gray-600">
                          <span>分数: {player.score}</span>
                          <span>手牌: {player.hand_count}张</span>
                        </div>
                        {player.calls.length > 0 && (
                          <div className="flex gap-1 mt-1 flex-wrap">
                            {player.calls.map((c, i) => (
                              <Badge key={i} variant="outline" className="text-[9px]">{c.type === 'peng' ? '碰' : c.type === 'gang' ? '杠' : c.type === 'chi' ? '吃' : c.type}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-lg">游戏信息</CardTitle></CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-gray-600">当前回合</span><span>{room.round} 局</span></div>
                    <div className="flex justify-between"><span className="text-gray-600">庄家</span><span>{room.players[room.dealer_seat]?.name || 'N/A'}</span></div>
                    <div className="flex justify-between"><span className="text-gray-600">剩余牌数</span><span>{room.wall_remaining}张</span></div>
                    <div className="flex justify-between"><span className="text-gray-600">宝牌指示牌</span>
                      <div className="flex gap-1">{room.dora_indicators.map((d, i) => <MiniTile key={i} tile={d} />)}</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Center/Right: Game board + Hand + Chat */}
            <div className="lg:col-span-2 space-y-4">
              {/* Game table */}
              <Card className="bg-green-800 text-white">
                <CardHeader className="pb-2"><CardTitle className="text-lg text-center">麻将桌</CardTitle></CardHeader>
                <CardContent>
                  <div className="aspect-[4/3] relative rounded-lg bg-green-700 p-4">
                    {/* Last discard indicator */}
                    {room.last_discard && (
                      <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-10">
                        <div className="bg-orange-100 rounded-lg p-2 shadow-lg">
                          <p className="text-[10px] text-orange-800 text-center mb-1">最新出牌</p>
                          <TileCard tile={room.last_discard} />
                        </div>
                      </div>
                    )}

                    {/* Player positions */}
                    {room.players.map((p) => {
                      const pos = ['top-4 left-1/2 -translate-x-1/2', 'right-4 top-1/2 -translate-y-1/2', 'bottom-4 left-1/2 -translate-x-1/2', 'left-4 top-1/2 -translate-y-1/2'][p.seat];
                      return (
                        <div key={p.id} className={`absolute ${pos} text-center`}>
                          <div className={`text-sm font-medium ${room.current_player_seat === p.seat ? 'text-yellow-300' : 'text-white'}`}>{p.name}</div>
                          <div className="text-xs opacity-70">{p.hand_count}张</div>
                        </div>
                      );
                    })}

                    {/* Discards */}
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                      <div className="bg-green-900/50 rounded-lg p-3 max-w-[200px]">
                        <div className="grid grid-cols-6 gap-1">
                          {room.players.flatMap(p => p.discards).slice(-18).map((t, i) => (
                            <MiniTile key={i} tile={t} />
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* My hand */}
              {myPlayer?.hand && (
                <Card>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-lg">我的手牌</CardTitle>
                      {isMyTurn && <Badge className="bg-orange-500 animate-pulse">你的回合</Badge>}
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2 justify-center">
                      {myPlayer.hand.map((tile, idx) => (
                        <TileCard key={`${tile.suit}_${tile.value}_${idx}`} tile={tile} selected={selectedTileIdx === idx} onClick={() => handleDiscardClick(idx)} />
                      ))}
                    </div>
                  </CardContent>
                  <CardFooter className="flex flex-wrap gap-2 justify-center">
                    {isMyTurn && (
                      <Button size="sm" className="bg-blue-500 hover:bg-blue-600" onClick={drawTile}>摸牌</Button>
                    )}
                    {canCall && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => makeCall('chi')}>吃</Button>
                        <Button size="sm" variant="outline" onClick={() => makeCall('peng')}>碰</Button>
                        <Button size="sm" variant="outline" onClick={() => makeCall('gang')}>杠</Button>
                        <Button size="sm" className="bg-red-500 hover:bg-red-600" onClick={() => makeCall('hu')}>和</Button>
                        <Button size="sm" variant="ghost" onClick={passCall}>过</Button>
                      </>
                    )}
                  </CardFooter>
                </Card>
              )}

              {/* Chat */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-lg"><MessageSquare className="w-4 h-4 inline mr-1" />聊天</CardTitle></CardHeader>
                <CardContent className="h-48">
                  <ScrollArea className="h-full">
                    <div className="space-y-2">
                      {messages.map((msg, i) => (
                        <div key={i} className="text-xs">
                          <span className="font-medium text-orange-600">{msg.player || msg.type}</span>
                          <span className="text-gray-400 ml-1">{msg.time ? new Date(msg.time).toLocaleTimeString() : ''}</span>
                          <p className="mt-0.5 text-gray-700">{msg.action || (msg as unknown as { text?: string }).text || JSON.stringify(msg)}</p>
                        </div>
                      ))}
                      {messages.length === 0 && <div className="text-center text-gray-400 text-xs py-8">暂无消息</div>}
                    </div>
                  </ScrollArea>
                </CardContent>
                <CardFooter>
                  <Input placeholder="输入消息..." className="flex-1 text-sm" value={chatText} onChange={(e) => setChatText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSendChat()} />
                  <Button className="ml-2 bg-orange-500 hover:bg-orange-600" size="sm" onClick={handleSendChat}><MessageSquare className="w-3 h-3 mr-1" />发送</Button>
                </CardFooter>
              </Card>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}