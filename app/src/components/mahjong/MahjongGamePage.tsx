import * as React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { MahjongTable } from './MahjongTable';
import {
  AudioMixerProvider,
  SettingsPanel as AudioSettingsPanel,
  resumeAudio,
  playDraw,
  playDiscard,
  playChow,
  playPung,
  playKong,
  playDrawGame,
  playHu,
  playCascade,
} from './AudioMixer';
import { useMahjongSocket } from '@/hooks/useMahjongSocket';
import type { GameState, Ruleset } from '@/types/morev3';

const RULESET_OPTIONS: Array<{ id: Ruleset; label: string; desc: string }> = [
  { id: 'guobiao', label: '国标麻将', desc: '8 番起胡 · 标准规则' },
  { id: 'sichuan_xuemen', label: '四川缺门血战', desc: '缺一门 · 血战到底' },
  { id: 'guangdong', label: '广东麻将', desc: '鸡平胡 · 简单易上手' },
];

function useWindowSize() {
  const [size, setSize] = React.useState({
    w: typeof window !== 'undefined' ? window.innerWidth : 1024,
    h: typeof window !== 'undefined' ? window.innerHeight : 768,
  });
  React.useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return size;
}

const SEAT_WIND = ['东', '南', '西', '北'];

function FanTypeList({ fanTypes }: { fanTypes: string[] }) {
  const zhMap: Record<string, string> = {
    pinghu: '平胡',
    duanyaojiu: '断幺九',
    yizhihua: '一番花',
    menqing: '门清',
    duiyiduihu: '对对胡',
    qidui: '七对',
    hunyise: '混一色',
    qingyise: '清一色',
    zimo: '自摸',
    ron: '荣和',
    lidong: '立直',
    duora: '多宝牌',
    haidiyue: '海底捞月',
    hediwumao: '河底摸鱼',
    gangshangkaihua: '杠上开花',
    sananke: '三暗刻',
    sikelike: '四暗刻',
    datongsan: '大三元',
    xiaosanyuan: '小三元',
    daqixi: '大四喜',
    xiaoqixi: '小四喜',
    shibaluohan: '十八罗汉',
    jiulianbaodeng: '九莲宝灯',
    guoshuang: '国士无双',
  };
  return (
    <div className="flex flex-wrap gap-2">
      {fanTypes.map((f) => (
        <span
          key={f}
          className="px-2 py-1 rounded-md bg-amber-100 text-amber-800 text-sm border border-amber-200"
        >
          {zhMap[f] || f}
        </span>
      ))}
    </div>
  );
}

function ScoreHud({
  gameState,
  mySeatIdx,
}: {
  gameState: GameState;
  mySeatIdx: number;
}) {
  return (
    <div className="grid grid-cols-4 gap-2 w-full">
      {[0, 1, 2, 3].map((s) => {
        const seat = gameState.seats[s];
        const isMe = s === mySeatIdx;
        const isTurn = s === gameState.currentTurn;
        const isDealer = seat?.isDealer;
        return (
          <Card
            key={s}
            className={`py-2 px-3 ${
              isTurn
                ? 'border-amber-400 ring-2 ring-amber-300/60 shadow-md'
                : ''
            } ${isMe ? 'bg-orange-50 border-orange-300' : ''}`}
          >
            <CardContent className="p-0 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-700 flex items-center gap-1">
                  {isDealer && (
                    <span className="text-red-500 font-bold text-[10px]">庄</span>
                  )}
                  {seat?.playerName || SEAT_WIND[s]}
                  <span className="text-[10px] text-slate-400 ml-1">
                    {SEAT_WIND[s]}
                  </span>
                </span>
                {isTurn && (
                  <span className="text-[10px] bg-amber-400 text-amber-950 rounded px-1.5 py-0.5 font-semibold animate-pulse">
                    回合
                  </span>
                )}
              </div>
              <div className="text-base font-bold tabular-nums text-slate-900">
                {seat?.score ?? 0}
              </div>
              {seat && (
                <div className="text-[10px] text-slate-500">
                  手牌 {seat.hand.length} · 剩余牌 {gameState.wallRemaining}
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

interface InnerPageProps {
  roomId: string;
  playerUuid: string;
  playerName: string;
}

const DEFAULT_ROOM_ID = 'demo_room';
const DEFAULT_UUID = 'demo_uuid_local';
const DEFAULT_NAME = '你';

function MahjongGamePageInner({
  roomId,
  playerUuid,
  playerName,
}: InnerPageProps) {
  const [selectedTileIdx, setSelectedTileIdx] = React.useState<number | null>(null);
  const [mySeatIdx] = React.useState(0);
  const [showCreateRoom, setShowCreateRoom] = React.useState(false);
  const [showSettings, setShowSettings] = React.useState(false);
  const [showWinResult, setShowWinResult] = React.useState(false);
  const [minFan, setMinFan] = React.useState(2);
  const [ruleset, setRuleset] = React.useState<Ruleset>('guangdong');
  const [aiSeats, setAiSeats] = React.useState<[boolean, boolean, boolean, boolean]>([
    false,
    true,
    true,
    true,
  ]);
  const { w: vw } = useWindowSize();
  const mobile = vw < 520;
  const prevHuRef = React.useRef<string | null>(null);
  const {
    gameState,
    connected,
    sendDiscard,
    sendChow,
    sendPung,
    sendKong,
    sendRon,
    sendSkip,
    sendStart,
    sendReorder,
  } = useMahjongSocket(roomId, playerUuid, {
    onEventDraw: (_seatIdx, _tile, actionId) => {
      resumeAudio();
      playDraw(actionId);
    },
    onEventDiscard: (_seatIdx, _tile, actionId) => {
      resumeAudio();
      playDiscard(actionId);
    },
    onEventChow: (_seatIdx, _meld, actionId) => {
      resumeAudio();
      playChow(actionId);
    },
    onEventPung: (_seatIdx, _meld, actionId) => {
      resumeAudio();
      playPung(actionId);
    },
    onEventKong: (_seatIdx, _meld, actionId) => {
      resumeAudio();
      playKong(actionId);
    },
    onEventDrawGame: (actionId) => {
      resumeAudio();
      playDrawGame(actionId);
    },
    onEventHu: (result, actionId) => {
      resumeAudio();
      playHu(actionId);
      const key = `${result.winnerSeat}_${result.fanTypes.join(',')}_${Date.now()}`;
      prevHuRef.current = key;
      setShowWinResult(true);
    },
    onEventCascade: (level, _actionId) => {
      resumeAudio();
      playCascade(level);
    },
  });
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      const k = e.key.toLowerCase();
      if (k === 'c') {
        sendChow();
        e.preventDefault();
      } else if (k === 'p') {
        sendPung();
        e.preventDefault();
      } else if (k === 'k') {
        sendKong();
        e.preventDefault();
      } else if (k === 'h') {
        sendRon();
        e.preventDefault();
      } else if (k === 's') {
        sendSkip();
        e.preventDefault();
      } else if (k === 'enter') {
        if (gameState.phase === 'waiting') {
          const arr: number[] = [];
          aiSeats.forEach((v, i) => {
            if (v && i !== mySeatIdx) arr.push(i);
          });
          sendStart(ruleset, minFan, arr);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [gameState.phase, aiSeats, ruleset, minFan, sendChow, sendPung, sendKong, sendRon, sendSkip, sendStart, mySeatIdx]);
  const fanDisplay = gameState.huResult
    ? `${gameState.huResult.fanCount}番`
    : `${gameState.round}局`;
  const myHand = gameState.seats[mySeatIdx]?.hand ?? [];
  const hasCallsForMe = gameState.pendingCalls.some((c) => c.seatIdx === mySeatIdx);
  void playerName;
  const callKinds = gameState.pendingCalls
    .filter((c) => c.seatIdx === mySeatIdx)
    .map((c) => c.callKind);
  const canChow = callKinds.includes('chow');
  const canPung = callKinds.includes('pung');
  const canKong = callKinds.includes('kong') || callKinds.includes('concealed_kong');
  const canHu = callKinds.includes('hu');
  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-3 md:p-6">
      <div className="max-w-6xl mx-auto space-y-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div>
            <h1 className="text-xl md:text-2xl font-bold tracking-wide text-amber-100">
              🀄 麻将 ·{' '}
              <span className="text-amber-300">
                {RULESET_OPTIONS.find((r) => r.id === gameState.ruleset)?.label ||
                  '广东麻将'}
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              {connected ? (
                <span className="text-emerald-400">服务器已连接</span>
              ) : (
                <span className="text-rose-400">未连接 (演示模式)</span>
              )}{' '}
              · 房间 {gameState.roomId || roomId}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Dialog open={showCreateRoom} onOpenChange={setShowCreateRoom}>
                  <DialogTrigger asChild>
                    <Button size="sm" variant="secondary">
                      创建 / 开局
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>创建麻将房间</DialogTitle>
                      <DialogDescription>
                        选择规则、番数门槛与 AI 座位分配
                      </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-5 py-2">
                      <div className="space-y-2">
                        <Label>玩法规则</Label>
                        <div className="grid grid-cols-1 gap-2">
                          {RULESET_OPTIONS.map((r) => (
                            <button
                              key={r.id}
                              type="button"
                              onClick={() => setRuleset(r.id)}
                              className={`text-left px-3 py-2 rounded-lg border transition ${
                                ruleset === r.id
                                  ? 'bg-amber-400/10 border-amber-400 ring-1 ring-amber-400'
                                  : 'bg-slate-800/60 border-slate-700 hover:bg-slate-700/60'
                              }`}
                            >
                              <div className="font-semibold">{r.label}</div>
                              <div className="text-xs text-slate-400">{r.desc}</div>
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <Label>最小番数</Label>
                          <span className="text-sm font-semibold tabular-nums text-amber-300">
                            {minFan} 番
                          </span>
                        </div>
                        <Slider
                          value={[minFan]}
                          min={0}
                          max={8}
                          step={1}
                          onValueChange={(v) => setMinFan(v[0])}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>AI 座位分配</Label>
                        <div className="grid grid-cols-4 gap-2">
                          {[0, 1, 2, 3].map((i) => (
                            <div
                              key={i}
                              className={`p-2 rounded-lg border text-center space-y-1 ${
                                i === mySeatIdx
                                  ? 'border-orange-400 bg-orange-400/10'
                                  : 'border-slate-700 bg-slate-800/50'
                              }`}
                            >
                              <div className="text-xs font-semibold">
                                {SEAT_WIND[i]}
                                {i === mySeatIdx && ' (你)'}
                              </div>
                              {i === mySeatIdx ? (
                                <div className="text-[10px] text-orange-300">玩家</div>
                              ) : (
                                <>
                                  <Switch
                                    checked={aiSeats[i]}
                                    onCheckedChange={(v) => {
                                      const next = [...aiSeats] as [
                                        boolean,
                                        boolean,
                                        boolean,
                                        boolean,
                                      ];
                                      next[i] = v;
                                      setAiSeats(next);
                                    }}
                                  />
                                  <div className="text-[10px] text-slate-400">
                                    {aiSeats[i] ? 'AI' : '真人'}
                                  </div>
                                </>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                    <DialogFooter>
                      <Button
                        variant="default"
                        onClick={() => {
                          const arr: number[] = [];
                          aiSeats.forEach((v, i) => {
                            if (v && i !== mySeatIdx) arr.push(i);
                          });
                          sendStart(ruleset, minFan, arr);
                          setShowCreateRoom(false);
                        }}
                      >
                        开始 (Enter)
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </TooltipTrigger>
              <TooltipContent>Enter 键可快速开始</TooltipContent>
            </Tooltip>
            <Dialog open={showSettings} onOpenChange={setShowSettings}>
              <DialogTrigger asChild>
                <Button variant="outline" size="icon-sm" aria-label="设置">
                  <svg
                    viewBox="0 0 24 24"
                    width="16"
                    height="16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>麻将音频设置</DialogTitle>
                  <DialogDescription>
                    首次点击出牌或按钮后音频自动启动
                  </DialogDescription>
                </DialogHeader>
                <AudioSettingsPanel />
              </DialogContent>
            </Dialog>
          </div>
        </div>
        <ScoreHud gameState={gameState} mySeatIdx={mySeatIdx} />
        <Card className="bg-slate-800/70 border-slate-700 overflow-hidden">
          <CardContent className="p-2 md:p-3">
            <MahjongTable
              gameState={gameState}
              mySeatIdx={mySeatIdx}
              selectedTileIdx={selectedTileIdx}
              onSelectTile={(idx) => setSelectedTileIdx(idx)}
              onReorder={(perm) => {
                sendReorder(perm);
              }}
              onDiscardTile={(idx) => {
                sendDiscard(idx);
                setSelectedTileIdx(null);
                resumeAudio();
                playDiscard(`discard_${Date.now()}`);
              }}
              fanDisplay={fanDisplay}
              onUserGesture={() => resumeAudio()}
            />
          </CardContent>
        </Card>
        {!mobile && (
          <Card className="bg-slate-800/70 border-slate-700">
            <CardContent className="p-3 flex flex-wrap gap-2 justify-center items-center">
              <Button
                variant="outline"
                disabled={!canChow || !hasCallsForMe}
                onClick={() => sendChow()}
              >
                吃 (C)
              </Button>
              <Button
                variant="outline"
                disabled={!canPung || !hasCallsForMe}
                onClick={() => sendPung()}
              >
                碰 (P)
              </Button>
              <Button
                variant="outline"
                disabled={!canKong || !hasCallsForMe}
                onClick={() => sendKong()}
              >
                杠 (K)
              </Button>
              <Button
                variant="destructive"
                disabled={!canHu || !hasCallsForMe}
                onClick={() => sendRon()}
              >
                胡 (H)
              </Button>
              <Button
                variant="ghost"
                disabled={!hasCallsForMe}
                onClick={() => sendSkip()}
              >
                跳过 (S)
              </Button>
              <div className="w-px h-8 bg-slate-700 mx-2" />
              <Button
                variant="secondary"
                disabled={myHand.length === 0}
                onClick={() => {
                  sendReorder([...Array(myHand.length).keys()]);
                }}
              >
                理牌
              </Button>
              {selectedTileIdx !== null && (
                <Button
                  variant="default"
                  onClick={() => {
                    sendDiscard(selectedTileIdx);
                    setSelectedTileIdx(null);
                    resumeAudio();
                    playDiscard(`discard_btn_${Date.now()}`);
                  }}
                >
                  出牌 (第{selectedTileIdx + 1}张)
                </Button>
              )}
            </CardContent>
          </Card>
        )}
        {mobile && (
          <MobileActionBar
            canChow={canChow && hasCallsForMe}
            canPung={canPung && hasCallsForMe}
            canKong={canKong && hasCallsForMe}
            canHu={canHu && hasCallsForMe}
            hasCalls={hasCallsForMe}
            selectedTileIdx={selectedTileIdx}
            handCount={myHand.length}
            onChow={() => sendChow()}
            onPung={() => sendPung()}
            onKong={() => sendKong()}
            onHu={() => sendRon()}
            onSkip={() => sendSkip()}
            onLeft={() =>
              setSelectedTileIdx((s) =>
                s === null ? 0 : Math.max(0, s - 1),
              )
            }
            onRight={() =>
              setSelectedTileIdx((s) =>
                s === null
                  ? Math.max(0, myHand.length - 1)
                  : Math.min(myHand.length - 1, s + 1),
              )
            }
            onDiscard={() => {
              if (selectedTileIdx !== null) {
                sendDiscard(selectedTileIdx);
                setSelectedTileIdx(null);
                resumeAudio();
                playDiscard(`discard_m_${Date.now()}`);
              }
            }}
            onOrganize={() => {
              if (myHand.length > 0)
                sendReorder([...Array(myHand.length).keys()]);
            }}
          />
        )}
        <Dialog
          open={showWinResult}
          onOpenChange={(v) => {
            setShowWinResult(v);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="text-center text-xl">
                🎉 胡牌 · {gameState.huResult?.fanCount ?? 0} 番
              </DialogTitle>
              <DialogDescription className="text-center">
                {gameState.huResult?.isRon
                  ? '荣和 (点炮)'
                  : '自摸'}
                {' · '}
                赢家：
                {gameState.seats[gameState.huResult?.winnerSeat ?? 0]?.playerName ||
                  '赢家'}
              </DialogDescription>
            </DialogHeader>
            {gameState.huResult && (
              <div className="space-y-3">
                <div>
                  <Label>番型</Label>
                  <div className="mt-2">
                    <FanTypeList fanTypes={gameState.huResult.fanTypes} />
                  </div>
                </div>
                <div>
                  <Label>分数变动</Label>
                  <div className="mt-2 grid grid-cols-4 gap-2">
                    {gameState.huResult.deltaScores.map((d, i) => {
                      const name =
                        gameState.seats[i]?.playerName || SEAT_WIND[i];
                      const good = d > 0;
                      const bad = d < 0;
                      return (
                        <div
                          key={i}
                          className={`p-2 rounded-md border text-center ${
                            good
                              ? 'bg-emerald-400/10 border-emerald-400/40 text-emerald-300'
                              : bad
                                ? 'bg-rose-400/10 border-rose-400/40 text-rose-300'
                                : 'bg-slate-800 border-slate-700 text-slate-300'
                          }`}
                        >
                          <div className="text-[10px] opacity-80">{name}</div>
                          <div className="text-sm font-bold tabular-nums">
                            {d >= 0 ? `+${d}` : d}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
            <DialogFooter className="flex-row justify-end">
              <Button
                onClick={() => {
                  setShowWinResult(false);
                  const arr: number[] = [];
                  aiSeats.forEach((v, i) => {
                    if (v && i !== mySeatIdx) arr.push(i);
                  });
                  sendStart(ruleset, minFan, arr);
                }}
              >
                再来一局
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

interface MobileActionBarProps {
  canChow: boolean;
  canPung: boolean;
  canKong: boolean;
  canHu: boolean;
  hasCalls: boolean;
  selectedTileIdx: number | null;
  handCount: number;
  onChow: () => void;
  onPung: () => void;
  onKong: () => void;
  onHu: () => void;
  onSkip: () => void;
  onLeft: () => void;
  onRight: () => void;
  onDiscard: () => void;
  onOrganize: () => void;
}

function MobileActionBar(props: MobileActionBarProps) {
  const {
    canChow,
    canPung,
    canKong,
    canHu,
    hasCalls,
    selectedTileIdx,
    handCount,
    onChow,
    onPung,
    onKong,
    onHu,
    onSkip,
    onLeft,
    onRight,
    onDiscard,
    onOrganize,
  } = props;
  const Btn = ({
    children,
    onClick,
    disabled,
    variant = 'secondary',
    compact,
  }: {
    children: React.ReactNode;
    onClick: () => void;
    disabled?: boolean;
    variant?: 'default' | 'secondary' | 'outline' | 'destructive' | 'ghost';
    compact?: boolean;
  }) => (
    <Button
      size={compact ? 'sm' : 'default'}
      variant={variant}
      disabled={disabled}
      onClick={onClick}
      className={compact ? 'flex-1 text-xs' : 'flex-1'}
    >
      {children}
    </Button>
  );
  return (
    <Card className="bg-slate-800/90 border-slate-700 sticky bottom-2">
      <CardContent className="p-2 space-y-2">
        <div className="grid grid-cols-5 gap-1">
          <Btn
            variant="outline"
            onClick={onChow}
            disabled={!canChow || !hasCalls}
            compact
          >
            吃
          </Btn>
          <Btn
            variant="outline"
            onClick={onPung}
            disabled={!canPung || !hasCalls}
            compact
          >
            碰
          </Btn>
          <Btn
            variant="outline"
            onClick={onKong}
            disabled={!canKong || !hasCalls}
            compact
          >
            杠
          </Btn>
          <Btn
            variant="destructive"
            onClick={onHu}
            disabled={!canHu || !hasCalls}
            compact
          >
            胡
          </Btn>
          <Btn
            variant="ghost"
            onClick={onSkip}
            disabled={!hasCalls}
            compact
          >
            跳
          </Btn>
        </div>
        <div className="grid grid-cols-4 gap-2">
          <Btn onClick={onLeft} compact>
            ◀
          </Btn>
          <Btn onClick={onRight} compact>
            ▶
          </Btn>
          <Btn
            variant="default"
            onClick={onDiscard}
            disabled={selectedTileIdx === null}
            compact
          >
            出牌{selectedTileIdx !== null ? `#${selectedTileIdx + 1}` : ''}
          </Btn>
          <Btn onClick={onOrganize} disabled={handCount === 0} compact>
            理牌
          </Btn>
        </div>
      </CardContent>
    </Card>
  );
}

export function MahjongGamePage() {
  return (
    <AudioMixerProvider>
      <MahjongGamePageInner
        roomId={DEFAULT_ROOM_ID}
        playerUuid={DEFAULT_UUID}
        playerName={DEFAULT_NAME}
      />
    </AudioMixerProvider>
  );
}

export default MahjongGamePage;
