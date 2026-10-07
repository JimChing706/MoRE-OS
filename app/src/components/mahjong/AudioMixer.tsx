import * as React from 'react';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import type { AudioCfg } from '@/types/morev3';
import { AudioMixerCtx, useAudioMixer } from './AudioMixerCtx';
import {
  getAudioCfg,
  isBgmPlaying,
  playDiscard,
  resumeAudio,
  setAudioCfg,
  stopAllBgm,
  subscribeAudioCfg,
  toggleBgm,
} from './mahjongAudio';

export function AudioMixerProvider({ children }: { children: React.ReactNode }) {
  const [cfg, setCfgState] = React.useState<AudioCfg>(getAudioCfg);
  React.useEffect(
    () => subscribeAudioCfg((c: AudioCfg) => setCfgState({ ...c })),
    [],
  );
  const setCfg = React.useCallback((next: AudioCfg) => {
    setAudioCfg(next);
    setCfgState({ ...next });
    if (!next.bgmOn) stopAllBgm();
  }, []);
  const doResume = React.useCallback(() => {
    resumeAudio();
  }, []);
  const value = React.useMemo(
    () => ({ cfg, setCfg, resumeAudio: doResume }),
    [cfg, setCfg, doResume],
  );
  return <AudioMixerCtx.Provider value={value}>{children}</AudioMixerCtx.Provider>;
}

export function SettingsPanel() {
  const { cfg, setCfg, resumeAudio: resume } = useAudioMixer();
  // 本地镜像「BGM 是否在播」，否则按钮文案在点击后不会刷新。
  const [bgmPlaying, setBgmPlaying] = React.useState<boolean>(() => isBgmPlaying());
  const testSfx = React.useCallback(() => {
    resume();
    playDiscard();
  }, [resume]);
  const testBgm = React.useCallback(() => {
    resume();
    toggleBgm();
    setBgmPlaying(isBgmPlaying());
  }, [resume]);
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">音效音量</p>
            <p className="text-xs text-muted-foreground">{cfg.sfx}%</p>
          </div>
          <Switch
            checked={cfg.sfxOn}
            onCheckedChange={(v) => setCfg({ ...cfg, sfxOn: v })}
          />
        </div>
        <Slider
          disabled={!cfg.sfxOn}
          value={[cfg.sfx]}
          min={0}
          max={100}
          step={1}
          onValueChange={(v) => setCfg({ ...cfg, sfx: v[0] })}
        />
        <Button size="sm" variant="outline" onClick={testSfx}>
          测试音效
        </Button>
      </div>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">背景音乐</p>
            <p className="text-xs text-muted-foreground">{cfg.bgm}%</p>
          </div>
          <Switch
            checked={cfg.bgmOn}
            onCheckedChange={(v) => {
              setCfg({ ...cfg, bgmOn: v });
              if (v) resume();
            }}
          />
        </div>
        <Slider
          disabled={!cfg.bgmOn}
          value={[cfg.bgm]}
          min={0}
          max={100}
          step={1}
          onValueChange={(v) => setCfg({ ...cfg, bgm: v[0] })}
        />
        <Button size="sm" variant="outline" onClick={testBgm}>
          {bgmPlaying ? '停止试听 BGM' : '试听 BGM'}
        </Button>
      </div>
    </div>
  );
}
