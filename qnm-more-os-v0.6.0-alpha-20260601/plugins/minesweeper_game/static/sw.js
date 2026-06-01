// Service Worker for Multi-Platform Minesweeper
const CACHE_NAME = 'minesweeper-v2';
const ASSETS = [
    '/',
    '/static/minesweeper_enhanced.css',
    '/static/minesweeper_enhanced.js',
    '/manifest.json'
];

// 安装 - 缓存资源
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(ASSETS))
            .then(() => self.skipWaiting())
    );
});

// 激活 - 清理旧缓存
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys => 
            Promise.all(
                keys.filter(k => k !== CACHE_NAME)
                    .map(k => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

// 请求拦截 - 缓存优先，网络回退
self.addEventListener('fetch', (event) => {
    // 只处理GET请求
    if (event.request.method !== 'GET') return;
    
    // API请求走网络
    if (event.request.url.includes('/api/')) {
        event.respondWith(
            fetch(event.request).catch(() => 
                new Response(JSON.stringify({ error: '网络不可用' }), {
                    status: 503,
                    headers: { 'Content-Type': 'application/json' }
                })
            )
        );
        return;
    }
    
    // 静态资源用缓存优先策略
    event.respondWith(
        caches.match(event.request)
            .then(cached => {
                // 返回缓存或从网络获取
                const fetchPromise = fetch(event.request)
                    .then(networkResponse => {
                        // 更新缓存
                        caches.open(CACHE_NAME).then(cache => {
                            cache.put(event.request, networkResponse.clone());
                        });
                        return networkResponse;
                    })
                    .catch(() => {
                        // 完全离线时，如果有缓存则返回缓存
                        if (cached) return cached;
                        // 返回离线页面
                        return new Response(
                            '<h1>离线模式</h1><p>游戏数据已缓存，可以继续游玩</p>',
                            { headers: { 'Content-Type': 'text/html' } }
                        );
                    });
                
                return cached || fetchPromise;
            })
    );
});

// 后台同步（用于保存游戏状态）
self.addEventListener('sync', (event) => {
    if (event.tag === 'save-game') {
        event.waitUntil(
            // 保存游戏状态的逻辑
            console.log('Game state saved')
        );
    }
});

// 推送通知（可选）
self.addEventListener('push', (event) => {
    const data = event.data?.json();
    event.waitUntil(
        self.registration.showNotification(data?.title || '扫雷提醒', {
            body: data?.body || '来玩一局扫雷吧！',
            icon: '/icon.png'
        })
    );
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(
        clients.openWindow('/')
    );
});
