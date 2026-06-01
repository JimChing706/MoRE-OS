/**
 * 跨平台扫雷游戏 - 增强版
 * Multi-Platform Minesweeper - Enhanced Edition
 * 
 * 支持平台:
 * - 📱 iOS (iPhone/iPad)
 * - 🤖 Android
 * - 💻 Windows/macOS/Linux (桌面浏览器)
 * - 🖥️ 笔记本/台式机
 * - 📱 小屏设备到大屏设备自适应
 */

class MultiPlatformMinesweeper {
    constructor() {
        this.gameId = null;
        this.ws = null;
        this.autoPlay = false;
        this.autoPlayTask = null;
        this.timerInterval = null;
        this.elapsed = 0;
        this.startTime = null;
        
        // 平台检测
        this.platform = this.detectPlatform();
        this.setupPlatformSpecific();
        
        // 交互状态
        this.touchStartTime = 0;
        this.touchTimer = null;
        this.longPressThreshold = 500; // 长按阈值(ms)
        this.isLongPress = false;
        this.chordMouseDown = false;
        
        // DOM元素
        this.boardEl = document.getElementById('gameBoard');
        this.timerEl = document.getElementById('timer');
        this.flagsEl = document.getElementById('flags');
        this.minesEl = document.getElementById('mines');
        
        this.init();
    }
    
    /**
     * 平台检测
     */
    detectPlatform() {
        const ua = navigator.userAgent;
        const platform = navigator.platform;
        
        if (/iPad|iPhone|iPod/.test(ua)) return 'ios';
        if (/Android/.test(ua)) return 'android';
        if (/Win/.test(platform)) return 'windows';
        if (/Mac/.test(platform)) return 'macos';
        if (/Linux/.test(platform)) return 'linux';
        return 'unknown';
    }
    
    /**
     * 平台特定设置
     */
    setupPlatformSpecific() {
        // 设置平台标识
        const badge = document.getElementById('platformBadge');
        const platformIcons = {
            ios: '🍎 iOS',
            android: '🤖 Android',
            windows: '💻 Windows',
            macos: '🍎 macOS',
            linux: '🐧 Linux'
        };
        badge.textContent = platformIcons[this.platform] || '🌐 Web';
        
        // 添加平台CSS类
        document.body.classList.add(`platform-${this.platform}`);
        
        // 显示正确的操作提示
        const touchHint = document.getElementById('touchHint');
        const mouseHint = document.getElementById('mouseHint');
        
        if (['ios', 'android'].includes(this.platform)) {
            touchHint.style.display = 'flex';
            mouseHint.style.display = 'none';
        } else {
            touchHint.style.display = 'none';
            mouseHint.style.display = 'flex';
        }
        
        // 桌面平台使用更灵敏的Chord检测
        if (['windows', 'macos', 'linux'].includes(this.platform)) {
            this.chordThreshold = 150; // 更短的按压时间
        } else {
            this.chordThreshold = 200;
        }
    }
    
    init() {
        this.initEventListeners();
        this.newGame('beginner');
        this.log('欢迎使用跨平台扫雷！', 'info');
    }
    
    initEventListeners() {
        // 控制按钮
        document.getElementById('newGameBtn').addEventListener('click', 
            () => this.newGame(document.getElementById('difficulty').value));
        document.getElementById('autoPlayBtn').addEventListener('click', 
            () => this.startAutoPlay());
        document.getElementById('stopBtn').addEventListener('click', 
            () => this.stopAutoPlay());
    }
    
    async newGame(difficulty = 'beginner') {
        this.stopAutoPlay();
        this.stopTimer();

        let customConfig = null;
        if (difficulty === 'custom') {
            customConfig = this.getCustomConfig();
            if (!customConfig) {
                this.log('请先设置自定义配置', 'error');
                return;
            }
        }

        try {
            const resp = await fetch('/api/v1/minesweeper/new', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ difficulty, custom_config: customConfig, first_click_safe: true }),
            });
            const data = await resp.json();

            if (data.detail) {
                this.log(`创建失败: ${data.detail}`, 'error');
                return;
            }

            this.gameId = data.game_id;
            this.elapsed = 0;
            this.startTime = null;

            this.renderBoard(data.state);
            this.updateStats(data.state);
            this.log(`新游戏开始 [${difficulty}]`, 'success');

            document.getElementById('gameOverModal').style.display = 'none';

        } catch (err) {
            this.log(`创建游戏失败: ${err.message}`, 'error');
        }
    }

    getCustomConfig() {
        const width = parseInt(prompt('请输入宽度 (8-100):', '16'));
        const height = parseInt(prompt('请输入高度 (8-100):', '16'));
        const mines = parseInt(prompt('请输入地雷数:', '40'));

        if (!width || !height || !mines || width < 1 || height < 1 || mines < 1) {
            this.log('无效的输入', 'error');
            return null;
        }

        return { width, height, mines };
    }
    }
    
    renderBoard(state) {
        const cells = state.cells;
        this.boardEl.innerHTML = '';
        
        // 设置网格列数
        this.boardEl.style.gridTemplateColumns = 
            `repeat(${state.config.width}, var(--cell-size))`;
        
        // 更新地雷数显示
        this.minesEl.textContent = state.config.num_mines;
        
        // 使用文档片段提高性能
        const fragment = document.createDocumentFragment();
        
        cells.forEach((row, x) => {
            row.forEach((cell, y) => {
                const cellEl = this.createCellElement(cell, x, y);
                fragment.appendChild(cellEl);
            });
        });
        
        this.boardEl.appendChild(fragment);
        this.updateStats(state);
    }
    
    createCellElement(cell, x, y) {
        const cellEl = document.createElement('div');
        cellEl.className = `cell ${cell.state}`;
        cellEl.dataset.x = x;
        cellEl.dataset.y = y;
        
        // 设置内容
        if (cell.state === 'revealed' && !cell.is_mine) {
            cellEl.textContent = cell.adjacent_mines || '';
            cellEl.dataset.num = cell.adjacent_mines;
            
            // 数字颜色
            const colors = {
                1: '#4fc3f7', 2: '#66bb6a', 3: '#ef5350',
                4: '#7e57c2', 5: '#ff7043', 6: '#26c6da',
                7: '#ce93d8', 8: '#546e7a'
            };
            if (cell.adjacent_mines > 0) {
                cellEl.style.color = colors[cell.adjacent_mines] || '#fff';
            }
        } else if (cell.state === 'flagged') {
            cellEl.dataset.flagged = 'true';
        } else if (cell.state === 'mine' && cell.is_mine) {
            cellEl.textContent = '💣';
        }
        
        // 绑定事件
        this.bindCellEvents(cellEl, x, y, cell);
        
        return cellEl;
    }
    
    bindCellEvents(cellEl, x, y, cell) {
        // === 触摸事件 (移动端) ===
        if (['ios', 'android'].includes(this.platform)) {
            // 触摸开始 - 检测长按
            cellEl.addEventListener('touchstart', (e) => {
                e.preventDefault();
                this.touchStartTime = Date.now();
                
                this.touchTimer = setTimeout(() => {
                    this.isLongPress = true;
                    this.handleLongPress(x, y, cell);
                }, this.longPressThreshold);
            }, { passive: false });
            
            // 触摸结束
            cellEl.addEventListener('touchend', (e) => {
                e.preventDefault();
                
                if (this.touchTimer) {
                    clearTimeout(this.touchTimer);
                    this.touchTimer = null;
                }
                
                const touchDuration = Date.now() - this.touchStartTime;
                
                if (!this.isLongPress && touchDuration < this.longPressThreshold) {
                    // 短按 - 翻开或Chord
                    this.handleShortPress(x, y, cell);
                }
                
                this.isLongPress = false;
            }, { passive: false });
            
            // 触摸取消
            cellEl.addEventListener('touchcancel', () => {
                if (this.touchTimer) {
                    clearTimeout(this.touchTimer);
                    this.touchTimer = null;
                }
                this.isLongPress = false;
            });
            
        // === 鼠标事件 (桌面端) ===
        } else {
            // 左键点击 - 翻开
            cellEl.addEventListener('click', (e) => {
                e.preventDefault();
                if (e.button === 0 && !this.autoPlay) {
                    this.handleClick(x, y, 'reveal');
                }
            });
            
            // 右键点击 - 标记
            cellEl.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                this.handleClick(x, y, 'flag');
            });
            
            // 中键点击 - 直接Chord
            cellEl.addEventListener('mousedown', (e) => {
                if (e.button === 1 && cell.state === 'revealed' && 
                    cell.adjacent_mines > 0) {
                    e.preventDefault();
                    this.handleClick(x, y, 'chord');
                }
            });
            
            // 双按钮Chord (左键+右键)
            this.bindMouseChord(cellEl, x, y, cell);
            
            // 触控板/触摸屏支持
            cellEl.addEventListener('touchstart', (e) => {
                e.preventDefault();
                if (cell.state === 'hidden') {
                    this.handleClick(x, y, 'reveal');
                }
            }, { passive: false });
        }
    }
    
    bindMouseChord(cellEl, x, y, cell) {
        let chordActive = false;
        
        cellEl.addEventListener('mousedown', (e) => {
            if (cell.state === 'revealed' && cell.adjacent_mines > 0 && e.button === 0) {
                chordActive = true;
            }
        });
        
        cellEl.addEventListener('mouseup', (e) => {
            if (chordActive && cell.state === 'revealed' && cell.adjacent_mines > 0) {
                // 检查是否右键也按下
                if (e.button === 0 && e.buttons === 0) {
                    // 检查右键是否之前按下
                    this.handleClick(x, y, 'chord');
                }
            }
            chordActive = false;
        });
        
        // 更好的实现：监听全局mouseup检测右键
        let leftDown = false;
        let rightDown = false;
        
        document.addEventListener('mousedown', (e) => {
            if (e.button === 0) leftDown = true;
            if (e.button === 2) rightDown = true;
        });
        
        document.addEventListener('mouseup', (e) => {
            if (cell.state === 'revealed' && cell.adjacent_mines > 0) {
                if (e.button === 0 && leftDown && rightDown) {
                    this.handleClick(x, y, 'chord');
                }
            }
            if (e.button === 0) leftDown = false;
            if (e.button === 2) rightDown = false;
        });
    }
    
    handleShortPress(x, y, cell) {
        if (cell.state === 'hidden') {
            this.handleClick(x, y, 'reveal');
        } else if (cell.state === 'revealed' && cell.adjacent_mines > 0) {
            // iOS上可以用两指轻触或再次点击触发Chord
            this.handleClick(x, y, 'chord');
        }
    }
    
    handleLongPress(x, y, cell) {
        if (this.isLongPress) {
            if (cell.state === 'hidden') {
                this.handleClick(x, y, 'flag');
                this.log('已标记', 'info');
            } else if (cell.state === 'flagged') {
                this.handleClick(x, y, 'reveal');
                this.log('已取消标记', 'info');
            }
        }
    }
    
    async handleClick(x, y, action) {
        if (this.autoPlay || !this.gameId) return;
        
        try {
            const resp = await fetch(
                `/api/v1/minesweeper/${this.gameId}/move`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ x, y, action }),
                }
            );
            
            const data = await resp.json();
            this.renderBoard(data.state);
            this.updateStats(data.state);
            
            // 开始计时
            if (!this.startTime) {
                this.startTimer();
            }
            
            // 游戏结束检查
            if (data.state.result !== 'ongoing') {
                this.stopAutoPlay();
                this.stopTimer();
                this.showGameOver(data.state);
                
                const message = data.state.result === 'won' 
                    ? '🎉 胜利！恭喜完成游戏！' 
                    : '💥 踩雷了！再试一次吧！';
                this.log(message, data.state.result === 'won' ? 'success' : 'error');
            }
            
        } catch (err) {
            this.log(`操作失败: ${err.message}`, 'error');
        }
    }
    
    showGameOver(state) {
        const modal = document.getElementById('gameOverModal');
        const icon = document.getElementById('modalIcon');
        const title = document.getElementById('modalTitle');
        const message = document.getElementById('modalMessage');
        const time = document.getElementById('modalTime');
        const moves = document.getElementById('modalMoves');
        const accuracy = document.getElementById('modalAccuracy');
        
        if (state.result === 'won') {
            icon.textContent = '🏆';
            title.textContent = '恭喜获胜！';
            message.textContent = '太棒了，你成功避开了所有地雷！';
        } else {
            icon.textContent = '💣';
            title.textContent = '游戏结束';
            message.textContent = '踩到地雷了，下次记得小心！';
        }
        
        time.textContent = Math.round(this.elapsed);
        moves.textContent = state.move_count;
        accuracy.textContent = state.cells_revealed > 0 
            ? Math.round((state.cells_revealed / (state.cells_revealed + state.flags_placed)) * 100) 
            : 100;
        
        modal.style.display = 'flex';
    }
    
    updateStats(state) {
        this.flagsEl.textContent = state.flags_placed;
    }
    
    startTimer() {
        this.startTime = Date.now();
        this.timerInterval = setInterval(() => {
            this.elapsed = (Date.now() - this.startTime) / 1000;
            this.timerEl.textContent = Math.round(this.elapsed);
        }, 100);
    }
    
    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }
    
    // ========== AI自动游玩 ==========
    async startAutoPlay() {
        if (!this.gameId) {
            this.log('请先创建游戏', 'error');
            return;
        }
        
        this.autoPlay = true;
        document.getElementById('aiPanel').style.display = 'block';
        this.log('🤖 AI自动游玩启动中...', 'info');
        
        while (this.autoPlay) {
            try {
                const resp = await fetch(
                    `/api/v1/minesweeper/${this.gameId}/state`
                );
                const data = await resp.json();
                
                if (data.state.result !== 'ongoing') {
                    this.stopAutoPlay();
                    break;
                }
                
                // AI决策：寻找确定的安全格子
                const move = this.aiFindSafeMove(data.state);
                if (move) {
                    await this.handleClick(move.x, move.y, move.action);
                } else {
                    // 随机选择一个未翻开的格子
                    const randomMove = this.aiFindRandomMove(data.state);
                    if (randomMove) {
                        await this.handleClick(randomMove.x, randomMove.y, 'reveal');
                    }
                }
                
                await new Promise(r => setTimeout(r, 300));
                
            } catch (err) {
                this.log(`AI错误: ${err.message}`, 'error');
                break;
            }
        }
    }
    
    aiFindSafeMove(state) {
        const cells = state.cells;
        
        // 寻找已翻开的数字格子
        for (let x = 0; x < cells.length; x++) {
            for (let y = 0; y < cells[x].length; y++) {
                const cell = cells[x][y];
                if (cell.state === 'revealed' && cell.adjacent_mines > 0) {
                    
                    let hiddenCount = 0;
                    let flaggedCount = 0;
                    let hiddenCells = [];
                    
                    for (let dx = -1; dx <= 1; dx++) {
                        for (let dy = -1; dy <= 1; dy++) {
                            if (dx === 0 && dy === 0) continue;
                            const nx = x + dx;
                            const ny = y + dy;
                            if (nx >= 0 && nx < cells.length && 
                                ny >= 0 && ny < cells[0].length) {
                                const neighbor = cells[nx][ny];
                                if (neighbor.state === 'hidden') {
                                    hiddenCount++;
                                    hiddenCells.push({ x: nx, y: ny });
                                } else if (neighbor.state === 'flagged') {
                                    flaggedCount++;
                                }
                            }
                        }
                    }
                    
                    // 如果标记数等于数字，说明所有未标记的都是安全的
                    if (flaggedCount === cell.adjacent_mines && hiddenCount > 0) {
                        return { x: hiddenCells[0].x, y: hiddenCells[0].y, action: 'reveal' };
                    }
                    
                    // 如果隐藏数等于剩余的雷数，全部标记
                    const remainingMines = cell.adjacent_mines - flaggedCount;
                    if (hiddenCount === remainingMines && hiddenCount > 0) {
                        return { x: hiddenCells[0].x, y: hiddenCells[0].y, action: 'flag' };
                    }
                }
            }
        }
        
        return null;
    }
    
    aiFindRandomMove(state) {
        const cells = state.cells;
        const hidden = [];
        
        for (let x = 0; x < cells.length; x++) {
            for (let y = 0; y < cells[x].length; y++) {
                if (cells[x][y].state === 'hidden') {
                    hidden.push({ x, y });
                }
            }
        }
        
        if (hidden.length > 0) {
            return hidden[Math.floor(Math.random() * hidden.length)];
        }
        
        return null;
    }
    
    stopAutoPlay() {
        this.autoPlay = false;
        document.getElementById('aiPanel').style.display = 'none';
        this.log('AI已停止', 'info');
    }
    
    log(message, type = 'info') {
        console.log(`[扫雷] ${message}`);
        // 可以扩展为显示在页面上
    }
}

// 全局实例
let game = null;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    game = new MultiPlatformMinesweeper();
    
    // PWA安装提示
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        setTimeout(() => {
            if (confirm('是否将扫雷游戏添加到桌面？')) {
                e.prompt();
            }
        }, 3000);
    });
    
    // 网络状态提示
    window.addEventListener('online', () => {
        game.log('网络已连接', 'success');
    });
    
    window.addEventListener('offline', () => {
        game.log('网络已断开，离线模式', 'warning');
    });
});

// Service Worker注册失败处理
if (!('serviceWorker' in navigator)) {
    console.log('当前浏览器不支持Service Worker');
}
