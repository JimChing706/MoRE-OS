import { useState, useEffect, useSyncExternalStore, useCallback } from 'react';
import { apiService } from '@/services/apiService';

/**
 * 全局 API 健康状态 Hook。
 * 使用 useSyncExternalStore 确保所有组件共享同一份健康状态，避免重复订阅。
 */

let _globalPollingCleanup: (() => void) | null = null;

function ensurePolling() {
  if (!_globalPollingCleanup) {
    _globalPollingCleanup = apiService.startHealthPolling();
  }
  return _globalPollingCleanup;
}

function subscribeHealth(onStoreChange: () => void): () => void {
  ensurePolling();
  return apiService.onHealthChange(() => onStoreChange());
}

function getHealthSnapshot(): boolean {
  return apiService.healthOnline;
}

function getVersionSnapshot(): string {
  return apiService.healthVersion;
}

export function useApiHealth(): {
  online: boolean;
  version: string;
  checkNow: () => Promise<boolean>;
} {
  const online = useSyncExternalStore(subscribeHealth, getHealthSnapshot);
  const version = useSyncExternalStore(subscribeHealth, getVersionSnapshot);

  const checkNow = useCallback(async () => {
    return await apiService.checkHealth();
  }, []);

  // Ensure polling runs even if no component subscribes to the store
  useEffect(() => {
    const cleanup = ensurePolling();
    return cleanup;
  }, []);

  return { online, version, checkNow };
}

export { apiService };
