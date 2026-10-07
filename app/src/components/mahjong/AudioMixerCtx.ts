import * as React from 'react';
import type { AudioCfg } from '@/types/morev3';
import { getAudioCfg } from './mahjongAudio';

/**
 * 音频混音器上下文 + 消费 Hook。
 *
 * 单独成文件（而非与组件同文件）：让 AudioMixer.tsx 只导出组件，
 * 满足 react-refresh 的 Fast Refresh 约束。
 */
export const AudioMixerCtx = React.createContext<{
  cfg: AudioCfg;
  setCfg: (c: AudioCfg) => void;
  resumeAudio: () => void;
}>({
  cfg: getAudioCfg(),
  setCfg: () => {},
  resumeAudio: () => {},
});

export function useAudioMixer() {
  return React.useContext(AudioMixerCtx);
}
