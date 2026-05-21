                cellEl.addEventListener('contextmenu', (e) => {
                    e.preventDefault();
                    this.handleClick(x, y, 'flag');
                });
                
                // 双键点击快速翻开 (chord): 中键或双按钮同时点击
                cellEl.addEventListener('mousedown', (e) => {
                    if (cell.state === 'revealed' && cell.adjacent_mines > 0) {
                        // 中键点击直接触发chord
                        if (e.button === 1) {
                            e.preventDefault();
                            this.handleClick(x, y, 'chord');
                        }
                    }
                });
                
                // 双键同时按下检测 (标准扫雷chord手势) - 左键+右键
                const onMouseDownChord = (e) => {
                    if (cell.state === 'revealed' && cell.adjacent_mines > 0 && e.button === 0) {
                        // 设置chord模式，监听右键或释放
                        this.boardEl.addEventListener('mouseup', onMouseUpChord);
                        this.boardEl.addEventListener('contextmenu', onContextMenuChord);
                        e.preventDefault();
                    }
                };
                
                const onMouseUpChord = (e) => {
                    if (cell.state === 'revealed' && cell.adjacent_mines > 0) {
                        // 检查是否右键也按下 (buttons是位掩码: 1=左键, 2=右键, 4=中键)
                        if (e.buttons & 2) {
                            this.handleClick(x, y, 'chord');
                        }
                    }
                    cleanupChord();
                };
                
                const onContextMenuChord = (e) => {
                    if (cell.state === 'revealed' && cell.adjacent_mines > 0) {
                        this.handleClick(x, y, 'chord');
                    }
                    e.preventDefault();
                    cleanupChord();
                };
                
                const cleanupChord = () => {
                    this.boardEl.removeEventListener('mouseup', onMouseUpChord);
                    this.boardEl.removeEventListener('contextmenu', onContextMenuChord);
                };
                
                cellEl.addEventListener('mousedown', onMouseDownChord);

                this.boardEl.appendChild(cellEl);